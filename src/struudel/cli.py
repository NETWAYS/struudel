import click
from flask.cli import AppGroup

from struudel.database import SessionLocal
from struudel.services import user as user_service

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
