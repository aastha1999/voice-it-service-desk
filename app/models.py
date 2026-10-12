from typing import Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field
from typing_extensions import Annotated


def _email(value: str) -> str:
    value = value.strip().lower()
    local, _, domain = value.partition("@")
    if not local or "." not in domain or " " in value:
        raise ValueError("must be an email address")
    return value


Email = Annotated[str, AfterValidator(_email)]


class ToolRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")
    # Populated by ElevenLabs from the {{system__conversation_id}} dynamic variable.
    conversation_id: str | None = Field(default=None, max_length=128)


class LookupDeviceRequest(ToolRequest):
    email: Email | None = None
    asset_tag: str | None = Field(default=None, max_length=32)


class CreateTicketRequest(ToolRequest):
    device_id: str = Field(max_length=32)
    caller_email: Email
    summary: str = Field(min_length=5, max_length=500)
    category: Literal["hardware", "software", "access", "lost_or_stolen", "other"] = "other"
    priority: Literal["low", "medium", "high", "critical"] = "medium"


class GetTicketRequest(ToolRequest):
    ticket_id: str = Field(max_length=32)


class RequestDeviceActionRequest(ToolRequest):
    device_id: str = Field(max_length=32)
    action: Literal["restart", "lock", "wipe"]
    ticket_id: str = Field(max_length=32)
    caller_email: Email


class ConfirmDeviceActionRequest(ToolRequest):
    pending_action_id: str = Field(max_length=32)
    caller_utterance: str = Field(min_length=1, max_length=500)


class CancelDeviceActionRequest(ToolRequest):
    pending_action_id: str = Field(max_length=32)
