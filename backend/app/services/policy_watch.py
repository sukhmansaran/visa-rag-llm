"""
Policy watch (M7): a background agent that notices when an official page changed and prepares the change for review.

  detect   (M7.1) sweep(): each active registry page is fetched with the hardened live fetcher (main text only, so
           menus and footers don't count). A page that differs from the stored copy lands in the review queue
           (M5.5b) with origin "policy_watch".
  analyse  (M7.2) analyse(): for a pending item, code works out what changed: the lines and numbers removed and
           added, the ircc_rules.yaml keys whose value was on the stored page and is no longer on the new one, and the
           stored chunks that hold removed text. The model writes one or two sentences on the change
           (prompt policy_change); code keeps them only if every number in them is in the diff, otherwise a summary
           written by code is used.
  review   (M7.3) the analysis is saved on the review item and shown to the admin, who approves or rejects as for
           any fetched page; administrators get a notification.

Nothing here edits the rules file or the knowledge base (principle: no auto-edits). A named rule key means "look at
this figure", not "it is wrong".
"""

import difflib
import logging
import re
from typing import Any, Dict, List, Literal, Optional, Set, Tuple

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fetched_page import FetchedPageReview
from app.models.source import Source
from app.models.vector_chunk import VectorChunk

logger = logging.getLogger(__name__)

ORIGIN = "policy_watch"
MAX_DIFF_CHARS = 6000        # of changed lines shown to the model
MAX_LISTED = 40              # numbers, rule keys and chunks listed in an analysis
MIN_FOREIGN_RULE_VALUE = 1000  # a rule from another page is named only for a distinctive figure, not "24" or "7"
_NUMBER = re.compile(r"(?<![\w.])\$?\d[\d,]*(?:\.\d+)?")


class ChangeSummary(BaseModel):
    summary: str = Field(min_length=10, max_length=500)
    kind: Literal["figures", "wording", "structure", "other"]


# ---------------------------------------------------------------- what changed (code)

def numbers_in(text: str) -> Set[str]:
    """Every number in the text, without currency signs and thousands separators: "$23,448" -> "23448"."""
    found = set()
    for token in _NUMBER.findall(text or ""):
        value = token.lstrip("$").replace(",", "").rstrip(".")
        if value:
            found.add(value[:-2] if value.endswith(".0") else value)
    return found


def changed_lines(stored: str, fetched: str) -> Tuple[List[str], List[str]]:
    """(lines only in the stored copy, lines only in the fetched page), in page order."""
    removed, added = [], []
    for line in difflib.ndiff(stored.splitlines(), fetched.splitlines()):
        if line.startswith("- "):
            removed.append(line[2:].strip())
        elif line.startswith("+ "):
            added.append(line[2:].strip())
    return [line for line in removed if line], [line for line in added if line]


def rule_values(rules: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Every numeric value in ircc_rules.yaml as {key, section, value, urls}; urls = the section's source pages."""
    if rules is None:
        from app.services.rule_engine import load_ircc_rules

        rules = load_ircc_rules()
    values: List[Dict[str, Any]] = []

    def urls_of(node: Any) -> Set[str]:
        found: Set[str] = set()
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, str) and str(key).endswith("source_url"):
                    found.add(value)
                else:
                    found |= urls_of(value)
        elif isinstance(node, list):
            for value in node:
                found |= urls_of(value)
        return found

    def walk(node: Any, path: str, section: str, urls: Set[str]) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}" if path else str(key), section, urls)
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]", section, urls)
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            number = str(int(node)) if float(node).is_integer() else str(node)
            values.append({"key": path, "section": section, "value": number, "urls": urls})

    for section, body in rules.items():
        if isinstance(body, (dict, list)):
            walk(body, str(section), str(section), urls_of(body))
    return values


def affected_rules(url: str, removed_numbers: Set[str], rules: Optional[Dict[str, Any]] = None) -> List[Dict[str, str]]:
    """
    Rule keys whose value was on the stored page and is on the new page no longer. A rule sourced from this page
    counts for any figure; a rule sourced elsewhere only for a distinctive one (>= MIN_FOREIGN_RULE_VALUE).
    """
    hits = []
    for rule in rule_values(rules):
        if rule["value"] not in removed_numbers:
            continue
        from_this_page = url in rule["urls"]
        try:
            distinctive = float(rule["value"]) >= MIN_FOREIGN_RULE_VALUE
        except ValueError:
            distinctive = False
        if from_this_page or distinctive:
            hits.append({"key": rule["key"], "value": rule["value"], "section": rule["section"],
                         "sourced_from_this_page": from_this_page})
    hits.sort(key=lambda hit: (not hit["sourced_from_this_page"], hit["key"]))
    return hits[:MAX_LISTED]


async def affected_chunks(db: AsyncSession, document_id: Optional[int], removed: List[str]) -> List[int]:
    """Indexes of the stored version's chunks that contain a removed line: what answers quote from today."""
    if document_id is None or not removed:
        return []
    rows = (await db.execute(select(VectorChunk.chunk_index, VectorChunk.text).where(
        VectorChunk.document_id == document_id, VectorChunk.status != "superseded")
        .order_by(VectorChunk.chunk_index))).all()
    needles = [line for line in removed if len(line) >= 20]
    return [index for index, text in rows if any(needle in text for needle in needles)][:MAX_LISTED]


