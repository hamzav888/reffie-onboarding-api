# Deployment Guide

## How deploys work

Every push to `main` triggers the GitHub Actions workflow (`.github/workflows/deploy.yml`):

1. **CI job** — runs lint, format check, pyright, and pytest in the `reffie-onboarding-api/` directory.
2. **Deploy job** — runs only if CI passes AND the event is a push to `main` (not a PR). Calls `railway up --ci --service reffie-onboarding-api` which triggers a Nixpacks build on Railway and applies the new image.

PRs to `main` run CI only — no deploy.

## Required GitHub repository secrets

Add these in **Settings → Secrets and variables → Actions**:

| Secret | Description |
|---|---|
| `RAILWAY_TOKEN` | Project-scoped Railway token. Generate in Railway → Project → Settings → Tokens. |
| `RAILWAY_PROJECT_ID` | Railway project ID (visible in the project URL). Required if using an account-level token instead of a project-scoped token. |

## Required Railway environment variables

Set these in **Railway → Service → Variables** before the first deploy:

| Variable | Example | Notes |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@host:5432/db` | Supabase connection string with asyncpg driver prefix |
| `GOOGLE_CLIENT_ID` | `12345.apps.googleusercontent.com` | OAuth client ID for JWT auth |
| `HUBSPOT_TOKEN` | `pat-na1-...` | HubSpot private app token |
| `CORS_ORIGINS` | `https://reffie-onboarding.vercel.app` | Comma-separated; include all frontend origins |
| `HUBSPOT_WEBHOOK_SECRET` | `abc123` | HubSpot app client secret for webhook HMAC verification |
| `HUBSPOT_CLOSED_WON_STAGE_IDS` | `closedwon,8b76c620-abc` | Comma-separated pipeline stage IDs that represent Closed Won |

`JWT_SECRET` does not need to be set — Google JWT verification uses `GOOGLE_CLIENT_ID` and the Google public key endpoint.

## Checking deploy status

- **GitHub Actions tab** — shows CI and deploy job logs for each push.
- **Railway dashboard** — shows build logs, deploy status, and service health.
- **Health endpoint** — `GET /health` returns `{"status": "ok"}` when the service is up.

## First-deploy gotchas

**Service not yet provisioned**: If the Railway service named `reffie-onboarding-api` does not exist yet, `railway up` auto-provisions it on first run. The build may take 2–3 minutes longer than subsequent deploys.

**Port binding**: Railway injects `$PORT` at runtime. The start command binds uvicorn to `$PORT` — do not hardcode a port. Railway's health check hits `/health` to confirm the service is listening.

**Migration failures**: The start command runs `alembic upgrade head` before uvicorn starts. If a migration fails (bad SQL, missing dependency), the deploy is rolled back and the previous version stays live. Fix the migration, push again.

**Nixpacks uv detection**: `nixpacks.toml` is present to explicitly install uv via the install script. If Railway's Nixpacks version auto-detects uv, the explicit config is harmless but redundant.
