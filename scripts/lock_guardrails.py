"""Re-hash the protected guardrail files into agent/guardrails.lock.

Operator only: run after you deliberately change a protected file. The research
agent is not allowed to run this script.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

import gate  # noqa: E402

if __name__ == "__main__":
    gate.write_lock()
    print(f"wrote {gate.LOCK_FILE.relative_to(gate.common.ROOT)} ({len(gate.PROTECTED)} files)")
