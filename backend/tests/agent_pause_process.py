"""
Helper for tests/test_agent_pause.py (M5.4): pause an agent run in one process and resume it in another, through the
Postgres checkpointer (AGENT_CHECKPOINT_URL), as after a worker restart. The model is scripted; prints one JSON line.

  python tests/agent_pause_process.py pause <thread_id>
  python tests/agent_pause_process.py resume <thread_id>
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent import loop  # noqa: E402
from app.services.llm import llm_service  # noqa: E402
from app.services.llm_fake import FakeLLM  # noqa: E402
from app.workers.async_runner import agent_loop_factory  # noqa: E402

DECIDE = r"planner of a Canadian immigration assistant"
QUESTION = "How much money do I need to show if my family is coming with me?"
FACTS = "OFFICIAL IRCC REGULATORY FACTS: a family of four needs CAD $43,572."


def act(action, query=""):
    return {"thought": "", "action": action, "query": query}


async def main(command: str, thread_id: str) -> None:
    fake = FakeLLM()
    llm_service.structured_call = fake.structured_call
    if command == "pause":
        fake.when(DECIDE, act("ask_user", "How many family members are coming with you?"))
        result = await loop.run(QUESTION, FACTS, [], thread_id=thread_id)
        out = {"outcome": result.outcome, "thread_id": result.thread_id, "ask": result.ask}
    else:
        fake.when(DECIDE, act("answer", "How much money does a family of four need to show?"))
        result = await loop.resume(thread_id, "Four of us in total.")
        prompts = [c["user_prompt"] for c in fake.calls]
        out = {"outcome": result.outcome if result else None,
               "answer_question": result.answer_question if result else None,
               "question": result.question if result else None,
               "reply_seen": any("Four of us in total." in p for p in prompts),
               "left": await loop.paused_question(thread_id)}
    print(json.dumps(out))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]), loop_factory=agent_loop_factory())