def code_summary(removed: List[str], added: List[str], numbers_removed: Set[str], numbers_added: Set[str]) -> str:
    parts = [f"{len(removed)} line(s) removed and {len(added)} added."]
    if numbers_removed:
        parts.append("Figures no longer on the page: " + ", ".join(sorted(numbers_removed)[:12]) + ".")
    if numbers_added:
        parts.append("New figures: " + ", ".join(sorted(numbers_added)[:12]) + ".")
    return " ".join(parts)


# ---------------------------------------------------------------- the model's sentence, checked by code

async def model_summary(page: str, removed: List[str], added: List[str]) -> Optional[ChangeSummary]:
    """One or two sentences on the change, or None when the model is unavailable, unreadable or invents a number."""
    from app.core.exceptions import AIServiceUnavailableError, LLMStructuredOutputError
    from app.services.llm import llm_service
    from app.services.prompt_registry import get_prompt

    diff = "\n".join([f"- {line}" for line in removed] + [f"+ {line}" for line in added])[:MAX_DIFF_CHARS]
    system, user = get_prompt("policy_change").render(page=page, diff=diff)
    try:
        result = await llm_service.structured_call(ChangeSummary, system, user, role="agent", max_tokens=220)
    except (LLMStructuredOutputError, AIServiceUnavailableError):
        return None
    except Exception:
        logger.warning("[POLICY WATCH] summary failed", exc_info=True)
        return None
    invented = numbers_in(result.summary) - numbers_in(diff)
    if invented:
        logger.info("[POLICY WATCH] summary dropped: numbers not in the diff: %s", sorted(invented))
        return None
    return result


# ---------------------------------------------------------------- analyse one review item

async def analyse(db: AsyncSession, item: FetchedPageReview, use_model: bool = True) -> Dict[str, Any]:
    """Work out what changed for a pending review item and save it on the item."""
    from app.services import review_queue
    from app.services.prompt_registry import get_prompt

    stored = await review_queue.stored_document(db, item.source_id)
    stored_text = stored.extracted_text if stored else ""
    removed, added = changed_lines(stored_text, item.text)
    gone = numbers_in("\n".join(removed)) - numbers_in(item.text)        # on the stored page, nowhere on the new one
    new = numbers_in("\n".join(added)) - numbers_in(stored_text)
    summary = await model_summary(item.title or item.url, removed, added) if use_model and (removed or added) else None
    analysis = {
        "lines_removed": len(removed), "lines_added": len(added),
        "numbers_removed": sorted(gone)[:MAX_LISTED], "numbers_added": sorted(new)[:MAX_LISTED],
        "rules": affected_rules(item.url, gone),
        "chunks": await affected_chunks(db, stored.id if stored else None, removed),
        "summary": summary.summary if summary else code_summary(removed, added, gone, new),
        "summary_by": "model" if summary else "code",
        "kind": summary.kind if summary else ("figures" if gone or new else "other"),
        "prompt": get_prompt("policy_change").tag if summary else None,
        "first_version": stored is None,
    }
    item.analysis = analysis
    await db.commit()
    return analysis


async def notify_admins(db: AsyncSession, item: FetchedPageReview, analysis: Dict[str, Any]) -> int:
    """A notification for each administrator that a page is waiting, with the summary. No user data involved."""
    from app.models.notification import Notification
    from app.models.user import User

    admins = (await db.execute(select(User.id).where(User.is_admin == True, User.is_active == True))).scalars().all()  # noqa: E712
    rules = ", ".join(rule["key"] for rule in analysis["rules"][:5])
    message = analysis["summary"] + (f" Rules to check: {rules}." if rules else "")
    for admin_id in admins:
        db.add(Notification(user_id=admin_id, title=f"Official page changed: {(item.title or item.url)[:200]}",
                            message=message[:2000], notification_type="system", related_url="/admin"))
    await db.commit()
    return len(admins)


# ---------------------------------------------------------------- the sweep

async def sweep(db: AsyncSession, limit: Optional[int] = None, use_model: bool = True) -> Dict[str, Any]:
    """Fetch every active registry page, then analyse each pending review item that has no analysis yet."""
    from app.services import live_fetch
    from app.services.source_registry import load_registry

    registry_urls = set(load_registry().by_url())
    sources = (await db.execute(select(Source).where(Source.is_active == True)  # noqa: E712
                                .order_by(Source.id))).scalars().all()
    pages = [source for source in sources if source.url in registry_urls][:limit]
    report: Dict[str, Any] = {"pages": len(pages), "fetched": 0, "failed": [], "analysed": []}
    for source in pages:
        try:
            await live_fetch.fetch(source.url, origin=ORIGIN)
            report["fetched"] += 1
        except live_fetch.LiveFetchError as e:
            report["failed"].append({"url": source.url, "reason": str(e)[:120]})
        except Exception as e:  # one page never stops the sweep
            logger.warning("[POLICY WATCH] %s failed", source.url, exc_info=True)
            report["failed"].append({"url": source.url, "reason": type(e).__name__})

    waiting = (await db.execute(select(FetchedPageReview).where(
        FetchedPageReview.status == "pending", FetchedPageReview.analysis.is_(None))
        .order_by(FetchedPageReview.id))).scalars().all()
    for item in waiting:
        analysis = await analyse(db, item, use_model=use_model)
        await notify_admins(db, item, analysis)
        report["analysed"].append({"id": item.id, "url": item.url, "kind": analysis["kind"],
                                   "rules": [rule["key"] for rule in analysis["rules"]]})
    logger.info("[POLICY WATCH] %s pages, %s fetched, %s failed, %s analysed", report["pages"], report["fetched"],
                len(report["failed"]), len(report["analysed"]))
    return report
