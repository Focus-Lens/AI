"""Checks the real Gemini filter against fixed cases. Run before every demo.

    python eval.py            # all 20 cases (needs GEMINI_API_KEY in .env)
    python eval.py --limit 6  # 3 that must be allowed + 3 that must be blocked (saves free quota)
"""

import json
import sys
import time
from pathlib import Path

from . import config  # loads .env
from .gemini_client import GeminiLLM, is_daily_quota
from .chat import chat
from google.genai import errors
import os

cases = json.loads((Path(__file__).parent / "tests" / "eval_cases.json").read_text(encoding="utf-8"))
if "--limit" in sys.argv:
    limit = int(sys.argv[sys.argv.index("--limit") + 1])
    half = (limit + 1) // 2
    cases = [c for c in cases if c["expect"] == "allowed"][:half] + [c for c in cases if c["expect"] == "blocked"][: limit - half]

key = os.environ.get("GEMINI_API_KEY", "")
if not key or key.startswith("paste_"):
    sys.exit("✗ GEMINI_API_KEY is missing in .env")

llm = GeminiLLM(key)
print(f"model: {config.GEMINI_MODEL} · thinking: {config.GEMINI_THINKING} · cases: {len(cases)}\n")

passed = errors_count = tokens = 0
for c in cases:
    try:
        r = chat(c["message"], llm, subject="Biology")
        tokens += r["usage"]["total"]
        got = "blocked" if r["blocked"] else "allowed"
        ok = got == c["expect"]
        passed += ok
        extra = "" if ok else f"  -> expected {c['expect']}, got {got} ({r['reason']})"
        print(f"{'✓' if ok else '✗'} [{r['category']}] {c['message']}{extra}")
    except errors.APIError as e:
        errors_count += 1
        print(f"! [error {e.code}] {c['message']}")
        if e.code in (400, 404) or is_daily_quota(e):
            print("\nStopping: bad key/model or the daily free quota is used up.")
            break
    time.sleep(4)

done = len(cases) - errors_count
avg = round(tokens / done) if done else 0
print(f"\n{passed}/{done} correct" + (f" · {errors_count} errors" if errors_count else "") + f" · {tokens} tokens · ~{avg} per message")
sys.exit(0 if passed == len(cases) else 1)
