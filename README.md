# Struudel

Self-hosted Doodle-style scheduling and decision tool. Bring your own identity
provider; Struudel handles the polls.

## Features

- **Mixed option types** in one poll — dates, datetimes, free-text
- **Three voting modes** — Yes/No/Maybe (Doodle-style), single choice, multi choice
- **Audience by user or group**, with optional mandatory participation
- **Public or private** visibility, plus anonymous voting and
  hide-results-until-close
- **Templates** for recurring poll shapes and **custom options** for user-added entries
- **Guest counts per Yes vote** and an optional **edit window** for responses
- **Email** via SMTP — invitations, close notifications, reminders and
  non-responder reports for mandatory polls, opt-in owner notifications
- **Auto-delete** on close with configurable retention

## Requirements

Struudel intentionally does not implement its own user management. Both of these
are required to run it:

- **An OpenID Connect provider** (Keycloak, Authentik, Authelia, Okta, …) — used
  to authenticate every end user. Anonymous access is never granted.
- **SCIM v2 outbound provisioning** from that provider (or any SCIM-capable
  directory) pushing to Struudel's `/scim/v2` endpoint. Groups exist only via
  SCIM — without it, polls cannot target groups.

To run the bundled stack you additionally need **Docker** and **Docker Compose v2**.
PostgreSQL 17 and Redis 7 are pinned in `compose.yaml`; the app runs on Python 3.13.

## Quick Start

1. Register a confidential OIDC client at your IdP.
   Redirect URI: `<APP_BASE_URL>/auth/callback`. Scopes: `openid profile email`.
2. Configure a SCIM v2 outbound connector at your IdP targeting
   `<APP_BASE_URL>/scim/v2` with Bearer-token authentication.
3. Configure local env and start the stack:

   ```bash
   cp .env.example .env       # fill in the REQUIRED block
   make dev-run               # app + worker + postgres + redis
   make db-upgrade            # apply migrations
   ```

The app listens on <http://localhost:5009>.

## Configuration

All settings come from environment variables. The required ones:

| Variable | Purpose |
| --- | --- |
| `DB_USER`, `DB_PASS` | Postgres credentials — used by both the app and the bundled Postgres container |
| `OIDC_DISCOVERY_URL` | `.well-known/openid-configuration` URL of your IdP |
| `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` | OIDC client credentials registered with the IdP |
| `SCIM_TOKEN` | Bearer token expected at `/scim/v2` — must match what the IdP's SCIM connector sends |
| `SECRET_KEY` | Flask session signing key — long random string, no built-in fallback. Generate via `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `SESSION_COOKIE_SECURE` | `true` behind TLS in production, `false` only for HTTP dev. Must be set explicitly — no default |

For production also set `APP_BASE_URL` to the public HTTPS URL.
See [`.env.example`](.env.example) for the full list of optional settings
(mail, timezones, Redis URLs, login button name, …).

## Container Image

Pre-built `linux/amd64` images are published to GitHub Container Registry on every
push to `main` (as `:latest`) and on every release tag (as `:X.Y.Z` and `:X.Y`):

```bash
docker pull ghcr.io/netways/struudel:latest
docker pull ghcr.io/netways/struudel:0.9.0
```

The image runs `alembic upgrade head` on start and then serves the app via Gunicorn.
Wire it into your own Compose / Kubernetes / Nomad stack with the env vars from the
Configuration table above.

## Common Commands

| Command | Purpose |
| --- | --- |
| `make dev-run` | Start the full dev stack |
| `make dev-shell` | Bash inside the app container |
| `make dev-psql` | psql against the dev database |
| `make db-upgrade` | Run pending Alembic migrations |
| `make db-migrate MSG="..."` | Generate a new migration (autogenerate) |
| `make lint` / `make format` | `ruff check` / `ruff format` |
| `make type-check` | `ty check` |
| `make css-build` | Recompile `static/css/app.css` |

## Architecture

Service signatures, voting semantics, CSRF wiring, the Alpine + HTMX + SortableJS
pattern, the Redis layout — all documented in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## License

[MIT](LICENSE) © NETWAYS GmbH
