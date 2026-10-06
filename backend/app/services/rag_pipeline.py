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
- Associate each factual statement with inline citations like [Source 1], [Source 2] corresponding to the provided sources.
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
                "sources": [],
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
            return {"answer": cached_response, "sources": [], "metrics": metrics, "guardrail_blocked": False}

        # 3. Rule Engine Check
        rule_response = rule_engine.try_rule_answer(intent, country, visa_type)
        if rule_response:
            metrics["latency_ms"] = int((time.perf_counter() - start_time) * 1000)
            metrics["source"] = "rule_engine"
            intent_cache.set(country, visa_type, intent, rule_response)
            return {"answer": rule_response, "sources": [], "metrics": metrics, "guardrail_blocked": False}

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
        conf_eval = self.calculate_algorithmic_confidence(chunks, has_tourist_db=bool(tourist_context))
        metrics["confidence"] = conf_eval["score"]
        metrics["confidence_level"] = conf_eval["level"]

        sources: List[Dict[str, Any]] = []

        if has_evidence and conf_eval["level"] != "INSUFFICIENT":
            sources = self.build_citations(chunks, tourist_context)
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
            # RAG-ONLY POLICY: Reject answer when no verified sources or confidence is INSUFFICIENT
            answer = UNVERIFIED_EVIDENCE_REFUSAL
            metrics["source"] = "no_evidence_refusal" if not has_evidence else "insufficient_confidence_refusal"
            metrics["llm_called"] = False

        metrics["latency_ms"] = int((time.perf_counter() - start_time) * 1000)
        return {"answer": answer, "sources": sources, "metrics": metrics, "guardrail_blocked": False}

    @staticmethod
    def build_citations(
        chunks: List[Dict[str, Any]],
        tourist_context: str = "",
    ) -> List[Dict[str, Any]]:
        """
        Build structured source citations matching SourceCitation schema:
        url, snippet, scraped_at, title.
        """
        citations: List[Dict[str, Any]] = []
        seen_urls = set()

        for chunk in chunks:
            metadata = chunk.get("metadata", {})
            url = metadata.get("url") or chunk.get("url") or "https://www.canada.ca"
            if url in seen_urls:
                continue
            seen_urls.add(url)

            raw_text = chunk.get("text", "")
            snippet = raw_text[:200].strip() if raw_text else ""
            scraped_at = str(metadata.get("scraped_at") or chunk.get("scraped_at") or "")
            title = metadata.get("title") or chunk.get("title") or "Official IRCC Document"

            citations.append({
                "url": url,
                "snippet": snippet,
                "scraped_at": scraped_at,
                "title": title,
            })

        if tourist_context and not citations:
            citations.append({
                "url": "https://www.canada.ca/en/immigration-refugees-citizenship/services/visit-canada.html",
                "snippet": tourist_context[:200].strip(),
                "scraped_at": "",
                "title": "Official Canada Tourist Registry",
            })

        return citations

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
            similarity = max(c.get("score", 0.70) for c in chunks)
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
            authority = 0.95  # Official PostgreSQL DB

        # 3. Freshness weight
        if chunks:
            freshness_weights = [c.get("freshness_weight", 0.7) for c in chunks]
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
        conf_eval = self.calculate_algorithmic_confidence(chunks, has_tourist_db=bool(tourist_context))
        metrics["confidence"] = conf_eval["score"]
        metrics["confidence_level"] = conf_eval["level"]

        if has_evidence and conf_eval["level"] != "INSUFFICIENT":
            sources = self.build_citations(chunks, tourist_context)
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
            yield {"type": "done", "full_response": full_response, "sources": sources, "metrics": metrics}
        else:
            # RAG-ONLY POLICY: No verified chunks found or insufficient confidence
            metrics["source"] = "no_evidence_refusal" if not has_evidence else "insufficient_confidence_refusal"
            metrics["llm_called"] = False
            metrics["latency_ms"] = int((time.perf_counter() - start_time) * 1000)
            yield {"type": "chunk", "content": UNVERIFIED_EVIDENCE_REFUSAL}
            yield {"type": "done", "full_response": UNVERIFIED_EVIDENCE_REFUSAL, "sources": [], "metrics": metrics}


# Global instance
rag_pipeline = RAGPipeline()
