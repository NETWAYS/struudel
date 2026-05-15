from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from jinja2 import Environment, FileSystemLoader, select_autoescape

from struudel.config import settings
from struudel.models.poll import Poll

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "mail"

_html_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
    keep_trailing_newline=False,
    trim_blocks=True,
    lstrip_blocks=True,
)
_text_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=False,
    keep_trailing_newline=False,
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_mail(template_name: str, **ctx: Any) -> tuple[str, str, str]:
    """Render the three template variants for a mail.

    `template_name` is the bare stem, e.g. "invitation". The renderer reads
    `<name>.subject.txt`, `<name>.html` and `<name>.txt`. The context is
    augmented with `app_base_url` so every template can build absolute links.
    """
    ctx.setdefault("app_base_url", settings.app_base_url)

    subject = _text_env.get_template(f"{template_name}.subject.txt").render(**ctx).strip()
    html = _html_env.get_template(f"{template_name}.html").render(**ctx)
    text = _text_env.get_template(f"{template_name}.txt").render(**ctx)
    return subject, html, text


def build_poll_url(poll: Poll) -> str:
    return urljoin(_base(), f"/polls/{poll.id}")


def build_vote_url(poll: Poll) -> str:
    return urljoin(_base(), f"/polls/{poll.id}/vote")


def build_share_url(poll: Poll) -> str:
    return urljoin(_base(), f"/polls/s/{poll.share_token}")


def _base() -> str:
    base = settings.app_base_url.rstrip("/")
    return f"{base}/"
