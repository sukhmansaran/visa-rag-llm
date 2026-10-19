"""
Record the fingerprint of every prompt version in app/prompts/versions.lock.json (M0.12).

    cd backend
    python scripts/lock_prompts.py           # after adding a prompt or bumping a version

Refuses if a prompt's text changed while its version number stayed the same: bump `version` in the
prompt file first. Old versions stay in the lock, so a trace or eval report can always be matched to the
text that produced it (that text is in git history under the same id and version).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.prompt_registry import LOCK_PATH, all_prompts, load_lock  # noqa: E402


def main() -> int:
    prompts, lock = all_prompts(), load_lock()
    changed = []
    for prompt in prompts.values():
        versions = lock.setdefault(prompt.id, {})
        locked = versions.get(str(prompt.version))
        if locked is not None and locked != prompt.fingerprint:
            print(f"REFUSED {prompt.id}: text changed under version {prompt.version} "
                  f"(locked {locked}, now {prompt.fingerprint}). Bump its version first.")
            return 1
        if locked is None:
            versions[str(prompt.version)] = prompt.fingerprint
            changed.append(prompt.tag)
    LOCK_PATH.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("Locked: " + ", ".join(changed) if changed else "Nothing new to lock.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
