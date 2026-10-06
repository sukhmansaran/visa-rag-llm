"""Advanced conversation management service."""
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from sqlmodel import Session, select
import json

from app.models.chat_message import ChatMessage
from app.core.logging_config import get_logger

logger = get_logger(__name__)

MAX_CONTEXT_MESSAGES = 10
MAX_CONTEXT_TOKENS = 4000


class ConversationService:
    """Manages conversation context and multi-turn interactions."""

    def __init__(self, db: Session):
        self.db = db

    async def get_conversation_context(
        self,
        session_id: str,
        user_id: str,
        max_messages: int = MAX_CONTEXT_MESSAGES
    ) -> List[Dict[str, str]]:
        """Get recent conversation history for context."""
        statement = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .where(ChatMessage.user_id == user_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(max_messages)
        )
        messages = self.db.exec(statement).all()
        
        # Reverse to get chronological order
        messages = list(reversed(messages))
        
        context = []
        for msg in messages:
            context.append({
                "role": msg.role,
                "content": msg.content
            })
        
        return context

    def detect_follow_up(self, question: str, context: List[Dict[str, str]]) -> bool:
        """Detect if the question is a follow-up to previous conversation."""
        if not context:
            return False
        
        follow_up_indicators = [
            "what about", "how about", "and", "also", "more",
            "tell me more", "explain", "why", "can you",
            "what if", "is it", "does it", "that", "this",
            "the same", "similar", "another", "other"
        ]
        
        question_lower = question.lower().strip()
        
        # Check for pronouns that reference previous context
        pronouns = ["it", "they", "them", "this", "that", "these", "those"]
        words = question_lower.split()
        if any(word in pronouns for word in words[:5]):
            return True
        
        # Check for follow-up indicators
        for indicator in follow_up_indicators:
            if question_lower.startswith(indicator):
                return True
        
        # Short questions are often follow-ups
        if len(words) <= 5:
            return True
        
        return False

    def build_context_prompt(
        self,
        question: str,
        context: List[Dict[str, str]],
        is_follow_up: bool
    ) -> str:
        """Build a prompt that includes conversation context."""
        if not context or not is_follow_up:
            return question
        
        context_str = "\n".join([
            f"{msg['role'].upper()}: {msg['content']}"
            for msg in context[-5:]  # Last 5 messages
        ])
        
        return f"""Previous conversation:
{context_str}

Current question: {question}

Please answer the current question, taking into account the previous conversation context if relevant."""

    async def summarize_conversation(
        self,
        session_id: str,
        user_id: str
    ) -> Optional[str]:
        """Generate a summary of the conversation."""
        context = await self.get_conversation_context(session_id, user_id, max_messages=20)
        
        if len(context) < 3:
            return None
        
        # Simple extractive summary - get key topics
        topics = set()
        for msg in context:
            if msg['role'] == 'user':
                # Extract key phrases (simplified)
                words = msg['content'].lower().split()
                # Filter common words
                stop_words = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'what', 'how', 'can', 'i', 'you'}
                key_words = [w for w in words if len(w) > 3 and w not in stop_words]
                topics.update(key_words[:3])
        
        if topics:
            return f"Conversation topics: {', '.join(list(topics)[:10])}"
        return None


class FeedbackService:
    """Manages user feedback on chat responses."""

    def __init__(self, db: Session):
        self.db = db

    async def record_feedback(
        self,
        message_id: str,
        user_id: str,
        feedback_type: str,  # 'helpful', 'not_helpful', 'report'
        comment: Optional[str] = None
    ) -> bool:
        """Record user feedback on a message."""
        try:
            # Get the message
            statement = select(ChatMessage).where(ChatMessage.id == message_id)
            message = self.db.exec(statement).first()
            
            if not message:
                return False
            
            # Update feedback in metadata
            metadata = json.loads(message.metadata) if message.metadata else {}
            metadata['feedback'] = {
                'type': feedback_type,
                'comment': comment,
                'timestamp': datetime.utcnow().isoformat()
            }
            message.metadata = json.dumps(metadata)
            
            self.db.add(message)
            self.db.commit()
            
            logger.info(f"Feedback recorded for message {message_id}: {feedback_type}")
            return True
        except Exception as e:
            logger.error(f"Error recording feedback: {e}")
            return False

    async def get_feedback_stats(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Get feedback statistics."""
        statement = select(ChatMessage).where(ChatMessage.role == 'assistant')
        if user_id:
            statement = statement.where(ChatMessage.user_id == user_id)
        
        messages = self.db.exec(statement).all()
        
        stats = {'helpful': 0, 'not_helpful': 0, 'report': 0, 'no_feedback': 0}
        
        for msg in messages:
            if msg.metadata:
                metadata = json.loads(msg.metadata)
                feedback = metadata.get('feedback', {})
                feedback_type = feedback.get('type')
                if feedback_type in stats:
                    stats[feedback_type] += 1
                else:
                    stats['no_feedback'] += 1
            else:
                stats['no_feedback'] += 1
        
        total = sum(stats.values())
        stats['total'] = total
        stats['helpful_rate'] = (stats['helpful'] / total * 100) if total > 0 else 0
        
        return stats
