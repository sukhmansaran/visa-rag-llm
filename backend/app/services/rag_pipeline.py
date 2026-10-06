"""
Unified RAG Pipeline orchestrator.
Executes the authoritative flow: Guardrail -> Intent -> Cache -> Rule Engine -> Tourist DB -> Strict Retrieval -> Grounded Generation.
Enforces the RAG-Only policy: Zero ungrounded hallucinations, zero raw LLM fallbacks.
"""

import time
import json
from typing import Dict, Any, Optional, List, AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.intent_parser import intent_parser
from app.services.rule_engine import rule_engine
from app.services.cache_service import intent_cache
from app.services.retrieval import retrieval_service
from app.services.llm import llm_service
from app.services.guardrails.input_guardrail import input_guardrail
from app.services.tourist_service import get_tourist_context


GROUNDED_SYSTEM_PROMPT = """You are Pendu, an official visa and immigration information assistant.
You must answer the user's question using ONLY the provided verified context below.
Do NOT infer, speculate, or introduce outside knowledge.

Instructions:
- Provide concise, factual information in bullet points.
- If the provided context does not contain enough information to fully answer the query, clearly state: 'Additional details are not found in the verified official sources.'
- Cite sources where available.
- Maintain strict fidelity to official IRCC / government guidelines."""

UNVERIFIED_EVIDENCE_REFUSAL = (
    "I cannot find verified official sources in my knowledge base to answer this specific question. "
    "To prevent misinformation, I do not speculate or extrapolate on immigration policies. "
    "Please consult official government portals (such as Immigration, Refugees and Citizenship Canada at https://www.canada.ca) "
    "or consult a licensed Regulated Canadian Immigration Consultant (RCIC)."
)


