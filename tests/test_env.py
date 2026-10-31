import io
import json

import pytest

import init_env
import telegram_chat_id

EXAMPLE = """# comment
TELEGRAM_TOKEN=
TELEGRAM_CHAT_ID=
API_USERNAME=admin
API_PASSWORD=
API_JWT_SECRET=
API_WS_TOKEN=
DRY_RUN=true
"""


@pytest.fixture
def env_files(tmp_path, monkeypatch):
    example, target = tmp_path / ".env.example", tmp_path / ".env"
    example.write_text(EXAMPLE)
    monkeypatch.setattr(init_env, "EXAMPLE", example)
    monkeypatch.setattr(init_env, "TARGET", target)
    monkeypatch.setattr(init_env.read_env, "__defaults__", (target,))
    monkeypatch.setattr(init_env.update_env, "__defaults__", (target,))
    return target


def test_init_env_generates_api_secrets_and_keeps_values(env_files, capsys):
    assert init_env.main() == 0
    first = init_env.read_env()
    assert all(first[k] for k in init_env.GENERATED) and first["API_USERNAME"] == "admin"
    assert "still to fill in: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID" in capsys.readouterr().out
    assert oct(env_files.stat().st_mode & 0o777) == "0o600"

    init_env.update_env({"TELEGRAM_TOKEN": "123:abc", "NEW_KEY": "x"})
    assert init_env.main() == 0
    second = init_env.read_env()
    assert {k: second[k] for k in init_env.GENERATED} == {k: first[k] for k in init_env.GENERATED}
    assert second["TELEGRAM_TOKEN"] == "123:abc" and second["NEW_KEY"] == "x"
    assert env_files.read_text().startswith("# comment\n")
    assert first["API_PASSWORD"] not in capsys.readouterr().out


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def updates(*chats):
    return FakeResponse(json.dumps({"result": [
        {"message": {"chat": {"id": cid, "type": kind}}} for cid, kind in chats]}).encode())


def test_telegram_chat_id(env_files, monkeypatch, capsys):
    init_env.main()
    assert telegram_chat_id.main() == 1  # no token yet
    init_env.update_env({"TELEGRAM_TOKEN": "123:abc"})

    replies = [updates(), updates((1, "private"), (2, "private")), updates((42, "private"), (7, "group"))]
    monkeypatch.setattr(telegram_chat_id.urllib.request, "urlopen", lambda url, timeout: replies.pop(0))
    assert telegram_chat_id.main() == 1  # nobody messaged the bot
    assert telegram_chat_id.main() == 1  # ambiguous
    assert telegram_chat_id.main() == 0
    assert init_env.read_env()["TELEGRAM_CHAT_ID"] == "42"
