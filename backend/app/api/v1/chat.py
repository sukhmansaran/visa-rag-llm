from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
import uuid
import json

from app.core.database import get_db
from app.core.security import get_current_user, get_demo_user
from app.models.user import User
from app.models.chat_message import ChatMessage
from app.api.v1.chat_schemas import ChatMessage as ChatMessageSchema, ChatResponse, SourceCitation
from app.services.rag_pipeline import rag_pipeline
from app.services.guardrails.input_guardrail import input_guardrail

router = APIRouter(prefix="/chat", tags=["Chat"])

@router.post("/answer/stream")
async def get_answer_stream(
    message: ChatMessageSchema,
    current_user: User = Depends(get_demo_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get AI-powered answer with real-time streaming (like ChatGPT).
    
    Returns Server-Sent Events (SSE) for real-time updates.
    Frontend should use EventSource or fetch with streaming.
    """
    
    try:
        # Use provided session_id or create new one
        session_id = message.sessionId if message.sessionId else str(uuid.uuid4())
        
        # Get chat history from current session
        history_result = await db.execute(
            select(ChatMessage)
            .where(
                ChatMessage.user_id == current_user.id,
                ChatMessage.session_id == session_id
            )
            .order_by(ChatMessage.created_at)
            .limit(20)
        )
        history_messages = history_result.scalars().all()
        
        # Convert to list format
        chat_history = [
            {"role": msg.role, "content": msg.content}
            for msg in history_messages
        ]

        # 1. Deterministic Input Guardrail Check
        guardrail_result = input_guardrail.evaluate(message.query, chat_history=chat_history)
        if not guardrail_result.allowed:
            refusal_text = guardrail_result.refusal_message or "Request blocked by safety guardrail."
            
            # Save user message
            user_msg = ChatMessage(
                user_id=current_user.id,
                role="user",
                content=message.query,
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

            async def blocked_stream():
                yield f"data: {json.dumps({'type': 'session', 'session_id': session_id})}\n\n"
                yield f"data: {json.dumps({'type': 'guardrail_blocked', 'violation': guardrail_result.violation.value if guardrail_result.violation else None, 'reason': guardrail_result.reason})}\n\n"
                yield f"data: {json.dumps({'type': 'chunk', 'content': refusal_text})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'full_response': refusal_text})}\n\n"

            return StreamingResponse(
                blocked_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                }
            )
        
        # Save user message
        user_msg = ChatMessage(
            user_id=current_user.id,
            role="user",
            content=message.query,
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
        async def event_stream():
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
                
                # Send completion event with citations and metrics
                yield f"data: {json.dumps({'type': 'done', 'full_response': full_response, 'sources': sources, 'metrics': metrics})}\n\n"
                
            except Exception as e:
                print(f"Error in streaming: {e}")
                import traceback
                traceback.print_exc()
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        
        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            }
        )
        
    except Exception as e:
        print(f"Error setting up stream: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/answer", response_model=ChatResponse)
async def get_answer(
    message: ChatMessageSchema,
    current_user: User = Depends(get_demo_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get AI-powered answer using LangGraph agent with OpenRouter.
    
    Uses LangChain/LangGraph for:
    1. Conversation management
    2. LLM integration via OpenRouter (Nvidia Nemotron)
    3. Chat history context
    """
    
    try:
        # Use provided session_id or create new one
        session_id = message.sessionId if message.sessionId else str(uuid.uuid4())
        
        # Get chat history ONLY from current session for context
        history_result = await db.execute(
            select(ChatMessage)
            .where(
                ChatMessage.user_id == current_user.id,
                ChatMessage.session_id == session_id
            )
            .order_by(ChatMessage.created_at)  # Oldest first
            .limit(20)
        )
        history_messages = history_result.scalars().all()
        
        # Convert to list format for agent
        chat_history = [
            {"role": msg.role, "content": msg.content}
            for msg in history_messages
        ]

        # 1. Deterministic Input Guardrail Check
        guardrail_result = input_guardrail.evaluate(message.query, chat_history=chat_history)
        if not guardrail_result.allowed:
            refusal_text = guardrail_result.refusal_message or "Request blocked by safety guardrail."
            
            # Save user message
            user_msg = ChatMessage(
                user_id=current_user.id,
                role="user",
                content=message.query,
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
        
        # Save user message
        user_msg = ChatMessage(
            user_id=current_user.id,
            role="user",
            content=message.query,
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
        
        return ChatResponse(
            advice_text=answer,
            sources=[SourceCitation(**s) for s in sources] if sources else [],
            confidence=confidence,
            escalate=False,
            session_id=session_id,
            metadata=rag_metrics,
        )
        
    except Exception as e:
        print(f"Error generating answer: {e}")
        import traceback
        traceback.print_exc()
        import traceback
        tb = traceback.format_exc()
        return ChatResponse(
            advice_text=f"I'm sorry, I encountered an error processing your request. Please try again.",
            sources=[],
            confidence=0.0,
            escalate=True,
            session_id=None,
            metadata={"error": str(e), "traceback": tb},
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
