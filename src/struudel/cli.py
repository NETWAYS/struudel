import click
from flask.cli import AppGroup

from struudel.database import SessionLocal
from struudel.mail import send_mail
from struudel.models.poll import Poll
from struudel.models.poll_response import PollResponse
from struudel.models.user import User
from struudel.services import user as user_service
from struudel.services.notifications import build_poll_url, build_vote_url, render_mail
from struudel.services.poll import (
    count_responses,
    get_audience_response_status,
)

superuser_cli = AppGroup("superuser", help="Manage superuser privileges.")


def _set_superuser_by_username(preferred_username: str, value: bool) -> "user_service.User":
    with SessionLocal() as db:
        target = user_service.get_user_by_username(db, preferred_username=preferred_username)
        if target is None:
            raise click.ClickException(f"User {preferred_username!r} not found.")
        user = user_service.set_superuser(db, user_id=target.id, value=value)
    assert user is not None  # we just looked it up in the same session
    return user


@superuser_cli.command("grant")
@click.argument("preferred_username")
def grant(preferred_username: str) -> None:
    """Make USER a superuser."""
    user = _set_superuser_by_username(preferred_username, value=True)
    click.echo(f"Granted superuser to {user.preferred_username} (id={user.id}).")


@superuser_cli.command("revoke")
@click.argument("preferred_username")
def revoke(preferred_username: str) -> None:
    """Revoke superuser from USER."""
    user = _set_superuser_by_username(preferred_username, value=False)
    click.echo(f"Revoked superuser from {user.preferred_username} (id={user.id}).")


@superuser_cli.command("list")
def list_() -> None:
    """List all superusers."""
    with SessionLocal() as db:
        users = user_service.list_superusers(db)
    if not users:
        click.echo("(no superusers)")
        return
    for u in users:
        click.echo(f"{u.preferred_username}\t{u.email}\t(id={u.id})")


mail_cli = AppGroup("mail", help="Send mails synchronously for testing.")


def _get_poll(db, poll_id: int) -> Poll:
    poll = db.get(Poll, poll_id)
    if poll is None:
        raise click.ClickException(f"poll {poll_id} not found")
    return poll


def _get_user(db, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise click.ClickException(f"user {user_id} not found")
    if not user.email:
        raise click.ClickException(f"user {user_id} has no email")
    return user


@mail_cli.command("test")
@click.option("--to", required=True, help="Recipient email address.")
def test_(to: str) -> None:
    """Send a trivial smoke-test mail (no DB, no templates)."""
    send_mail(
        to=to,
        subject="Struudel mail test",
        html="<p>This is a Struudel SMTP smoke test.</p>",
        text="This is a Struudel SMTP smoke test.\n",
    )
    click.echo(f"sent test mail to {to}")


@mail_cli.command("invitation")
@click.option("--poll-id", type=int, required=True)
@click.option("--user-id", type=int, required=True)
def invitation(poll_id: int, user_id: int) -> None:
    """Render and send the invitation mail for POLL_ID to USER_ID."""
    with SessionLocal() as db:
        poll = _get_poll(db, poll_id)
        user = _get_user(db, user_id)
        subject, html, text = render_mail(
            "invitation",
            poll=poll,
            recipient_user=user,
            vote_url=build_vote_url(poll),
        )
        send_mail(to=user.email, subject=subject, html=html, text=text)
    click.echo(f"sent invitation to {user.email}")


@mail_cli.command("mandatory-reminder")
@click.option("--poll-id", type=int, required=True)
@click.option("--user-id", type=int, required=True)
@click.option("--tier", type=click.Choice(["72h", "24h", "2h"]), default="24h")
def mandatory_reminder(poll_id: int, user_id: int, tier: str) -> None:
    """Render and send a mandatory reminder mail (bypasses task guards/dedup)."""
    with SessionLocal() as db:
        poll = _get_poll(db, poll_id)
        user = _get_user(db, user_id)
        subject, html, text = render_mail(
            "mandatory_reminder",
            poll=poll,
            recipient_user=user,
            tier=tier,
            vote_url=build_vote_url(poll),
        )
        send_mail(to=user.email, subject=subject, html=html, text=text)
    click.echo(f"sent mandatory-reminder ({tier}) to {user.email}")


@mail_cli.command("poll-closed-audience")
@click.option("--poll-id", type=int, required=True)
@click.option("--user-id", type=int, required=True)
def poll_closed_audience(poll_id: int, user_id: int) -> None:
    """Render and send the poll-closed mail to an audience member."""
    with SessionLocal() as db:
        poll = _get_poll(db, poll_id)
        user = _get_user(db, user_id)
        subject, html, text = render_mail(
            "poll_closed_audience",
            poll=poll,
            recipient_user=user,
            poll_url=build_poll_url(poll),
        )
        send_mail(to=user.email, subject=subject, html=html, text=text)
    click.echo(f"sent poll-closed-audience to {user.email}")


@mail_cli.command("poll-closed-owner")
@click.option("--poll-id", type=int, required=True)
def poll_closed_owner(poll_id: int) -> None:
    """Render and send the poll-closed mail to the poll owner."""
    with SessionLocal() as db:
        poll = _get_poll(db, poll_id)
        owner = poll.created_by
        if not owner.email:
            raise click.ClickException(f"owner of poll {poll_id} has no email")
        subject, html, text = render_mail(
            "poll_closed_owner",
            poll=poll,
            recipient_user=owner,
            response_count=count_responses(db, poll_id=poll.id),
            poll_url=build_poll_url(poll),
        )
        send_mail(to=owner.email, subject=subject, html=html, text=text)
    click.echo(f"sent poll-closed-owner to {owner.email}")


@mail_cli.command("response-notification")
@click.option("--response-id", type=int, required=True)
def response_notification(response_id: int) -> None:
    """Render and send the owner-notification mail for a response."""
    with SessionLocal() as db:
        response = db.get(PollResponse, response_id)
        if response is None:
            raise click.ClickException(f"response {response_id} not found")
        poll = response.poll
        owner = poll.created_by
        if not owner.email:
            raise click.ClickException(f"owner of poll {poll.id} has no email")
        anonymous = bool(poll.attributes.get("anonymous_votes", False))
        voter = response.user
        voter_name = (voter.name or voter.preferred_username) if voter else ""
        subject, html, text = render_mail(
            "response_notification",
            poll=poll,
            recipient_user=owner,
            voter_name=voter_name,
            anonymous=anonymous,
            response_count=count_responses(db, poll_id=poll.id),
            poll_url=build_poll_url(poll),
        )
        send_mail(to=owner.email, subject=subject, html=html, text=text)
    click.echo(f"sent response-notification to {owner.email}")


@mail_cli.command("non-responder-report")
@click.option("--poll-id", type=int, required=True)
def non_responder_report(poll_id: int) -> None:
    """Render and send the non-responder report to the poll owner."""
    with SessionLocal() as db:
        poll = _get_poll(db, poll_id)
        owner = poll.created_by
        if not owner.email:
            raise click.ClickException(f"owner of poll {poll_id} has no email")
        _, pending = get_audience_response_status(db, poll=poll)
        subject, html, text = render_mail(
            "non_responder_report",
            poll=poll,
            recipient_user=owner,
            non_responders=pending,
            poll_url=build_poll_url(poll),
        )
        send_mail(to=owner.email, subject=subject, html=html, text=text)
    click.echo(f"sent non-responder-report to {owner.email}")
