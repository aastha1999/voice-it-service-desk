import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import connect
from app.main import create_app
from app.mdm import FakeMDM

TOOL_SECRET = "test-tool-secret"
ADMIN_KEY = "test-admin-key"
PRIYA = "priya.shah@northwind.example"
CONVO = "conv_test_123"


class Harness:
    def __init__(self, client: TestClient, settings: Settings, mdm: FakeMDM):
        self.client, self.settings, self.mdm = client, settings, mdm

    def tool(self, name: str, conversation_id: str | None = CONVO, **body):
        if conversation_id is not None:
            body["conversation_id"] = conversation_id
        return self.client.post(f"/tools/{name}", json=body, headers={"X-Tool-Secret": TOOL_SECRET})

    def admin(self, path: str, **params):
        return self.client.get(f"/admin/{path}", params=params, headers={"X-Admin-Key": ADMIN_KEY})

    def db(self):
        return connect(self.settings.db_path)

    def device_status(self, device_id: str) -> str:
        conn = self.db()
        try:
            return conn.execute("SELECT status FROM devices WHERE id = ?", (device_id,)).fetchone()[0]
        finally:
            conn.close()

    def events(self) -> list[str]:
        return [e["event"] for e in self.admin("audit", limit=1000).json()["data"]]

    # Common happy-path setup
    def open_ticket(self, device_id="DEV-001", caller=PRIYA, **kw):
        body = {"device_id": device_id, "caller_email": caller, "summary": "Left laptop in a taxi",
                "category": "lost_or_stolen", **kw}
        r = self.tool("create_ticket", **body)
        assert r.status_code == 200, r.json()
        return r.json()["data"]["id"]

    def request_action(self, action="lock", device_id="DEV-001", caller=PRIYA, ticket_id=None, **kw):
        ticket_id = ticket_id or self.open_ticket(device_id=device_id)
        return self.tool("request_device_action", device_id=device_id, action=action, ticket_id=ticket_id,
                         caller_email=caller, **kw)


@pytest.fixture
def make_harness(tmp_path):
    def _make(mdm_fault: str | None = None, **overrides) -> Harness:
        settings = Settings(db_path=str(tmp_path / "test.db"), tool_secret=TOOL_SECRET, admin_key=ADMIN_KEY,
                            mdm_backoff_seconds=0, **overrides)
        mdm = FakeMDM(fault=mdm_fault)
        client = TestClient(create_app(settings, mdm), raise_server_exceptions=False)
        return Harness(client, settings, mdm)
    return _make


@pytest.fixture
def h(make_harness) -> Harness:
    return make_harness()
