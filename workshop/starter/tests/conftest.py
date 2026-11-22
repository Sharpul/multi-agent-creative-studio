"""Offline boundary: no developer dotenv, credentials, or outbound service requests."""
import os
import socket
import pytest

os.environ["PYTHON_DOTENV_DISABLED"] = "1"
for key in ("COPYWRITER_AGENT_URL", "DESIGNER_AGENT_URL", "STRATEGIST_AGENT_URL", "CRITIC_AGENT_URL", "PM_AGENT_URL", "NOTION_TOKEN", "NOTION_PROJECT_DATABASE_ID", "NOTION_TASKS_DATABASE_ID"):
    os.environ.pop(key, None)


@pytest.fixture(autouse=True)
def offline_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("External network access prohibited in offline tests")
    original_connect, original_pair = socket.socket.connect, socket.socketpair
    def local_pair(*args, **kwargs):
        # Windows asyncio needs its internal loopback wakeup pipe.
        with monkeypatch.context() as local:
            local.setattr(socket.socket, "connect", original_connect)
            return original_pair(*args, **kwargs)
    monkeypatch.setattr(socket, "socketpair", local_pair)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
