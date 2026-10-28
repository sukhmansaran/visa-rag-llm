"""
Tool registry (M5.1): the read-only tools the router (M5.2) may call, each with typed arguments and results.

Every call goes through `call(name, args)`: the arguments are validated against the tool's argument model before
the tool runs (unknown fields refused, sizes bounded, values checked by code), and the result against its result
model. A model's tool call is only ever a proposal; code decides whether it may run (principle 3). No tool writes
data.

  rules                  the rule engine's facts for a question (ircc_rules.yaml, owner-reviewed)
  knowledge_base_search  chunks from the knowledge base (the same search the pipeline uses)
  live_fetch             one registry page, fetched now; the URL must be a registry page exactly (principle 10).
                         Arguments are checked today; fetching arrives with M5.3, until then it is unavailable
  profile                the requesting user's profile. Takes no arguments: whose profile is never the model's
                         choice; it is the user of the current request. Only fields an answer can use (no names)
  processing_times_link  IRCC's live processing-times tool; Pendu stores no processing-time figures

Calls are traced as step `tool` with the tool name and the result's size, never the arguments (they can hold the
user's words).
"""

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Type

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.services.tracing import current_trace, trace_step

logger = logging.getLogger(__name__)


class ToolError(Exception):
    """A tool call that can't run."""


class UnknownToolError(ToolError):
    pass


class ToolArgumentError(ToolError):
    pass


class ToolUnavailableError(ToolError):
    pass


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------------------------------------------------------------- rules

class RulesArgs(_Args):
    question: str = Field(min_length=3, max_length=1000)
    country: str = Field(default="Canada", max_length=60)


class RulesResult(BaseModel):
    intent: str
    visa_type: str
    facts: Optional[str] = None
    guarantee_fact: Optional[str] = None
    closed_program_fact: Optional[str] = None
    rules_version: str


async def _rules(args: RulesArgs) -> RulesResult:
    from app.services.intent_parser import intent_parser
    from app.services.rule_engine import get_rules_content_hash, rule_engine

    parsed = await intent_parser.parse_intent(args.question)
    intent, visa_type = parsed.get("intent", "general"), parsed.get("visa_type", "Student")
    return RulesResult(
        intent=intent, visa_type=visa_type,
        facts=rule_engine.try_rule_answer(intent, args.country, visa_type, query=args.question),
        guarantee_fact=rule_engine.approval_guarantee_fact(args.question),
        closed_program_fact=rule_engine.discontinued_program_fact(args.question),
        rules_version=get_rules_content_hash())


# ---------------------------------------------------------------- knowledge_base_search

class SearchArgs(_Args):
    query: str = Field(min_length=3, max_length=500)
    top_k: int = Field(default=4, ge=1, le=8)
    country: Optional[str] = Field(default=None, max_length=60)


class SearchChunk(BaseModel):
    url: str
    title: str
    text: str
    score: float
    authority_tier: Optional[int] = None


class SearchResult(BaseModel):
    chunks: List[SearchChunk]


async def _knowledge_base_search(args: SearchArgs) -> SearchResult:
    from app.services.retrieval import retrieval_service

    found = await retrieval_service.retrieve(query=args.query, top_k=args.top_k, country=args.country)
    return SearchResult(chunks=[
        SearchChunk(url=(c.get("metadata") or {}).get("url") or c.get("url") or "",
                    title=(c.get("metadata") or {}).get("title") or c.get("title") or "",
                    text=c.get("text") or "", score=float(c.get("score") or 0.0),
                    authority_tier=c.get("authority_tier"))
        for c in found])


# ---------------------------------------------------------------- live_fetch

class LiveFetchArgs(_Args):
    url: str = Field(max_length=500)

    @field_validator("url")
    @classmethod
    def registry_page_only(cls, url: str) -> str:
        """Exactly a registry page (an exact match, so no query string or fragment can carry the user's words)."""
        from app.services.source_registry import load_registry

        if url not in load_registry().by_url():
            raise ValueError("the URL is not a page in the official source registry")
        return url


class LiveFetchResult(BaseModel):
    url: str
    title: str
    text: str
    fetched_at: str


async def _live_fetch(args: LiveFetchArgs) -> LiveFetchResult:
    raise ToolUnavailableError("live fetch arrives with M5.3")


