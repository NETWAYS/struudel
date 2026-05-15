from collections.abc import Callable
from functools import wraps
from typing import Any

from flask import abort, g, redirect, request, url_for


def require_auth(view: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(view)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if not g.user:
            next_url = request.full_path.rstrip("?") or request.path
            return redirect(url_for("auth.login", next=next_url))
        return view(*args, **kwargs)

    return wrapper


def require_superuser(view: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(view)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if not g.user.get("is_superuser"):
            abort(403)
        return view(*args, **kwargs)

    return require_auth(wrapper)
