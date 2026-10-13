"""
Monitor-model measurements for M0.4b: load time, swap cost and memory, per candidate.

For each candidate model C (with the primary model P = OLLAMA_MODEL):
  1. cold load:  unload everything, call C           -> load time from disk
  2. pair:       call P, then C                      -> C's load time while P is resident
  3. swap back:  call P again                        -> 0 s if P stayed loaded, else the eviction cost
  4. memory:     which models Ollama keeps resident, their size, and free system RAM
Each scenario is repeated --repeat times. Judgment accuracy is measured separately with
scripts/probe_structured.py --roles verifier --model C.

Usage (from backend/):
  .venv\\Scripts\\python.exe scripts\\measure_models.py --candidates phi4-mini,qwen2.5-coder:3b
Results are written to logs/measure_models_<timestamp>.json
"""

import argparse
import asyncio
import ctypes
import json
import sys
import time
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import httpx  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services.llm import llm_service, record_llm_calls  # noqa: E402

BASE = settings.OLLAMA_BASE_URL.rstrip("/")


def free_ram_gb() -> float:
    """Free physical memory (Windows GlobalMemoryStatusEx; 0 elsewhere)."""
    class MemoryStatus(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    try:
        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(MemoryStatus)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        return round(status.ullAvailPhys / 1024 ** 3, 2)
    except Exception:
        return 0.0


def _tag(name: str) -> str:
    """Ollama reports "phi4-mini" as "phi4-mini:latest"."""
    return name if ":" in name else f"{name}:latest"


async def resident_models(client: httpx.AsyncClient) -> list:
    data = (await client.get(f"{BASE}/api/ps")).json()
    return [{"name": m["name"], "size_gb": round(m.get("size", 0) / 1024 ** 3, 2),
             "vram_gb": round(m.get("size_vram", 0) / 1024 ** 3, 2)} for m in data.get("models", [])]


async def unload_all(client: httpx.AsyncClient) -> None:
    for m in await resident_models(client):
        await client.post(f"{BASE}/api/generate", json={"model": m["name"], "keep_alive": 0})
    for _ in range(30):
        if not await resident_models(client):
            return
        await asyncio.sleep(0.5)


async def tiny_call(model: str) -> dict:
    """A 1-token call; returns Ollama's load time and the client wall time."""
    with record_llm_calls() as calls:
        await llm_service.generate_answer(system_prompt="Reply with OK.", user_prompt="OK", temperature=0.0,
                                          max_tokens=1, model=model, role="measure")
    stats = calls[-1]
    return {"model": model, "load_s": stats.load_s, "wall_s": stats.wall_s}


async def measure(primary: str, candidate: str, repeat: int) -> dict:
    runs = []
    async with httpx.AsyncClient(timeout=120) as client:
        for r in range(repeat):
            await unload_all(client)
            ram_empty = free_ram_gb()
            cold = await tiny_call(candidate)
            await unload_all(client)

            p_first = await tiny_call(primary)
            ram_primary = free_ram_gb()
            c_with_p = await tiny_call(candidate)
            resident_after_c = await resident_models(client)
            ram_both = free_ram_gb()
            p_again = await tiny_call(primary)
            resident_after_p = await resident_models(client)

            run = {
                "repeat": r + 1,
                "free_ram_gb": {"nothing_loaded": ram_empty, "primary_loaded": ram_primary, "after_candidate": ram_both},
                "candidate_cold_load_s": cold["load_s"], "candidate_cold_wall_s": cold["wall_s"],
                "primary_load_s": p_first["load_s"],
                "candidate_load_with_primary_resident_s": c_with_p["load_s"],
                "candidate_wall_with_primary_resident_s": c_with_p["wall_s"],
                "swap_back_primary_load_s": p_again["load_s"], "swap_back_primary_wall_s": p_again["wall_s"],
                "resident_after_candidate": resident_after_c, "resident_after_swap_back": resident_after_p,
                "both_resident": {_tag(m["name"]) for m in resident_after_c} >= {_tag(primary), _tag(candidate)},
            }
            runs.append(run)
            print(f"  {candidate} run {r + 1}: cold {cold['load_s']}s | with {primary} resident {c_with_p['load_s']}s"
                  f" | swap back {p_again['load_s']}s | both resident={run['both_resident']}"
                  f" | free RAM {ram_empty}->{ram_primary}->{ram_both} GB", flush=True)
    return {"primary": primary, "candidate": candidate, "runs": runs}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", default="phi4-mini")
    ap.add_argument("--primary", default=settings.OLLAMA_MODEL)
    ap.add_argument("--repeat", type=int, default=3)
    args = ap.parse_args()

    report = {"primary": args.primary, "num_ctx": settings.OLLAMA_NUM_CTX, "results": []}
    for candidate in args.candidates.split(","):
        print(f"\n=== {args.primary} + {candidate.strip()} ===", flush=True)
        report["results"].append(await measure(args.primary, candidate.strip(), args.repeat))

    out_dir = BACKEND / "logs"
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f"measure_models_{datetime.now():%Y%m%d_%H%M%S}.json"
    path.write_text(json.dumps(report, indent=2, default=list), encoding="utf-8")
    print(f"saved {path}", flush=True)
    await llm_service.close()


if __name__ == "__main__":
    t0 = time.perf_counter()
    asyncio.run(main())
    print(f"total {time.perf_counter() - t0:.0f}s")