# ---------------------------------------------------------------- profile

class ProfileArgs(_Args):
    pass


class ProfileResult(BaseModel):
    found: bool
    education_level: Optional[str] = None
    field_of_study: Optional[str] = None
    work_experience_years: Optional[int] = None
    test_scores: Optional[Dict[str, Any]] = None
    target_countries: Optional[Any] = None
    target_universities: Optional[Any] = None


async def _profile(args: ProfileArgs) -> ProfileResult:
    from sqlmodel import select

    from app.core.database import AsyncSessionLocal
    from app.models.profile import Profile

    trace = current_trace()
    user_id = trace.user_id if trace else None
    if user_id is None:
        return ProfileResult(found=False)
    async with AsyncSessionLocal() as session:  # read only: nothing is added or committed
        profile = (await session.execute(select(Profile).where(Profile.user_id == user_id))).scalars().first()
    if profile is None:
        return ProfileResult(found=False)
    return ProfileResult(found=True, education_level=profile.education_level, field_of_study=profile.field_of_study,
                         work_experience_years=profile.work_experience, test_scores=profile.test_scores,
                         target_countries=profile.target_countries, target_universities=profile.target_universities)


# ---------------------------------------------------------------- processing_times_link

class ProcessingTimesArgs(_Args):
    pass


class ProcessingTimesResult(BaseModel):
    url: str
    note: str


async def _processing_times_link(args: ProcessingTimesArgs) -> ProcessingTimesResult:
    from app.services.rule_engine import rule_engine

    rule = rule_engine.rules_data.get("processing_times") or {}
    url = rule.get("source_url")
    if not url:
        raise ToolUnavailableError("ircc_rules.yaml has no processing_times.source_url")
    return ProcessingTimesResult(url=url, note=(
        "IRCC processing times change regularly and depend on the application type and the country you apply from. "
        "Pendu stores no processing-time figures; check IRCC's tool for the current time."))


# ---------------------------------------------------------------- registry

@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args_model: Type[_Args]
    result_model: Type[BaseModel]
    run: Callable[[Any], Awaitable[BaseModel]]
    available: bool = True


TOOLS: Dict[str, Tool] = {t.name: t for t in (
    Tool("rules", "Official figures and rules for a question (proof of funds, language levels, PGWP length, "
                  "closed programs...), from the owner-reviewed rules file.", RulesArgs, RulesResult, _rules),
    Tool("knowledge_base_search", "Search the stored official pages for passages about a question.",
         SearchArgs, SearchResult, _knowledge_base_search),
    Tool("live_fetch", "Fetch one official registry page now, when the stored copy may be out of date.",
         LiveFetchArgs, LiveFetchResult, _live_fetch, available=False),
    Tool("profile", "The asking user's saved profile (education, work experience, test scores, targets).",
         ProfileArgs, ProfileResult, _profile),
    Tool("processing_times_link", "Where to check current IRCC processing times (Pendu stores no figures).",
         ProcessingTimesArgs, ProcessingTimesResult, _processing_times_link),
)}


def tool_specs() -> List[Dict[str, Any]]:
    """The available tools for a model to choose from: name, description and the JSON schema of the arguments."""
    return [{"name": t.name, "description": t.description, "parameters": t.args_model.model_json_schema()}
            for t in TOOLS.values() if t.available]


def validate_args(name: str, args: Optional[Mapping[str, Any]]) -> _Args:
    """The tool's arguments, checked; raises UnknownToolError or ToolArgumentError."""
    tool = TOOLS.get(name)
    if tool is None:
        raise UnknownToolError(f"no tool named {name!r}")
    try:
        return tool.args_model.model_validate(dict(args or {}))
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(map(str, err['loc'])) or 'arguments'}: {err['msg']}" for err in e.errors())
        raise ToolArgumentError(f"{name}: {problems}") from None


async def call(name: str, args: Optional[Mapping[str, Any]] = None) -> BaseModel:
    """Run a tool with checked arguments and return its checked result."""
    parsed = validate_args(name, args)
    tool = TOOLS[name]
    if not tool.available:
        raise ToolUnavailableError(f"{name} is not available yet")
    with trace_step("tool", tool=name) as step:
        result = tool.result_model.model_validate(await tool.run(parsed))
        step["result_chars"] = len(result.model_dump_json())
    return result
