from tests.conftest import PRIYA


def test_health_is_public(h):
    assert h.client.get("/health").json() == {"ok": True}


def test_tool_requires_secret_and_failure_is_audited(h):
    r = h.client.post("/tools/lookup_device", json={"email": PRIYA})
    assert r.status_code == 401
    body = r.json()
    assert body["ok"] is False and body["error"]["code"] == "UNAUTHORIZED"
    assert body["speakable"]
    r = h.client.post("/tools/lookup_device", json={"email": PRIYA}, headers={"X-Tool-Secret": "wrong"})
    assert r.status_code == 401
    assert h.events() == ["auth.failed", "auth.failed"]


def test_admin_requires_admin_key_not_tool_secret(h):
    from tests.conftest import TOOL_SECRET
    r = h.client.get("/admin/audit", headers={"X-Admin-Key": TOOL_SECRET})
    assert r.status_code == 401


def test_request_id_is_echoed_and_generated(h):
    r = h.tool("lookup_device", email=PRIYA)
    assert r.headers["X-Request-ID"] == r.json()["request_id"]
    r = h.client.post("/tools/lookup_device", json={"email": PRIYA},
                      headers={"X-Tool-Secret": h.settings.tool_secret, "X-Request-ID": "abc123"})
    assert r.json()["request_id"] == "abc123"


def test_validation_errors_use_envelope_with_speakable(h):
    r = h.tool("create_ticket", device_id="DEV-001", caller_email="not-an-email", summary="hi", priority="urgent")
    assert r.status_code == 422
    body = r.json()
    assert body["error"]["code"] == "INVALID_INPUT"
    fields = {f["field"] for f in body["error"]["details"]["fields"]}
    assert fields == {"caller_email", "summary", "priority"}
    assert "repeat" in body["speakable"]


def test_unexpected_errors_return_safe_envelope(make_harness):
    h = make_harness()

    def boom(*a, **k):
        raise RuntimeError("database exploded with secret details")
    h.client.app.state.mdm.send_command = boom  # not MDMUnavailable -> unexpected
    rid = h.request_action().json()["data"]["pending_action_id"]
    r = h.tool("confirm_device_action", pending_action_id=rid, caller_utterance="yes")
    assert r.status_code == 500
    body = r.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "secret" not in r.text
    # The action is marked failed rather than stuck mid-execution, so it can't be retried blindly.
    assert h.tool("confirm_device_action", pending_action_id=rid, caller_utterance="yes").status_code == 409
    assert h.events()[-1] == "action.failed"
