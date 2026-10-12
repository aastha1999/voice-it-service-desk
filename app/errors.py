"""Domain errors. Every error carries a `speakable` sentence the voice agent can say verbatim."""


class ServiceDeskError(Exception):
    status_code = 400
    default_code = "BAD_REQUEST"
    default_speakable = "Sorry, I couldn't complete that request."

    def __init__(self, message: str, *, code: str | None = None, speakable: str | None = None,
                 details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.code = code or self.default_code
        self.speakable = speakable or self.default_speakable
        self.details = details or {}


class InvalidInput(ServiceDeskError):
    status_code = 422
    default_code = "INVALID_INPUT"
    default_speakable = "I didn't quite catch all the details. Could you repeat that?"


class Unauthorized(ServiceDeskError):
    status_code = 401
    default_code = "UNAUTHORIZED"
    default_speakable = "I'm having trouble connecting to the service desk system right now."


class Forbidden(ServiceDeskError):
    status_code = 403
    default_code = "FORBIDDEN"
    default_speakable = "I'm not able to do that for this device."


class NotFound(ServiceDeskError):
    status_code = 404
    default_code = "NOT_FOUND"
    default_speakable = "I couldn't find that. Could you double-check it for me?"


class Conflict(ServiceDeskError):
    status_code = 409
    default_code = "CONFLICT"
    default_speakable = "That can't be done in the device's current state."


class ConfirmationExpired(ServiceDeskError):
    status_code = 410
    default_code = "CONFIRMATION_EXPIRED"
    default_speakable = "That confirmation timed out, so nothing was changed. I can set it up again if you'd like."


class ConfirmationRejected(ServiceDeskError):
    status_code = 422
    default_code = "CONFIRMATION_REJECTED"
    default_speakable = "I need a clear yes before I take any action on the device."


class UpstreamUnavailable(ServiceDeskError):
    status_code = 502
    default_code = "MDM_UNAVAILABLE"
    default_speakable = ("I couldn't reach the device management system, so nothing has been changed yet. "
                         "I've noted it on your ticket and a technician will follow up.")


class InternalError(ServiceDeskError):
    status_code = 500
    default_code = "INTERNAL_ERROR"
    default_speakable = "Something went wrong on my side. I've logged it. Could we try that again?"
