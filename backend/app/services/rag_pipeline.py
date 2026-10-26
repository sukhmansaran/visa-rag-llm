"""
Unified RAG Pipeline orchestrator.
Executes the authoritative flow: Guardrail -> Intent -> Rule Engine -> Cache -> Tourist DB -> Strict Retrieval
-> Evidence gate -> Grounded Generation -> Output guardrail -> Legal disclaimer.
One implementation (RAGPipeline._events) serves both the streaming and the non-streaming endpoint.
Enforces the RAG-Only policy: Zero ungrounded hallucinations, zero raw LLM fallbacks.
"""

import logging
import time
from dataclasses import replace
import re
from typing import Dict, Any, Optional, List, AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession


from app.core.config import settings
from app.core.visa_constitution import LEGAL_DISCLAIMER
from app.services.intent_parser import intent_parser
from app.services.rule_engine import rule_engine, get_rules_content_hash
from app.services.cache_service import intent_cache
from app.services.retrieval import retrieval_service
from app.services.vector_store import vector_store
from app.services.llm import llm_service
from app.services.guardrails.input_guardrail import input_guardrail
from app.services.guardrails.output_guardrail import output_guardrail
from app.services.guardrails.legal_disclaimer import legal_disclaimer_engine
from app.services.tourist_service import get_tourist_context
from app.services.tracing import trace_step
from app.services.decomposition import decompose, needs_split
from app.services.evidence import PartResult, answer_part, compose, evidence_context, source_texts
from app.services.iteration import better, refine_query
from app.services.follow_up import resolve as resolve_follow_up
from app.services.topics import detect_topics
from app.services.triage import VERIFIED, routed_path, triage
from app.services.prompt_registry import get_prompt

logger = logging.getLogger(__name__)

# [Source N] (Tier T - title) ... URL: ... (Retrieved: ...) around each chunk in the context (prepare_context)
_CHUNK_FRAMING_CHARS = 200


def _chunk_key(chunk: Dict[str, Any]) -> tuple:
    """A chunk's identity across retrievals: its page and its text."""
    return ((chunk.get("metadata") or {}).get("url") or chunk.get("url"), chunk.get("text"))


# The grounded-answer prompt lives in app/prompts/grounded_answer.yaml (M0.12).

def normalize_markdown_output(text: str) -> str:
    """Ensure bullet points and headers generated on a single line are cleanly spaced with newlines."""
    if not text:
        return text
    text = re.sub(r'([^\n])\s+([*+-]|\d+\.)\s+(\*\*)', r'\1\n\n\2 \3', text)
    text = re.sub(r'([.:;?!])\s+([*+-])\s+([A-Z])', r'\1\n\n\2 \3', text)
    return text


UNVERIFIED_EVIDENCE_REFUSAL = (
    "I cannot find verified official sources in my knowledge base to answer this specific question. "
    "To prevent misinformation, I do not speculate or extrapolate on immigration policies. "
    "Please consult official government portals (such as Immigration, Refugees and Citizenship Canada at https://www.canada.ca) "
    "or consult a licensed Regulated Canadian Immigration Consultant (RCIC)."
)


