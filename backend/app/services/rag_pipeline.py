"""
Unified RAG Pipeline orchestrator.
Executes the authoritative flow: Intent -> Rule/Cache -> Retrieval -> Generation -> Metrics.
"""

import time
import json
from typing import Dict, Any, Optional

from app.services.intent_parser import intent_parser
from app.services.rule_engine import rule_engine
from app.services.cache_service import intent_cache
from app.services.retrieval import retrieval_service
from app.services.llm import llm_service
from app.services.guardrails.input_guardrail import input_guardrail

class RAGPipeline:
    """Orchestrates the authoritative RAG flow."""
    
    async def process_query(self, query: str, context_metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        start_time = time.time()
        metrics = {
            "tokens_in": 0,
            "tokens_out": 0,
            "retrieval_chunks": 0,
            "llm_called": False,
            "cost_usd": 0.0,
            "latency_ms": 0,
            "source": "none"
        }
        
        # 0. Deterministic Input Guardrail Firewall Check
        guardrail_res = input_guardrail.evaluate(query)
        if not guardrail_res.allowed:
            metrics["latency_ms"] = int((time.time() - start_time) * 1000)
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
        visa_type = intent_data.get("visa_type", "Student") # Default to Student if unknown
        intent = intent_data.get("intent", "general")
        
        # 2. Aggressive Cache Check
        cached_response = intent_cache.get(country, visa_type, intent)
        if cached_response:
            metrics["latency_ms"] = int((time.time() - start_time) * 1000)
            metrics["source"] = "cache"
            return {"answer": cached_response, "metrics": metrics}
            
        # 3. Rule Engine Check
        rule_response = rule_engine.try_rule_answer(intent, country, visa_type)
        if rule_response:
            metrics["latency_ms"] = int((time.time() - start_time) * 1000)
            metrics["source"] = "rule_engine"
            # Optional: Populate cache with rule response for future consistency
            intent_cache.set(country, visa_type, intent, rule_response)
            return {"answer": rule_response, "metrics": metrics}
            
        # 4. Strict Retrieval
        try:
            chunks = await retrieval_service.retrieve(
                query=query,
                country=country,
                visa_type=visa_type,
                intent=intent,
                top_k=2 # STRICT limit
            )
        except Exception as e:
            print(f"[RAG_PIPELINE] Retrieval failed: {e}")
            chunks = []
        metrics["retrieval_chunks"] = len(chunks)
        
        # 5. Constrained Generation
        if chunks:
            context = retrieval_service.prepare_context(chunks, max_context_length=1000)
            
            system_prompt = (
                "You are a visa information assistant. Use ONLY the provided sources.\n"
                "Do NOT infer or add information.\n\n"
                "Instructions:\n"
                "- Answer in ≤120 words\n"
                "- Bullet points only\n"
                "- If information is missing, say: 'Not found in official sources'\n"
                "- Cite sources inline like [Source 1]"
            )
            
            user_prompt = f"Question: {query}"
            
            metrics["llm_called"] = True
            answer = await llm_service.generate_answer(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                context=context,
                temperature=0.0, # Deterministic
                max_tokens=250   # Constrain output
            )
            
            # Simple Token estimation (approx 4 chars per token)
            metrics["tokens_in"] = (len(system_prompt) + len(user_prompt) + len(context)) // 4
            metrics["tokens_out"] = len(answer) // 4
            metrics["cost_usd"] = (metrics["tokens_in"] + metrics["tokens_out"]) * 0.0000001
            metrics["source"] = "llm_rag"
            
            # 6. Store in Cache
            intent_cache.set(country, visa_type, intent, answer)
        else:
            # No RAG chunks found — use Gemini's own knowledge as fallback
            system_prompt = (
                "You are Pendu, an AI-powered visa and study abroad assistant.\n"
                "You help users with visa applications, university admissions, "
                "document checklists, SOP guidance, and travel planning.\n\n"
                "Instructions:\n"
                "- Be helpful, accurate, and concise\n"
                "- Use bullet points where appropriate\n"
                "- If unsure, recommend checking official embassy or university websites\n"
                "- Always be encouraging and supportive"
            )
            
            user_prompt = f"Question: {query}"
            
            metrics["llm_called"] = True
            try:
                answer = await llm_service.generate_answer(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=0.3,
                    max_tokens=1500
                )
                metrics["tokens_in"] = (len(system_prompt) + len(user_prompt)) // 4
                metrics["tokens_out"] = len(answer) // 4
                metrics["cost_usd"] = (metrics["tokens_in"] + metrics["tokens_out"]) * 0.0000001
                metrics["source"] = "llm_direct"
            except Exception as e:
                print(f"[RAG_PIPELINE] LLM fallback also failed: {e}")
                answer = "I'm sorry, I'm having trouble connecting to the AI service right now. Please try again in a moment."
                metrics["source"] = "fallback"
            
        metrics["latency_ms"] = int((time.time() - start_time) * 1000)
        
        # Log final metrics
        print(f"[RAG_PIPELINE] Query processed. Metrics: {json.dumps(metrics)}")
        
        return {"answer": answer, "metrics": metrics}

# Global instance
rag_pipeline = RAGPipeline()
