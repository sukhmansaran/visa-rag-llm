from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
import uuid
import json
from contextlib import aclosing

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.chat_message import ChatMessage
from app.api.v1.chat_schemas import ChatMessage as ChatMessageSchema, ChatResponse, SourceCitation
from app.services.rag_pipeline import rag_pipeline
from app.services.guardrails.input_guardrail import input_guardrail
from app.core.logging_config import PIIRedactor, get_logger, log_audit_event
from app.core.exceptions import AppException, app_exception_to_http_exception, AIServiceUnavailableError
from app.services.tracing import TraceRecorder, activate_trace, save_trace

logger = get_logger(__name__)
router = APIRouter(prefix="/chat", tags=["Chat"])


@router.post("/answer/stream")
async def get_answer_stream(
    message: ChatMessageSchema,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get AI-powered answer with real-time streaming (like ChatGPT).
    
    Returns Server-Sent Events (SSE) for real-time updates.
    Frontend should use EventSource or fetch with streaming.
    Every request is traced (M0.5); the trace id is in the final "done" event.
    """
    trace = TraceRecorder("chat.stream", user_id=current_user.id, session_id=message.sessionId, query=message.query)

    try:
        # Use provided session_id or create new one
        session_id = message.sessionId if message.sessionId else str(uuid.uuid4())
        trace.session_id = session_id
        
        # Get chat history from current session (latest 20 messages, chronological order)
        history_result = await db.execute(
            select(ChatMessage)
            .where(
                ChatMessage.user_id == current_user.id,
                ChatMessage.session_id == session_id
            )
            .order_by(desc(ChatMessage.created_at))
            .limit(20)
        )
        history_messages = list(reversed(history_result.scalars().all()))
        
        # Convert to list format from DB
        db_history = [
            {"role": msg.role, "content": msg.content}
            for msg in history_messages
        ]
        
        # Enforce server-side DB history for multi-turn security
        chat_history = db_history

        # 1. Deterministic Input Guardrail Check
        with trace.step("input_guardrail") as step:
            guardrail_result = input_guardrail.evaluate(message.query, chat_history=chat_history)
            step.update(allowed=guardrail_result.allowed,
                        violation=guardrail_result.violation.value if guardrail_result.violation else None)
        if not guardrail_result.allowed:
            refusal_text = guardrail_result.refusal_message or "Request blocked by safety guardrail."
            
            # Save user message
            user_msg = ChatMessage(
                user_id=current_user.id,
                role="user",
                content=PIIRedactor.redact(message.query),  # stored redacted (A7); the LLM still sees the original
                session_id=session_id,
                message_metadata={
                    "country": message.country,
                    "university": message.university,
                }
            )
            db.add(user_msg)
            
            # Save refusal message
            assistant_msg = ChatMessage(
                user_id=current_user.id,
                role="assistant",
                content=refusal_text,
                sources={},
                confidence=0.0,
                message_metadata={
                    "guardrail_blocked": True,
                    "violation": guardrail_result.violation.value if guardrail_result.violation else None,
                    "reason": guardrail_result.reason,
                },
                session_id=session_id,
            )
            db.add(assistant_msg)
            await db.commit()
            await db.close()

            log_audit_event(
                logger=logger,
                event_type="INPUT_GUARDRAIL_BLOCKED",
                user_id=current_user.id,
                request_id=session_id,
                guardrail_status=guardrail_result.violation.value if guardrail_result.violation else "BLOCKED",
                extra_details={"reason": guardrail_result.reason},
            )

            trace.finish(answer=refusal_text, source="input_guardrail")
            await save_trace(trace)

            async def blocked_stream():
                yield f"data: {json.dumps({'type': 'session', 'session_id': session_id})}\n\n"
                yield f"data: {json.dumps({'type': 'guardrail_blocked', 'violation': guardrail_result.violation.value if guardrail_result.violation else None, 'reason': guardrail_result.reason})}\n\n"
                yield f"data: {json.dumps({'type': 'chunk', 'content': refusal_text})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'full_response': refusal_text, 'trace_id': trace.trace_id})}\n\n"

            return StreamingResponse(
                blocked_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache, no-transform",  # no-transform: proxies/Next.js must not gzip-buffer the stream
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                }
            )
        
        # Save user message
        user_msg = ChatMessage(
            user_id=current_user.id,
            role="user",
            content=PIIRedactor.redact(message.query),  # stored redacted (A7); the LLM still sees the original
            session_id=session_id,
            message_metadata={
                "country": message.country,
                "university": message.university,
            }
        )
        db.add(user_msg)
        await db.commit()
        await db.close()  # Release DB connection before the long Ollama stream
        
        # Stream generator via authoritative RAG pipeline
        async def _event_stream_body():
            """Generate Server-Sent Events for streaming response via unified RAG pipeline."""
            full_response = ""
            sources = []
            metrics = {}
            
            try:
                # Send session_id first
                yield f"data: {json.dumps({'type': 'session', 'session_id': session_id})}\n\n"
                
                # Stream the response through authoritative RAG pipeline
                async for event in rag_pipeline.process_query_stream(
                    query=message.query,
                    context_metadata={"country": message.country, "university": message.university},
                    chat_history=chat_history,
                    db=None,
                ):
                    event_type = event.get("type", "chunk")
                    if event_type == "chunk":
                        content = event.get("content", "")
                        full_response += content
                        yield f"data: {json.dumps({'type': 'chunk', 'content': content})}\n\n"
                    elif event_type == "guardrail_blocked":
                        yield f"data: {json.dumps(event)}\n\n"
                    elif event_type == "done":
                        sources = event.get("sources", [])
                        metrics = event.get("metrics", {})

                trace.finish(answer=full_response, source=metrics.get("source"))
                metrics["trace_id"] = trace.trace_id

                # Open a fresh DB session to save the assistant message
                from app.core.database import AsyncSessionLocal
                async with AsyncSessionLocal() as save_db:
                    assistant_msg = ChatMessage(
                        user_id=current_user.id,
                        role="assistant",
                        content=full_response,
                        sources={"citations": sources} if sources else {},
                        confidence=float(metrics.get("confidence", 0.0)),
                        message_metadata=metrics,
                        session_id=session_id,
                    )
                    save_db.add(assistant_msg)
                    await save_db.commit()
                
                log_audit_event(
                    logger=logger,
                    event_type="CHAT_STREAM_COMPLETED",
                    user_id=current_user.id,
                    request_id=session_id,
                    intent=metrics.get("intent", "general"),
                    retrieval_chunks=metrics.get("retrieval_chunks", 0),
                    latency_ms=metrics.get("latency_ms", 0),
                    guardrail_status="REMEDIATED" if metrics.get("output_guardrail_remediated") else "ALLOWED",
                    risk_categories=metrics.get("risk_categories", []),
                )

                # Send completion event with citations and metrics
                yield f"data: {json.dumps({'type': 'done', 'full_response': full_response, 'sources': sources, 'metrics': metrics})}\n\n"
                
            except AppException as exc:
                trace.finish(error=f"{type(exc).__name__}: {exc.message}")
                http_exc = app_exception_to_http_exception(exc)
                logger.error(f"AppException in streaming: {exc.message}")
                yield f"data: {json.dumps({'type': 'error', 'status_code': http_exc.status_code, 'detail': http_exc.detail})}\n\n"
            except Exception as e:
                trace.finish(error=type(e).__name__)
                logger.error(f"Error in streaming: {e}", exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'message': 'An error occurred while generating the response.'})}\n\n"

        async def event_stream():
            """Run the stream inside the request's trace and always save the trace, even on disconnect."""
            with activate_trace(trace):
                try:
                    async with aclosing(_event_stream_body()) as body:
                        async for chunk in body:
                            yield chunk
                finally:
                    if not trace.finished:
                        trace.finish(error="stream_interrupted")
                    await save_trace(trace)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",  # no-transform: proxies/Next.js must not gzip-buffer the stream
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            }
        )
        
    except (AppException, HTTPException) as exc:
        trace.finish(error=type(exc).__name__)
        await save_trace(trace)
        raise
    except Exception as e:
        logger.error(f"Error setting up stream: {e}", exc_info=True)
        trace.finish(error=type(e).__name__)
        await save_trace(trace)
        raise HTTPException(status_code=500, detail="Failed to initialize streaming response.")


