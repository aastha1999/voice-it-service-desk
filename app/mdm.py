"""Mobile Device Management client. `FakeMDM` stands in for Jamf / Intune / Kandji."""
import uuid
from typing import Protocol


class MDMUnavailable(Exception):
    pass


class MDMClient(Protocol):
    def send_command(self, device_id: str, action: str, online: bool) -> dict: ...


class FakeMDM:
    """fault=None: healthy. "outage": every call fails. "flaky": first call fails, then healthy."""

    def __init__(self, fault: str | None = None):
        self.fault = fault
        self.calls: list[tuple[str, str]] = []

    def send_command(self, device_id: str, action: str, online: bool) -> dict:
        self.calls.append((device_id, action))
        if self.fault == "outage" or (self.fault == "flaky" and len(self.calls) == 1):
            raise MDMUnavailable("MDM API timed out")
        # Real MDMs queue commands for offline devices and deliver them at next check-in.
        return {"command_id": f"CMD-{uuid.uuid4().hex[:8]}", "status": "completed" if online else "queued"}