class RAGPipeline:
    """Orchestrates the authoritative unified RAG flow for both synchronous and streaming chat."""

    async def process_query(
        self,
        query: str,
        context_metadata: Optional[Dict[str, Any]] = None,
        chat_history: Optional[List[Dict[str, Any]]] = None,
        db: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """Synchronous query processor with RAG-only enforcement."""
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

        # 0. Deterministic Input Guardrail Firewall Check
        guardrail_res = input_guardrail.evaluate(query, chat_history=chat_history)
        if not guardrail_res.allowed:
            metrics["latency_ms"] = int((time.perf_counter() - start_time) * 1000)
            metrics["source"] = "guardrail_refusal"
            return {
                "answer": guardrail_res.refusal_message or "Request blocked by safety guardrail.",
                "metrics": metrics,
                "violation": guardrail_res.violation.value if guardrail_res.violation else None,
                "guardrail_blocked": True,
            }

        # 1. Intent Normalization
        intent_data = await intent_parser.parse_intent(query)
        country = intent_data.get("country", context_metadata.get("country", "unknown") if context_metadata else "unknown")
        visa_type = intent_data.get("visa_type", "Student")
        intent = intent_data.get("intent", "general")

        # 2. Aggressive Cache Check
        cached_response = intent_cache.get(country, visa_type, intent)
        if cached_response:
            metrics["latency_ms"] = int((time.perf_counter() - start_time) * 1000)
            metrics["source"] = "cache"
            return {"answer": cached_response, "metrics": metrics, "guardrail_blocked": False}

        # 3. Rule Engine Check
        rule_response = rule_engine.try_rule_answer(intent, country, visa_type)
        if rule_response:
            metrics["latency_ms"] = int((time.perf_counter() - start_time) * 1000)
            metrics["source"] = "rule_engine"
            intent_cache.set(country, visa_type, intent, rule_response)
            return {"answer": rule_response, "metrics": metrics, "guardrail_blocked": False}

        # 4. Structured Database & Tourist Context Check
        tourist_context = ""
        if db:
            tourist_context = await get_tourist_context(db, query, country)

        # 5. Strict Vector Retrieval
        chunks = []
        try:
            chunks = await retrieval_service.retrieve(
                query=query,
                country=country,
                visa_type=visa_type,
                intent=intent,
                top_k=3,
            )
        except Exception as e:
            print(f"[RAG_PIPELINE] Retrieval error: {e}")
            chunks = []
        metrics["retrieval_chunks"] = len(chunks)

        # 6. Grounded Generation (RAG-Only — Zero ungrounded fallback)
        has_evidence = bool(chunks) or bool(tourist_context)

        if has_evidence:
            context_blocks = []
            if chunks:
                context_blocks.append(retrieval_service.prepare_context(chunks, max_context_length=1500))
            if tourist_context:
                context_blocks.append(f"Official Tourist Database Records:\n{tourist_context}")

            combined_context = "\n\n".join(context_blocks)
            user_prompt = f"Question: {query}"

            metrics["llm_called"] = True
            answer = await llm_service.generate_answer(
                system_prompt=GROUNDED_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                context=combined_context,
                temperature=0.0,  # Deterministic grounding
                max_tokens=600,
            )

            metrics["tokens_in"] = (len(GROUNDED_SYSTEM_PROMPT) + len(user_prompt) + len(combined_context)) // 4
            metrics["tokens_out"] = len(answer) // 4
            metrics["cost_usd"] = (metrics["tokens_in"] + metrics["tokens_out"]) * 0.0000001
            metrics["source"] = "llm_rag"

            # Cache grounded result
            intent_cache.set(country, visa_type, intent, answer)
        else:
            # RAG-ONLY POLICY: Reject answer when no verified sources exist
            answer = UNVERIFIED_EVIDENCE_REFUSAL
            metrics["source"] = "no_evidence_refusal"
            metrics["llm_called"] = False

        metrics["latency_ms"] = int((time.perf_counter() - start_time) * 1000)
        return {"answer": answer, "metrics": metrics, "guardrail_blocked": False}

    async def process_query_stream(
        self,
        query: str,
        context_metadata: Optional[Dict[str, Any]] = None,
        chat_history: Optional[List[Dict[str, Any]]] = None,
        db: Optional[AsyncSession] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Streaming query processor yielding SSE chunks with early guardrail interception."""
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

        # 0. Deterministic Input Guardrail Firewall Check
        guardrail_res = input_guardrail.evaluate(query, chat_history=chat_history)
        if not guardrail_res.allowed:
            metrics["latency_ms"] = int((time.perf_counter() - start_time) * 1000)
            metrics["source"] = "guardrail_refusal"
            refusal = guardrail_res.refusal_message or "Request blocked by safety guardrail."
            yield {
                "type": "guardrail_blocked",
                "violation": guardrail_res.violation.value if guardrail_res.violation else None,
                "reason": guardrail_res.reason,
            }
            yield {"type": "chunk", "content": refusal}
            yield {"type": "done", "full_response": refusal, "metrics": metrics}
            return

        # 1. Intent Normalization
        intent_data = await intent_parser.parse_intent(query)
        country = intent_data.get("country", context_metadata.get("country", "unknown") if context_metadata else "unknown")
        visa_type = intent_data.get("visa_type", "Student")
        intent = intent_data.get("intent", "general")

        # 2. Aggressive Cache Check
        cached_response = intent_cache.get(country, visa_type, intent)
        if cached_response:
            metrics["latency_ms"] = int((time.perf_counter() - start_time) * 1000)
            metrics["source"] = "cache"
            yield {"type": "chunk", "content": cached_response}
            yield {"type": "done", "full_response": cached_response, "metrics": metrics}
            return

        # 3. Rule Engine Check
        rule_response = rule_engine.try_rule_answer(intent, country, visa_type)
        if rule_response:
            metrics["latency_ms"] = int((time.perf_counter() - start_time) * 1000)
            metrics["source"] = "rule_engine"
            intent_cache.set(country, visa_type, intent, rule_response)
            yield {"type": "chunk", "content": rule_response}
            yield {"type": "done", "full_response": rule_response, "metrics": metrics}
            return

        # 4. Structured Database & Tourist Context Check
        tourist_context = ""
        if db:
            tourist_context = await get_tourist_context(db, query, country)

        # 5. Strict Vector Retrieval
        chunks = []
        try:
            chunks = await retrieval_service.retrieve(
                query=query,
                country=country,
                visa_type=visa_type,
                intent=intent,
                top_k=3,
            )
        except Exception as e:
            print(f"[RAG_PIPELINE] Retrieval error: {e}")
            chunks = []
        metrics["retrieval_chunks"] = len(chunks)

        # 6. Grounded Generation (RAG-Only)
        has_evidence = bool(chunks) or bool(tourist_context)

        if has_evidence:
            context_blocks = []
            if chunks:
                context_blocks.append(retrieval_service.prepare_context(chunks, max_context_length=1500))
            if tourist_context:
                context_blocks.append(f"Official Tourist Database Records:\n{tourist_context}")

            combined_context = "\n\n".join(context_blocks)
            user_prompt = f"Question: {query}"

            metrics["llm_called"] = True
            full_response = ""

            try:
                async for chunk in llm_service.generate_answer_stream(
                    system_prompt=GROUNDED_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    context=combined_context,
                    temperature=0.0,
                    max_tokens=600,
                ):
                    full_response += chunk
                    yield {"type": "chunk", "content": chunk}

                metrics["tokens_in"] = (len(GROUNDED_SYSTEM_PROMPT) + len(user_prompt) + len(combined_context)) // 4
                metrics["tokens_out"] = len(full_response) // 4
                metrics["cost_usd"] = (metrics["tokens_in"] + metrics["tokens_out"]) * 0.0000001
                metrics["source"] = "llm_rag"

                intent_cache.set(country, visa_type, intent, full_response)
            except Exception as e:
                print(f"[RAG_PIPELINE] LLM stream error: {e}")
                err_msg = "An error occurred while generating the answer from official sources."
                full_response += err_msg
                yield {"type": "chunk", "content": err_msg}

            metrics["latency_ms"] = int((time.perf_counter() - start_time) * 1000)
            yield {"type": "done", "full_response": full_response, "metrics": metrics}
        else:
            # RAG-ONLY POLICY: No verified chunks found
            metrics["source"] = "no_evidence_refusal"
            metrics["llm_called"] = False
            metrics["latency_ms"] = int((time.perf_counter() - start_time) * 1000)
            yield {"type": "chunk", "content": UNVERIFIED_EVIDENCE_REFUSAL}
            yield {"type": "done", "full_response": UNVERIFIED_EVIDENCE_REFUSAL, "metrics": metrics}


# Global instance
rag_pipeline = RAGPipeline()
