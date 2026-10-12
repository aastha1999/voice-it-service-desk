import pytest

from tests.conftest import PRIYA


def test_lookup_by_email_lists_all_devices_and_masks_serial(h):
    r = h.tool("lookup_device", email="  Priya.Shah@Northwind.example ")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["employee"]["name"] == "Priya Shah"
    assert [d["asset_tag"] for d in data["devices"]] == ["NW-1042", "NW-1043"]
    assert data["devices"][0]["serial_last4"] == "4F2K"
    assert "C02XK4F2K" not in r.text
    assert r.json()["speakable"] == ("I found 2 devices for Priya Shah: a MacBook Pro 14-inch (M3), asset tag NW-1042, "
                                     "and an iPhone 15, asset tag NW-1043.")


@pytest.mark.parametrize("spoken", ["NW-1042", "nw 1042", "NW1042", "1042"])
def test_lookup_by_asset_tag_tolerates_speech_variants(h, spoken):
    r = h.tool("lookup_device", asset_tag=spoken)
    assert r.status_code == 200
    assert r.json()["data"]["devices"][0]["device_id"] == "DEV-001"


def test_lookup_no_match_is_404_and_audited(h):
    r = h.tool("lookup_device", email="nobody@northwind.example")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "LOOKUP_NO_MATCH"
    assert "spell" in r.json()["speakable"]
    assert h.events() == ["device.lookup"]


def test_lookup_requires_an_identifier(h):
    r = h.tool("lookup_device")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "MISSING_IDENTIFIER"


def test_create_ticket_and_read_it_back(h):
    r = h.tool("create_ticket", device_id="DEV-003", caller_email="marcus.lee@northwind.example",
               summary="Laptop won't connect to VPN", category="software", priority="low")
    assert r.status_code == 200
    t = r.json()["data"]
    assert t["id"] == "INC-1001" and t["priority"] == "low" and t["status"] == "open"

    r = h.tool("get_ticket", ticket_id="inc 1001")
    assert r.status_code == 200
    assert r.json()["data"]["notes"][0]["body"].startswith("Ticket opened by voice agent")


def test_lost_device_tickets_are_at_least_high_priority(h):
    r = h.tool("create_ticket", device_id="DEV-001", caller_email=PRIYA, summary="Left laptop in a taxi",
               category="lost_or_stolen", priority="low")
    assert r.json()["data"]["priority"] == "high"


def test_ticket_creation_is_idempotent_within_a_conversation(h):
    first = h.open_ticket()
    r = h.tool("create_ticket", device_id="DEV-001", caller_email=PRIYA, summary="Left laptop in a taxi")
    assert r.json()["data"]["id"] == first and r.json()["data"]["deduplicated"] is True
    # A different call gets its own ticket.
    r = h.tool("create_ticket", conversation_id="conv_other", device_id="DEV-001", caller_email=PRIYA,
               summary="Left laptop in a taxi")
    assert r.json()["data"]["id"] != first


def test_ticket_ids_increment(h):
    assert h.open_ticket() == "INC-1001"
    assert h.open_ticket(device_id="DEV-002") == "INC-1002"


def test_ticket_for_unknown_device_or_caller(h):
    assert h.tool("create_ticket", device_id="DEV-999", caller_email=PRIYA, summary="Broken screen").status_code == 404
    r = h.tool("create_ticket", device_id="DEV-001", caller_email="ghost@northwind.example", summary="Broken screen")
    assert r.status_code == 404 and r.json()["error"]["code"] == "CALLER_NOT_FOUND"


def test_unknown_ticket(h):
    r = h.tool("get_ticket", ticket_id="INC-4040")
    assert r.status_code == 404 and r.json()["error"]["code"] == "TICKET_NOT_FOUND"