@router.post("/answer", response_model=ChatResponse)
async def get_answer(
    message: ChatMessageSchema,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Answer a question with the grounded RAG pipeline (non-streaming).

    Runs rag_pipeline.process_query on the local Ollama model, using the latest 20
    messages of this session as history, and stores both turns with PII redacted.
    Every request is traced (M0.5); the trace id is returned in metadata.trace_id.
    """
    trace = TraceRecorder("chat.answer", user_id=current_user.id, session_id=message.sessionId, query=message.query)
    with activate_trace(trace):
        try:
            return await _answer(message, current_user, db, trace)
        except BaseException as exc:
            if not trace.finished:
                trace.finish(error=type(exc).__name__)
            raise
        finally:
            await save_trace(trace)


async def _answer(message: ChatMessageSchema, current_user: User, db: AsyncSession, trace: TraceRecorder) -> ChatResponse:
    try:
        # Use provided session_id or create new one
        session_id = message.sessionId if message.sessionId else str(uuid.uuid4())
        trace.session_id = session_id
        
        # Get chat history ONLY from current session for context (latest 20 messages, chronological order)
        history_result = await db.execute(
            select(ChatMessage)
            .where(
                ChatMessage.user_id == current_user.id,
                ChatMessage.session_id == session_id
            )
            .order_by(desc(ChatMessage.created_at))
            .limit(20)
        )
        history_messages = list(reversed(history_result.scalars().all()))
        
        # Convert to list format for agent
        chat_history = [
            {"role": msg.role, "content": msg.content}
            for msg in history_messages
        ]

        # 1. Deterministic Input Guardrail Check
        with trace.step("input_guardrail") as step:
            guardrail_result = input_guardrail.evaluate(message.query, chat_history=chat_history)
            step.update(allowed=guardrail_result.allowed,
                        violation=guardrail_result.violation.value if guardrail_result.violation else None)
        if not guardrail_result.allowed:
            refusal_text = guardrail_result.refusal_message or "Request blocked by safety guardrail."
            
            # Save user message
            user_msg = ChatMessage(
                user_id=current_user.id,
                role="user",
                content=PIIRedactor.redact(message.query),  # stored redacted (A7); the LLM still sees the original
                session_id=session_id,
                message_metadata={
                    "country": message.country,
                    "university": message.university,
                }
            )
            db.add(user_msg)
            
            # Save refusal message
            assistant_msg = ChatMessage(
                user_id=current_user.id,
                role="assistant",
                content=refusal_text,
                sources={},
                confidence=0.0,
                message_metadata={
                    "guardrail_blocked": True,
                    "violation": guardrail_result.violation.value if guardrail_result.violation else None,
                    "reason": guardrail_result.reason,
                },
                session_id=session_id,
            )
            db.add(assistant_msg)
            await db.commit()
            
            log_audit_event(
                logger=logger,
                event_type="INPUT_GUARDRAIL_BLOCKED",
                user_id=current_user.id,
                request_id=session_id,
                guardrail_status=guardrail_result.violation.value if guardrail_result.violation else "BLOCKED",
                extra_details={"reason": guardrail_result.reason},
            )

            trace.finish(answer=refusal_text, source="input_guardrail")
            return ChatResponse(
                advice_text=refusal_text,
                sources=[],
                confidence=0.0,
                escalate=False,
                session_id=session_id,
                metadata={
                    "guardrail_blocked": True,
                    "violation": guardrail_result.violation.value if guardrail_result.violation else None,
                    "reason": guardrail_result.reason,
                    "latency_ms": 0,
                    "source": "input_guardrail",
                    "trace_id": trace.trace_id,
                },
            )
        
        # Process query through the authoritative RAG pipeline
        rag_result = await rag_pipeline.process_query(
            query=message.query,
            context_metadata={
                "country": message.country,
                "university": message.university
            },
            chat_history=chat_history,
            db=db,
        )
        answer = rag_result["answer"]
        rag_metrics = rag_result["metrics"]
        trace.finish(answer=answer, source=rag_metrics.get("source"))
        rag_metrics["trace_id"] = trace.trace_id
        
        # Save user message
        user_msg = ChatMessage(
            user_id=current_user.id,
            role="user",
            content=PIIRedactor.redact(message.query),  # stored redacted (A7); the LLM still sees the original
            session_id=session_id,
            message_metadata={
                "country": message.country,
                "university": message.university,
            }
        )
        db.add(user_msg)
        
        # Save assistant message
        sources = rag_result.get("sources", [])
        confidence = float(rag_metrics.get("confidence", 0.0))

        assistant_msg = ChatMessage(
            user_id=current_user.id,
            role="assistant",
            content=answer,
            sources={"citations": sources} if sources else {},
            confidence=confidence,
            message_metadata=rag_metrics,
            session_id=session_id,
        )
        db.add(assistant_msg)
        
        await db.commit()
        
        log_audit_event(
            logger=logger,
            event_type="CHAT_SYNC_COMPLETED",
            user_id=current_user.id,
            request_id=session_id,
            intent=rag_metrics.get("intent", "general"),
            retrieval_chunks=rag_metrics.get("retrieval_chunks", 0),
            latency_ms=rag_metrics.get("latency_ms", 0),
            guardrail_status="REMEDIATED" if rag_metrics.get("output_guardrail_remediated") else "ALLOWED",
            risk_categories=rag_metrics.get("risk_categories", []),
        )

        return ChatResponse(

            advice_text=answer,
            sources=[SourceCitation(**s) for s in sources] if sources else [],
            confidence=confidence,
            escalate=False,
            session_id=session_id,
            metadata=rag_metrics,
        )
        
    except AppException as exc:
        trace.finish(error=f"{type(exc).__name__}: {exc.message}")
        raise app_exception_to_http_exception(exc)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating answer: {e}", exc_info=True)
        trace.finish(error=type(e).__name__)
        return ChatResponse(
            advice_text="I'm sorry, I encountered an error processing your request. Please try again.",
            sources=[],
            confidence=0.0,
            escalate=True,
            session_id=session_id,
            metadata={"error_code": "INTERNAL_PROCESSING_ERROR", "trace_id": trace.trace_id},
        )


@router.get("/history")
async def get_chat_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
):
    """
    Get user's chat history.
    """
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.user_id == current_user.id)
        .order_by(desc(ChatMessage.created_at))
        .limit(limit)
        .offset(offset)
    )
    messages = result.scalars().all()
    
    # Count total efficiently
    total = await db.scalar(
        select(func.count()).select_from(ChatMessage).where(ChatMessage.user_id == current_user.id)
    )
    
    return {
        "messages": [
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "sources": msg.sources,
                "confidence": msg.confidence,
                "created_at": msg.created_at.isoformat(),
                "session_id": msg.session_id,
            }
            for msg in messages
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def _determine_query_type(query: str) -> str:
    """
    Determine query type from query text.
    
    Simple keyword-based classification.
    """
    query_lower = query.lower()
    
    if any(word in query_lower for word in ["visa", "immigration", "permit", "passport"]):
        return "visa"
    elif any(word in query_lower for word in ["university", "college", "admission", "gpa", "sat"]):
        return "university"
    elif any(word in query_lower for word in ["document", "checklist", "require", "need"]):
        return "checklist"
    elif any(word in query_lower for word in ["sop", "statement of purpose", "essay", "personal statement"]):
        return "sop"
    else:
        return "general"
