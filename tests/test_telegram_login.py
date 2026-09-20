import asyncio
import sys
from types import SimpleNamespace

from scripts import telegram_login


def test_login_prompts_run_off_event_loop_and_password_is_not_trimmed(monkeypatch, capsys):
    class PasswordNeeded(Exception):
        pass

    prompts = []
    sign_ins = []
    state = {}

    async def to_thread(function, prompt):
        prompts.append((function, prompt))
        if function is telegram_login.getpass:
            return "  password  "
        return " 12345 "

    class Client:
        def __init__(self, *args):
            self.session = SimpleNamespace(save=lambda: "fake-session")

        async def connect(self):
            pass

        async def is_user_authorized(self):
            return False

        async def send_code_request(self, phone):
            assert phone == "+380000000000"

        async def sign_in(self, **kwargs):
            sign_ins.append(kwargs)
            if "code" in kwargs:
                raise PasswordNeeded

        async def disconnect(self):
            state["disconnected"] = True

    monkeypatch.setitem(sys.modules, "telethon", SimpleNamespace(TelegramClient=Client))
    monkeypatch.setitem(sys.modules, "telethon.sessions", SimpleNamespace(StringSession=lambda: None))
    monkeypatch.setitem(sys.modules, "telethon.errors", SimpleNamespace(SessionPasswordNeededError=PasswordNeeded))
    monkeypatch.setattr(asyncio, "to_thread", to_thread)
    monkeypatch.setattr("sys.argv", ["telegram_login", "--api-id", "1", "--api-hash", "fake", "--phone", "+380000000000"])
    assert telegram_login.main() == 0
    assert sign_ins == [{"phone": "+380000000000", "code": "12345"}, {"password": "  password  "}]
    assert prompts[1][0] is telegram_login.getpass
    assert state["disconnected"] is True
    assert "password" not in capsys.readouterr().out
