from urllib.parse import urlparse

from flask import current_app, redirect, render_template, request, session, url_for
from werkzeug.wrappers import Response

from struudel.blueprints.auth import bp
from struudel.database import SessionLocal
from struudel.extensions import oauth
from struudel.services.user import (
    get_user_by_external_id,
    sync_superuser_from_oidc_groups,
    upsert_user,
    user_to_session_dict,
)
from struudel.tasks.user.avatar_sync import sync_user_avatar

_REDIRECT_MAX_LEN = 2048


def _is_safe_redirect(url: str) -> bool:
    if len(url) > _REDIRECT_MAX_LEN:
        return False
    parsed = urlparse(url)
    return not parsed.scheme and not parsed.netloc


def _login_error(message: str, status: int) -> tuple[str, int]:
    return render_template("auth/login.html", error=message), status


@bp.route("/login")
def login() -> str:
    return render_template("auth/login.html")


@bp.route("/authorize")
def authorize() -> Response | tuple[str, int]:
    redirect_uri = url_for("auth.callback", _external=True)
    next_url = request.args.get("next")
    if next_url and _is_safe_redirect(next_url):
        session["post_login_redirect"] = next_url
    try:
        return oauth.oidc.authorize_redirect(redirect_uri)
    except Exception as e:
        current_app.logger.error("OAuth authorize_redirect failed: %s", e)
        return _login_error("Authentication provider unavailable. Please try again.", 502)


@bp.route("/callback")
def callback() -> Response | tuple[str, int]:
    try:
        token = oauth.oidc.authorize_access_token()
        userinfo = token.get("userinfo") or oauth.oidc.userinfo(token=token)
    except Exception as e:
        current_app.logger.error("OAuth callback failed: %s", e)
        return _login_error("Authentication failed. Please try again.", 502)

    sub = userinfo.get("sub") if userinfo else None
    email = userinfo.get("email") if userinfo else None
    if not sub or not email:
        current_app.logger.warning("Incomplete userinfo from OIDC provider: %s", userinfo)
        return _login_error("Incomplete user data returned by SSO provider.", 502)

    preferred_username = userinfo.get("preferred_username") or sub
    display_name = userinfo.get("name") or preferred_username

    try:
        with SessionLocal() as db:
            existing = get_user_by_external_id(db, external_id=sub)
            if existing is not None and not existing.is_active:
                current_app.logger.warning(
                    "Login attempt by inactive user %d (%s)",
                    existing.id,
                    existing.preferred_username,
                )
                return _login_error("Your account is inactive.", 403)

            user = upsert_user(
                db,
                external_id=sub,
                preferred_username=preferred_username,
                name=display_name,
                given_name=userinfo.get("given_name"),
                family_name=userinfo.get("family_name"),
                email=email,
                profile=userinfo.get("profile"),
                picture=userinfo.get("picture"),
            )
            sync_superuser_from_oidc_groups(
                db, user_id=user.id, group_names=userinfo.get("groups")
            )
            session_user = user_to_session_dict(user)
            has_picture = bool(user.picture)
            user_id = user.id
    except Exception as e:
        current_app.logger.exception("Failed to upsert user: %s", e)
        return _login_error("Could not complete sign-in. Please try again.", 500)

    if has_picture:
        sync_user_avatar(user_id)

    session["user"] = session_user
    next_url = session.pop("post_login_redirect", None)
    return redirect(next_url or url_for("dashboard.index"))


@bp.route("/logout", methods=["POST"])
def logout() -> Response:
    session.clear()
    return redirect(url_for("dashboard.index"))
