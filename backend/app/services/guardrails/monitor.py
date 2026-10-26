"""
Monitor model (M4.5): the input guardrail's second layer. After the regex layer allows a message, a model
classifies it as immigration | harmful | injection | off_topic with a confidence. Deny wins, but only above a
confidence threshold: a wrongly refused legitimate question is the costly error (done-criterion: 0 false positives).
If the monitor can't run (model down, unreadable output), the message goes through on the regex layer's decision
and the result says so (M4.7: "checked by code only").
"""

import logging
from dataclasses import dataclass
from typing import Literal, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

IMMIGRATION = "immigration"
DENY = ("harmful", "injection", "off_topic")


class MonitorVerdict(BaseModel):
    category: Literal["immigration", "harmful", "injection", "off_topic"]
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


@dataclass(frozen=True)
class MonitorResult:
    category: Optional[str]          # None when the monitor couldn't run
    confidence: float = 0.0
    denied: bool = False
    available: bool = True

    def summary(self) -> dict:
        return {"category": self.category, "confidence": round(self.confidence, 2), "denied": self.denied,
                "available": self.available}


async def classify(message: str, threshold: float) -> MonitorResult:
    from app.core.exceptions import AIServiceUnavailableError, LLMStructuredOutputError
    from app.services.llm import llm_service
    from app.services.prompt_registry import get_prompt

    system, user = get_prompt("monitor").render(message=message)
    try:
        verdict = await llm_service.structured_call(MonitorVerdict, system, user, role="monitor", max_tokens=60)
    except (AIServiceUnavailableError, LLMStructuredOutputError) as e:
        logger.warning(f"[MONITOR] unavailable ({type(e).__name__}); the regex layer's decision stands")
        return MonitorResult(None, available=False)
    denied = verdict.category in DENY and verdict.confidence >= threshold
    return MonitorResult(verdict.category, verdict.confidence, denied)
