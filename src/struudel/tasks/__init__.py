from struudel.extensions import huey as huey  # noqa: PLC0414
from struudel.tasks.mail import (  # noqa: F401
    dispatch_mandatory_reminders,
    dispatch_pending_invitations,
    send_invitation,
    send_mandatory_reminder,
    send_non_responder_report,
    send_poll_closed_audience,
    send_poll_closed_owner,
    send_response_notification,
)
from struudel.tasks.poll import close_due, purge_expired  # noqa: F401
from struudel.tasks.user import avatar_sync  # noqa: F401

__all__ = ["huey"]
