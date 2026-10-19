"""
Show or accept the pinned model builds (M0.11).

    cd backend
    python scripts/pin_models.py                      # status: pinned vs installed for every configured model
    python scripts/pin_models.py --accept --note "full eval 54/63 on 2026-10-20"

--accept records the builds Ollama serves now as the accepted ones. Run it only after the full evaluation
(python scripts/eval_gate.py --full) passed on these builds: the pins say "answers were measured on this".
Exit code 1 if any configured model does not match its pin.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.model_pins import (PINS_PATH, check_pins, configured_models, installed_digests,  # noqa: E402
                                     write_pins)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--accept", action="store_true", help="pin the builds installed now")
    parser.add_argument("--note", default="", help="why these builds are accepted (e.g. the eval result)")
    args = parser.parse_args()

    if args.accept:
        if not args.note:
            parser.error("--accept needs --note saying which evaluation these builds passed")
        write_pins(await installed_digests(), configured_models(), args.note)
        print(f"Pinned in {PINS_PATH}")

    report = await check_pins()
    if not report.ollama_reachable:
        print("Ollama is not reachable.")
        return 1
    for m in report.models:
        print(f"{'OK  ' if m.ok else 'FAIL'} {m.status:<14} {m.model:<28} uses: {', '.join(m.uses)}"
              f"  pinned {(m.pinned or '-')[:12]}  installed {(m.installed or '-')[:12]}")
    for problem in report.problems():
        print(f"  - {problem}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
