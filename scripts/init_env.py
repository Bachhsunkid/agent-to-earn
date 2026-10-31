"""Create or complete .env from .env.example, generating the API secrets.

Never prints secret values. Safe to re-run: existing non-empty values are kept.
"""

import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / ".env.example"
TARGET = ROOT / ".env"

REQUIRED = ("TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID", "API_PASSWORD", "API_JWT_SECRET", "API_WS_TOKEN")
GENERATED = {
    "API_PASSWORD": lambda: secrets.token_urlsafe(18),
    "API_JWT_SECRET": lambda: secrets.token_hex(32),
    "API_WS_TOKEN": lambda: secrets.token_urlsafe(24),
}


def read_env(path: Path = TARGET) -> dict[str, str]:
    values = {}
    for line in path.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and not key.lstrip().startswith("#"):
            values[key.strip()] = value.strip()
    return values


def update_env(updates: dict[str, str], path: Path = TARGET) -> None:
    """Set KEY=value lines in place, keeping comments and order; append unknown keys."""
    lines, done = [], set()
    for line in path.read_text().splitlines():
        key = line.partition("=")[0].strip()
        if "=" in line and key in updates and not key.startswith("#"):
            line = f"{key}={updates[key]}"
            done.add(key)
        lines.append(line)
    lines += [f"{key}={value}" for key, value in updates.items() if key not in done]
    path.write_text("\n".join(lines) + "\n")
    path.chmod(0o600)


def main() -> int:
    if not TARGET.exists():
        TARGET.write_text(EXAMPLE.read_text())
    current = read_env()
    update_env({key: make() for key, make in GENERATED.items() if not current.get(key)})
    missing = [key for key in REQUIRED if not read_env().get(key)]
    print(f"wrote {TARGET.name}" + (f"; still to fill in: {', '.join(missing)}" if missing else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