class RAGPipeline:
    """Orchestrates the authoritative unified RAG flow for both synchronous and streaming chat."""

    @staticmethod
    async def _answer_cache_version() -> str:
        """Cache-key version: rules file hash + knowledge-base fingerprint (B16) + prompt version (M0.12)."""
        try:
            kb_version = await vector_store.content_version()
        except Exception:
            kb_version = "kb-unknown"
        return f"{get_rules_content_hash()}:{kb_version}:{get_prompt('grounded_answer').tag}"

    async def process_query(
        self,
        query: str,
        context_metadata: Optional[Dict[str, Any]] = None,
        chat_history: Optional[List[Dict[str, Any]]] = None,
        db: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """Non-streaming answer: runs the shared pipeline and folds its events into one result.

        Model errors propagate, so the endpoint can map AIServiceUnavailableError to HTTP 503.
        """
        blocked: Optional[Dict[str, Any]] = None
        done: Dict[str, Any] = {}
        async for event in self._events(query, context_metadata, chat_history, db, stream=False):
            if event["type"] == "guardrail_blocked":
                blocked = event
            elif event["type"] == "done":
                done = event

        result: Dict[str, Any] = {
            "answer": done["full_response"],
            "sources": done.get("sources", []),
            "metrics": done["metrics"],
            "guardrail_blocked": blocked is not None,
        }
        if blocked is not None:
            result["violation"] = blocked["violation"]
        return result

    async def process_query_stream(
        self,
        query: str,
        context_metadata: Optional[Dict[str, Any]] = None,
        chat_history: Optional[List[Dict[str, Any]]] = None,
        db: Optional[AsyncSession] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Streaming answer: yields the shared pipeline's events for SSE, with early guardrail interception."""
        async for event in self._events(query, context_metadata, chat_history, db, stream=True):
            yield event

    async def _events(
        self,
        query: str,
        context_metadata: Optional[Dict[str, Any]],
        chat_history: Optional[List[Dict[str, Any]]],
        db: Optional[AsyncSession],
        stream: bool,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        The one implementation of the chat pipeline (M0.3).

        Yields events: {"type": "guardrail_blocked"}, {"type": "chunk"} (one or more) and a final
        {"type": "done", "full_response", "sources", "metrics"}. Only answer generation differs by mode:
        stream=True streams tokens through the sentence-level output validator; stream=False makes one
        model call and validates the whole answer.
        """
        start_time = time.perf_counter()
        metrics: Dict[str, Any] = {
            "tokens_in": 0,
            "tokens_out": 0,
            "retrieval_chunks": 0,
            "llm_called": False,
            "cost_usd": 0.0,
            "latency_ms": 0,
            "source": "none",
        }

        def finished_metrics() -> Dict[str, Any]:
            metrics["latency_ms"] = int((time.perf_counter() - start_time) * 1000)
            return metrics

        # 0. Deterministic Input Guardrail Firewall Check
        with trace_step("input_guardrail") as step:
            guardrail_res = input_guardrail.evaluate(query, chat_history=chat_history)
            step.update(allowed=guardrail_res.allowed,
                        violation=guardrail_res.violation.value if guardrail_res.violation else None)
        if not guardrail_res.allowed:
            metrics["source"] = "guardrail_refusal"
            refusal = guardrail_res.refusal_message or "Request blocked by safety guardrail."
            yield {
                "type": "guardrail_blocked",
                "violation": guardrail_res.violation.value if guardrail_res.violation else None,
                "reason": guardrail_res.reason,
            }
            yield {"type": "chunk", "content": refusal}
            yield {"type": "done", "full_response": refusal, "metrics": finished_metrics()}
            return

        # 0a. Follow-up (M2.4): a message that leans on the previous question ("And if my spouse comes with me?")
        # becomes a standalone question for everything below; the conversation still goes to the answer step
        if chat_history:
            with trace_step("follow_up") as step:
                resolution = await resolve_follow_up(query, chat_history)
                step.update(resolution.summary())
            query = resolution.question

        # 0b. Triage (M1.2): decide fast vs verified from the question; traced, answers unchanged until M2
        triage_decision = None
        if settings.AGENT_MODE != "off":
            with trace_step("triage", stage="question", mode=settings.AGENT_MODE) as step:
                triage_decision = triage(query)
                step.update(self._triage_summary(triage_decision))
                step["topics"] = list(detect_topics(query).topics)  # M2.1: real questions' topics, before M2.2

        # 1. Intent Normalization
        with trace_step("intent") as step:
            intent_data = await intent_parser.parse_intent(query)
            country = intent_data.get("country", context_metadata.get("country", "unknown") if context_metadata else "unknown")
            visa_type = intent_data.get("visa_type", "Student")
            intent = intent_data.get("intent", "general")
            step.update(intent=intent, country=country, visa_type=visa_type)

        # 1b. Decomposition (M2.3): a verified question that asks several things gets rules and sources per part
        parts: List[str] = []
        if routed_path() == VERIFIED:
            with trace_step("decomposition") as step:
                if needs_split(query):
                    split = await decompose(query)
                    step.update(split.summary())
                    if len(split.sub_questions) > 1:
                        parts = list(split.sub_questions)
                else:
                    step.update(method="single", parts=1)

        # 2. Extract Authoritative Rule Engine Facts
        with trace_step("rules") as step:
            if parts:
                # the rule engine answers with the first rule that matches, so a two-part question got only one
                # part's facts (funds + work hours -> work hours only): ask it once per part
                rule_facts = await self._rule_facts_per_part(parts, country, visa_type, intent)
                step["parts"] = len(parts)
            else:
                rule_facts = rule_engine.try_rule_answer(intent, country, visa_type, query=query)
            guarantee_fact = rule_engine.approval_guarantee_fact(query)
            if guarantee_fact:
                rule_facts = (rule_facts + "\n\n" + guarantee_fact) if rule_facts else guarantee_fact
            closed_program_fact = rule_engine.discontinued_program_fact(query)
            if closed_program_fact:
                rule_facts = (rule_facts + "\n\n" + closed_program_fact) if rule_facts else closed_program_fact
            step.update(rule_facts=bool(rule_facts), guarantee_fact=bool(guarantee_fact),
                        closed_program_fact=bool(closed_program_fact))
        # The path is part of the key: a fast-path answer must not stand in for a verified one, nor the reverse
        rules_version = f"{await self._answer_cache_version()}:{routed_path()}"

        # 3. Cache Check (query-specific; bypass for multi-turn sessions; versioned by rules content hash)
        with trace_step("cache") as step:
            cached = intent_cache.get_entry(country, visa_type, intent, version=rules_version, query=query)
            step.update(hit=bool(cached), used=bool(cached and not chat_history))
        if cached and not chat_history:
            metrics["source"] = "cache"
            yield {"type": "chunk", "content": cached["response"]}
            yield {"type": "done", "full_response": cached["response"], "sources": cached["sources"],
                   "metrics": finished_metrics()}
            return

        # 4. Structured Database & Tourist Context Check (A8 fallback session)
        tourist_context = ""
        with trace_step("tourist_db") as step:
            if db:
                tourist_context = await get_tourist_context(db, query, country)
            else:
                try:
                    from app.core.database import AsyncSessionLocal
                    async with AsyncSessionLocal() as session:
                        tourist_context = await get_tourist_context(session, query, country)
                except Exception as e:
                    logger.warning(f"[RAG_PIPELINE] Tourist context DB error: {e}")
                    step["db_error"] = type(e).__name__
            step["found"] = bool(tourist_context)

        # 5. Strict Vector Retrieval
        chunks = []
        with trace_step("retrieval", top_k=settings.RAG_TOP_K) as step:
            try:
                if parts:
                    part_chunks = [await retrieval_service.retrieve(query=part, country=country, visa_type=visa_type,
                                                                    intent=intent, top_k=settings.RAG_TOP_K)
                                   for part in parts]
                    chunks = self._merge_part_chunks(part_chunks, settings.RAG_MULTI_PART_CONTEXT_CHARS)
                    step["parts"] = [len(c) for c in part_chunks]
                else:
                    chunks = await retrieval_service.retrieve(
                        query=query,
                        country=country,
                        visa_type=visa_type,
                        intent=intent,
                        top_k=settings.RAG_TOP_K,
                    )
            except Exception as e:
                logger.warning(f"[RAG_PIPELINE] Retrieval error: {e}")
                step["retrieval_error"] = type(e).__name__
                chunks = []
            step["chunks"] = [
                {"url": (c.get("metadata") or {}).get("url") or c.get("url"),
                 "score": round(float(c.get("score") or 0.0), 4), "tier": c.get("authority_tier")}
                for c in chunks
            ]
        metrics["retrieval_chunks"] = len(chunks)

        # 6. Evidence gate (RAG-only policy: no verified evidence, no model call)
        with trace_step("evidence_gate") as step:
            has_evidence = bool(chunks) or bool(tourist_context) or bool(rule_facts)
            conf_eval = self.calculate_algorithmic_confidence(chunks, has_tourist_db=bool(tourist_context or rule_facts))
            step.update(has_evidence=has_evidence, confidence=conf_eval["score"], level=conf_eval["level"],
                        passed=has_evidence and conf_eval["level"] != "INSUFFICIENT")
        # Low retrieval confidence is the one triage signal known only now: trace it if it changes the path
        if triage_decision is not None and not triage_decision.verified:
            after_retrieval = triage(query, retrieval_level=conf_eval["level"])
            if after_retrieval.verified:
                triage_decision = after_retrieval
                with trace_step("triage", stage="retrieval", mode=settings.AGENT_MODE) as step:
                    step.update(self._triage_summary(triage_decision))

        metrics["confidence"] = conf_eval["score"]
        metrics["confidence_level"] = conf_eval["level"]

        if not has_evidence or conf_eval["level"] == "INSUFFICIENT":
            metrics["source"] = "no_evidence_refusal" if not has_evidence else "insufficient_confidence_refusal"
            metrics["llm_called"] = False
            yield {"type": "chunk", "content": UNVERIFIED_EVIDENCE_REFUSAL}
            yield {"type": "done", "full_response": UNVERIFIED_EVIDENCE_REFUSAL, "sources": [], "metrics": finished_metrics()}
            return

        # 7. Grounded Generation
        context_chars = settings.RAG_MULTI_PART_CONTEXT_CHARS if parts else settings.RAG_CONTEXT_CHARS
        combined_context, sources = self._build_grounded_context(rule_facts, chunks, tourist_context, context_chars)
        question_text = query
        if parts:  # name the parts so the answer covers each one
            question_text = (f"{query}\n\nThis question has {len(parts)} parts. Answer each one:\n"
                             + "\n".join(f"{n}. {part}" for n, part in enumerate(parts, 1)))
        system_prompt, user_prompt = get_prompt("grounded_answer").render(query=question_text)

        # 7a. Evidence answers (M3): on the verified path each part is answered with a quote checked in code; the
        # answer is composed from the checked parts. If every part's output was unreadable, write the answer as usual.
        evidence_answer = None
        # Sensitive (M4.4): legal risk in the question (triage) or a request for certainty about approval
        sensitive = routed_path() == VERIFIED and (
            bool(guarantee_fact) or (triage_decision is not None and "legal_risk" in triage_decision.reasons))
        if routed_path() == VERIFIED:
            results, retry_chunks = await self._evidence_answers(
                parts or [query], rule_facts, chunks, context_chars,
                retrieval_args={"country": country, "visa_type": visa_type, "intent": intent},
                deadline=start_time + settings.VERIFIED_RETRY_BEFORE_SECONDS)
            if retry_chunks:  # a kept retry cites new pages: list them too, numbers continuing after the first round
                sources = self.build_citations([c for c in chunks if c.get("_included_in_context")] + retry_chunks,
                                               tourist_context)
            metrics["evidence"] = {status: sum(r.status == status for r in results)
                                   for status in ("verified", "not_covered", "unverified", "invalid")}
            metrics["evidence"]["partial"] = sum(r.partial for r in results)
            metrics["evidence"]["improved_by_retry"] = sum(r.retried for r in results)
            # A question built on a premise ("The funds are $10,000, right?", a closed program) that got nothing
            # verified: the model said "not covered" because no source states the false claim, instead of
            # correcting it. That "not covered" isn't trusted; the answer is written as before, from the rule facts.
            premise_unanswered = (triage_decision is not None and "premise" in triage_decision.reasons
                                  and not any(r.status == "verified" for r in results))
            if sensitive:
                # M4.4: a sensitive answer (refusal, misrepresentation, guarantees...) holds only parts that passed
                # the code checks: never the written-as-before fallback (premise or unreadable output). A part the
                # model check doubted stays, labelled "partially verified": dropping it removed a correct "approvals
                # can never be guaranteed" answer (owner decision 2026-10-28; the model doubts 21-25% of correct
                # claims). The legal disclaimer is always added below.
                metrics["evidence"]["sensitive"] = True
                evidence_answer = compose(results)
            elif premise_unanswered:
                metrics["evidence"]["premise_fallback"] = True
            elif any(r.status != "invalid" for r in results):
                evidence_answer = compose(results)

        generation_args = dict(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            context=combined_context,
            chat_history=chat_history,
            temperature=settings.RAG_TEMPERATURE,  # 0 = deterministic; same question, same answer
            max_tokens=settings.RAG_MAX_ANSWER_TOKENS,
            role="answer",
        )
        metrics["llm_called"] = True

        if not stream or evidence_answer is not None:  # an evidence answer is complete: sent whole in both modes
            if evidence_answer is not None:
                answer = evidence_answer
            else:
                with trace_step("generation", mode="whole") as step:
                    answer = await llm_service.generate_answer(**generation_args)
                    answer = normalize_markdown_output(answer)
                    step["chars"] = len(answer)

            # Output Guardrail & Leakage Shield Validation
            with trace_step("output_guardrail") as step:
                val_res = output_guardrail.validate_output(answer)
                step.update(valid=val_res.is_valid, violations=[v.value for v in val_res.violations])
            if not val_res.is_valid:
                answer = val_res.sanitized_output
                metrics["output_guardrail_remediated"] = True
                metrics["output_violations"] = [v.value for v in val_res.violations]
            else:
                metrics["output_guardrail_remediated"] = False

            # Legal & High-Risk Disclaimer Evaluation (Milestone 3 - Task 3.3)
            with trace_step("disclaimer") as step:
                disclaimer_eval = legal_disclaimer_engine.evaluate(query, answer)
                step.update(high_risk=disclaimer_eval.is_high_risk, categories=list(disclaimer_eval.risk_categories or []))
            if disclaimer_eval.is_high_risk:
                answer = disclaimer_eval.annotated_text
                metrics["high_risk_topic_detected"] = True
                metrics["risk_categories"] = disclaimer_eval.risk_categories
            else:
                metrics["high_risk_topic_detected"] = False
                metrics["risk_categories"] = []
            if sensitive and not disclaimer_eval.is_high_risk:
                answer += LEGAL_DISCLAIMER  # M4.4: always, even if the answer's wording didn't trigger the detector

            self._record_usage(metrics, user_prompt, combined_context, answer)

            # Cache grounded result only if validation passed without leakage
            if val_res.is_valid:
                intent_cache.set(country, visa_type, intent, answer, version=rules_version, query=query,
                                 sources=sources)

            yield {"type": "chunk", "content": answer}
            yield {"type": "done", "full_response": answer, "sources": sources, "metrics": finished_metrics()}
            return

        full_response = ""
        stream_blocked = False
        stream_violations = []
        try:
            raw_token_stream = llm_service.generate_answer_stream(**generation_args)

            with trace_step("generation", mode="stream") as step:
                async for event in output_guardrail.validate_stream(raw_token_stream):
                    event_type = event.get("type")
                    if event_type == "guardrail_blocked":
                        stream_blocked = True
                        stream_violations = event.get("violations", [])
                        yield event
                    elif event_type == "chunk":
                        content = event.get("content", "")
                        if event.get("replaced"):
                            full_response = content.strip()
                        else:
                            full_response += content
                        yield event
                step.update(chars=len(full_response), output_blocked=stream_blocked, violations=stream_violations)

            self._record_usage(metrics, user_prompt, combined_context, full_response)

            if stream_blocked:
                metrics["output_guardrail_remediated"] = True
                metrics["output_violations"] = stream_violations
            else:
                metrics["output_guardrail_remediated"] = False

                # Legal & High-Risk Disclaimer Evaluation (Milestone 3 - Task 3.3)
                with trace_step("disclaimer") as step:
                    disclaimer_eval = legal_disclaimer_engine.evaluate(query, full_response)
                    step.update(high_risk=disclaimer_eval.is_high_risk, categories=list(disclaimer_eval.risk_categories or []))
                if disclaimer_eval.is_high_risk and disclaimer_eval.disclaimer_text:
                    full_response = disclaimer_eval.annotated_text
                    metrics["high_risk_topic_detected"] = True
                    metrics["risk_categories"] = disclaimer_eval.risk_categories
                    yield {"type": "chunk", "content": disclaimer_eval.disclaimer_text}
                else:
                    metrics["high_risk_topic_detected"] = False
                    metrics["risk_categories"] = []

                normalized_full = normalize_markdown_output(full_response)
                intent_cache.set(country, visa_type, intent, normalized_full, version=rules_version, query=query,
                                 sources=sources)
        except Exception as e:
            logger.error(f"[RAG_PIPELINE] LLM stream error: {e}", exc_info=True)
            err_msg = "An error occurred while generating the answer from official sources."
            full_response += err_msg
            yield {"type": "chunk", "content": err_msg}

        yield {
            "type": "done",
            "full_response": normalize_markdown_output(full_response),
            "sources": sources,
            "metrics": finished_metrics(),
        }

    @staticmethod
    async def _evidence_answers(parts: List[str], rule_facts: Optional[str], chunks: List[Dict[str, Any]],
                                context_chars: int, retrieval_args: Dict[str, Any], deadline: float,
                                ) -> tuple[List["PartResult"], List[Dict[str, Any]]]:
        """
        M3: each part through the evidence step and the code check, traced as `evidence` (no user text).
        M4.3: a part that isn't verified gets one more round (refined search past the chunks already shown) while
        time remains; traced as `retry`. Returns the results and the extra chunks the kept retries cite.
        """
        chunk_context = retrieval_service.prepare_context(chunks, max_context_length=context_chars) if chunks else ""
        context = evidence_context(rule_facts, chunk_context)
        sources = source_texts(rule_facts, chunks)
        results = []
        for part in parts:
            with trace_step("evidence") as step:
                result = await answer_part(part, context, sources, rule_facts)
                step.update(result.summary())
            results.append(result)

        extra: List[Dict[str, Any]] = []
        if settings.VERIFIED_MAX_ROUNDS < 2:
            return results, extra
        for i, first in enumerate(results):
            if first.status == "verified":
                continue
            with trace_step("retry") as step:
                if time.perf_counter() > deadline:
                    step.update(skipped="time_budget")
                    break
                shown = {_chunk_key(c) for c in chunks + extra}
                found = await retrieval_service.retrieve(query=refine_query(first.part), top_k=settings.RAG_TOP_K * 2,
                                                         **retrieval_args)
                fresh = [c for c in found if _chunk_key(c) not in shown][:settings.RAG_TOP_K]
                step.update(first=first.status, new_chunks=len(fresh))
                if not fresh:
                    continue
                next_number = max([n for n in sources if n] + [0]) + 1
                fresh_context = retrieval_service.prepare_context(fresh, max_context_length=settings.RAG_CONTEXT_CHARS,
                                                                  first_number=next_number)
                retry_sources = {**sources, **source_texts(None, fresh)}
                retry = await answer_part(first.part, evidence_context(rule_facts, fresh_context), retry_sources,
                                          rule_facts)
                kept = better(first, retry)
                step.update(retry=retry.status, kept="retry" if kept is retry else "first")
            if kept is retry:
                results[i] = replace(retry, retried=True)
                sources = retry_sources
                extra.extend(c for c in fresh if c.get("_included_in_context"))
        return results, extra

    @staticmethod
    async def _rule_facts_per_part(parts: List[str], country: str, visa_type: str, intent: str) -> Optional[str]:
        """Rule facts for each part (with the part's own intent), each distinct block once."""
        blocks: List[str] = []
        for part in parts:
            part_intent = await intent_parser.parse_intent(part)
            block = rule_engine.try_rule_answer(part_intent.get("intent", intent), country,
                                                part_intent.get("visa_type", visa_type), query=part)
            if block and block not in blocks:
                blocks.append(block)
        return "\n\n".join(blocks) or None

    @staticmethod
    def _merge_part_chunks(part_chunks: List[List[Dict[str, Any]]], budget: int) -> List[Dict[str, Any]]:
        """
        One context from each part's retrieval: parts in order, each up to an equal share of `budget` characters
        of source text (always its best chunk), a chunk already taken by an earlier part not repeated. Without
        shares, the first part's chunks would fill the context and later parts get no sources.
        """
        share = budget // max(1, len(part_chunks))
        merged: List[Dict[str, Any]] = []
        seen = set()
        for chunks in part_chunks:
            used = 0
            for chunk in chunks:
                key = ((chunk.get("metadata") or {}).get("url") or chunk.get("url"), chunk.get("text"))
                if key in seen:
                    continue
                size = len(chunk.get("text") or "") + _CHUNK_FRAMING_CHARS
                if used and used + size > share:
                    break
                seen.add(key)
                merged.append(chunk)
                used += size
        return merged

    def _build_grounded_context(
        self,
        rule_facts: str,
        chunks: List[Dict[str, Any]],
        tourist_context: str,
        max_chars: Optional[int] = None,
    ) -> tuple[str, List[Dict[str, Any]]]:
        """Assemble the model context (rule facts, retrieved chunks, tourist records) and the citations for it."""
        context_blocks = []
        if rule_facts:
            context_blocks.append(f"### IMMUTABLE OFFICIAL STATUTORY FACTS (Binding Regulatory Calculations):\n{rule_facts}")

        if chunks:
            chunk_context = retrieval_service.prepare_context(chunks, max_context_length=max_chars or settings.RAG_CONTEXT_CHARS)
            if chunk_context:
                context_blocks.append(chunk_context)

        if tourist_context:
            context_blocks.append(f"Official Tourist Database Records:\n{tourist_context}")

        # Only cite sources that were actually included in the LLM context (A11)
        cited_chunks = [c for c in chunks if c.get("_included_in_context")] if chunks else []
        sources = self.build_citations(cited_chunks, tourist_context)
        if rule_facts and not sources:
            sources = [{
                "url": "https://www.canada.ca/en/immigration-refugees-citizenship.html",
                "title": "Official IRCC Regulatory Framework",
                "snippet": rule_facts[:200],
                "scraped_at": "",
            }]

        return "\n\n".join(context_blocks), sources

    @staticmethod
    def _record_usage(metrics: Dict[str, Any], user_prompt: str, context: str, answer: str) -> None:
        """Rough token/cost estimate (characters / 4); real Ollama counts arrive with the request trace (M0.5)."""
        metrics["tokens_in"] = (len(get_prompt("grounded_answer").system) + len(user_prompt) + len(context)) // 4
        metrics["tokens_out"] = len(answer) // 4
        metrics["cost_usd"] = (metrics["tokens_in"] + metrics["tokens_out"]) * 0.0000001
        metrics["source"] = "llm_rag"

    @staticmethod
    def build_citations(
        chunks: List[Dict[str, Any]],
        tourist_context: str = "",
    ) -> List[Dict[str, Any]]:
        """
        Build structured source citations matching SourceCitation schema:
        url, snippet, scraped_at, title, number, numbers.

        One citation per page. `numbers` are all the [Source N] labels its chunks had in the model context (each
        chunk is its own source there), `number` the first; the list is in order of `number`. So every [Source N]
        in an answer is the page whose `numbers` contain N, e.g. a page shown as "1, 3".
        """
        citations: List[Dict[str, Any]] = []
        by_url: Dict[str, Dict[str, Any]] = {}

        for position, chunk in enumerate(chunks, 1):
            metadata = chunk.get("metadata", {})
            url = metadata.get("url") or chunk.get("url") or "https://www.canada.ca"
            number = chunk.get("_source_number") or position
            if url in by_url:
                by_url[url]["numbers"].append(number)
                continue

            raw_text = chunk.get("text", "")
            snippet = raw_text[:200].strip() if raw_text else ""
            scraped_at = str(metadata.get("scraped_at") or chunk.get("scraped_at") or "")
            title = metadata.get("title") or chunk.get("title") or "Official IRCC Document"

            by_url[url] = {
                "url": url,
                "snippet": snippet,
                "scraped_at": scraped_at,
                "title": title,
                "number": number,
                "numbers": [number],
            }
            citations.append(by_url[url])
        for citation in citations:
            citation["numbers"].sort()
            citation["number"] = citation["numbers"][0]
        citations.sort(key=lambda c: c["number"])

        if tourist_context and not citations:
            citations.append({
                "url": "https://www.canada.ca/en/immigration-refugees-citizenship/services/visit-canada.html",
                "snippet": tourist_context[:200].strip(),
                "scraped_at": "",
                "title": "Official Canada Tourist Registry",
            })

        return citations

    @staticmethod
    def _triage_summary(decision) -> Dict[str, Any]:
        """Trace fields for a triage decision. `path` is what triage decided; `routed` is the path this request
        actually runs on (verified only for verified answer jobs, AGENT_MODE=on). Until M2 the verified path
        is today's pipeline, so answers are the same either way."""
        return {"path": decision.path, "reasons": list(decision.reasons), "routed": routed_path()}

    @staticmethod
    def calculate_algorithmic_confidence(
        chunks: List[Dict[str, Any]],
        has_tourist_db: bool = False,
    ) -> Dict[str, Any]:
        """
        Calculate algorithmic confidence score:
        confidence = similarity_score * 0.4 + authority_weight * 0.4 + freshness_weight * 0.2
        Classify as HIGH (>= 0.75), MEDIUM (>= 0.50), LOW (>= 0.35), or INSUFFICIENT (< 0.35).
        """
        if not chunks and not has_tourist_db:
            return {
                "score": 0.0,
                "level": "INSUFFICIENT",
                "similarity": 0.0,
                "authority": 0.0,
                "freshness": 0.0,
            }

        # 1. Similarity score
        if chunks:
            similarity = max(float(c.get("score") or 0.0) for c in chunks)  # missing score = no evidence (A13)
        else:
            similarity = 0.85 if has_tourist_db else 0.0

        # 2. Authority weight
        if chunks:
            auth_weights = []
            for c in chunks:
                if "authority_weight" in c and c["authority_weight"] is not None:
                    auth_weights.append(float(c["authority_weight"]))
                elif "authority_tier" in c and c["authority_tier"] is not None:
                    tier = int(c["authority_tier"])
                    auth_weights.append(retrieval_service.TIER_WEIGHTS.get(tier, 0.4))
                else:
                    tier = retrieval_service.infer_authority_tier(c)
                    auth_weights.append(retrieval_service.TIER_WEIGHTS.get(tier, 0.4))
            authority = sum(auth_weights) / len(auth_weights)
            if has_tourist_db:
                authority = max(authority, 0.95)
        else:
            authority = 0.95  # Official PostgreSQL DB / Tier-1 IRCC rules

        # 3. Freshness weight
        if chunks:
            freshness_weights = [float(c.get("freshness_weight") or 0.5) for c in chunks]  # unknown age = neutral-low (A13)
            freshness = sum(freshness_weights) / len(freshness_weights)
        else:
            freshness = 1.0  # Current live database

        # Formula: similarity * 0.4 + authority * 0.4 + freshness * 0.2
        score = round(similarity * 0.4 + authority * 0.4 + freshness * 0.2, 4)

        if score >= 0.75:
            level = "HIGH"
        elif score >= 0.50:
            level = "MEDIUM"
        elif score >= 0.35:
            level = "LOW"
        else:
            level = "INSUFFICIENT"

        return {
            "score": score,
            "level": level,
            "similarity": round(similarity, 4),
            "authority": round(authority, 4),
            "freshness": round(freshness, 4),
        }


# Global instance
rag_pipeline = RAGPipeline()
