"""
Retrieval smoke check (M0.14): does the right official page come back in the top 3 for known questions?

    cd backend
    python scripts/retrieval_check.py            # needs Ollama (query embeddings) and the real knowledge base

Run it before and after re-ingesting: the results must not get worse. Exit code 1 if any check fails.
Each check names the registry id (app/data/official_sources.yaml) of the page that must be retrieved.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.retrieval import retrieval_service  # noqa: E402
from app.services.source_registry import load_registry  # noqa: E402

TOP = 3
CHECKS = [
    ("How many hours can I work off campus during my studies?", "work-off-campus"),
    ("How much money do I need to show for a study permit?", "study-permit-financial-support"),
    ("Do I need a provincial attestation letter for my master's degree?", "study-permit-pal-tal"),
    ("How long is a post-graduation work permit after a 2-year program?", "pgwp-about"),
    ("What language level do I need for a PGWP after university?", "pgwp-eligibility"),
    ("How long can I stay in Canada as a visitor?", "visitor-visa-about"),
    ("How much work experience do I need for the Federal Skilled Worker Program?", "express-entry-fsw"),
    ("How old can my language test results be for Express Entry?", "express-entry-language-tests"),
    ("Do I need to give fingerprints and a photo?", "biometrics"),
    ("Is the Student Direct Stream still open?", "sds-ended-notice"),
]


async def main() -> int:
    urls = {e.id: e.url for e in load_registry().entries}
    failures = 0
    for question, expected_id in CHECKS:
        chunks = await retrieval_service.retrieve(question, country="Canada", top_k=TOP)
        got = [c["metadata"].get("url", "") for c in chunks]
        ok = urls[expected_id] in got
        failures += not ok
        print(f"{'OK  ' if ok else 'FAIL'} {expected_id:<32} {question}")
        if not ok:
            for url in got:
                print(f"       got: {url}")
    print(f"\n{len(CHECKS) - failures}/{len(CHECKS)} checks: the expected page is in the top {TOP}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
