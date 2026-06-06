# Deployment

Production split:

| Layer | Provider | What it gives us |
|---|---|---|
| Backend API | **Render** (free Docker web service) | builds [`backend/Dockerfile`](./backend/Dockerfile), runs [`backend/start.sh`](./backend/start.sh) |
| Postgres | **Supabase** (free) | pooled DSN on port 6543 (pgbouncer, transaction mode) |
| Redis | **Upstash** (free) | TLS `rediss://` URL |
| Frontend | **Vercel** | static Vite build, see [`frontend/vercel.json`](./frontend/vercel.json) |

No secrets live in the repo. Every value goes into each platform's env-var UI.

The Render Blueprint is checked in at [`render.yaml`](./render.yaml). The
old Railway config at [`backend/railway.toml`](./backend/railway.toml) is kept
for reference only — Render is the production target.

---

## 1. Supabase (Postgres)

1. <https://supabase.com/dashboard> → **New project**. Pick a region close to
   Render's region (Render free is Oregon → pick `us-west`).
2. Wait for the project to provision (~2 min).
3. **Settings → Database → Connection Pooling** → set mode to **Transaction**.
   Copy the **Connection string** under that pooler — it looks like:

   ```
   postgresql://postgres.<PROJECT>:<PASSWORD>@aws-0-<REGION>.pooler.supabase.com:6543/postgres
   ```

   That **pooled** URL on port **6543** is the one you want. Do **not** use the
   direct connection on 5432 — Render free only allows ~5 DB connections per
   service, and Supabase free caps direct connections too. The pooler is the
   only path that survives a burst.

4. Save that string as the **`DATABASE_URL`** secret you'll paste into Render.

The backend handles the rest automatically — [`backend/database.py`](./backend/database.py)
rewrites `postgresql://` → `postgresql+asyncpg://`, strips any `?sslmode=` query
param (asyncpg rejects libpq-style params), and passes `ssl=True` plus
`statement_cache_size=0` / `prepared_statement_cache_size=0` via
`connect_args` — that last pair is mandatory under pgbouncer transaction mode
or you'll get `prepared statement "__asyncpg_stmt_X__" already exists` under
load. `pool_size=5`, `max_overflow=2` keeps us inside Render's 512 MB.

---

## 2. Upstash (Redis)

1. <https://console.upstash.com/> → **Create Database**. Pick the same region
   as Supabase + Render.
2. Default settings are fine. Copy the **`UPSTASH_REDIS_REST_URL`** *and* the
   regular **`redis://`** URL — what you want is the **`rediss://`** TLS URL
   shown under **Endpoint → Redis client** (looks like
   `rediss://default:<TOKEN>@<HOST>.upstash.io:6379`).
3. Save that as the **`REDIS_URL`** secret for Render.

The backend's two Redis consumers both accept `rediss://` natively:

- [`backend/app/limiter.py`](./backend/app/limiter.py) — `slowapi`'s
  `storage_uri` reads `settings.REDIS_URL` verbatim.
- [`backend/app/routers/health.py`](./backend/app/routers/health.py) —
  `redis.asyncio.from_url(settings.REDIS_URL, ...)`.

Neither hardcodes `redis://`, so TLS works without code changes.

---

## 3. Render (backend)

1. <https://dashboard.render.com/new/blueprint> → connect this repo. Render
   reads [`render.yaml`](./render.yaml) and proposes one web service
   (`vigil-api`) backed by `backend/Dockerfile`.
2. When prompted, set the secrets that are marked `sync: false` in the
   blueprint:

   | Variable | Source | Notes |
   |---|---|---|
   | `SECRET_KEY` | `openssl rand -hex 32` | Required. Boot fails if weak when `DEBUG=false`. |
   | `DATABASE_URL` | Supabase pooled DSN (step 1) | Must be the port-6543 pooler URL. |
   | `REDIS_URL` | Upstash `rediss://` URL (step 2) | TLS-only — `redis://` will silently fail to connect. |
   | `ANTHROPIC_API_KEY` | Anthropic console | Optional. Used by the SDK e2e test. |
   | `OPENAI_API_KEY` | OpenAI console | Optional. If unset, toxicity checks are skipped. |
   | `FRONTEND_URL` | *fill in after Vercel deploy* | Comma-separated list supported (`https://prod.app,https://preview.app`). |
   | `SENTRY_DSN` | Sentry project | Leave blank to disable Sentry entirely. |

   The non-secret values (`ENVIRONMENT=production`, `DEBUG=false`,
   `SPACY_MODEL=en_core_web_sm`) come from `render.yaml` directly.

3. **Apply Blueprint.** First deploy builds the Docker image, runs
   `alembic upgrade head` via `start.sh`, and serves uvicorn on `$PORT`.
4. Render generates `https://vigil-api-<hash>.onrender.com`. Smoke-test:

   ```bash
   curl https://vigil-api-<hash>.onrender.com/health
   ```

   Expect `{"status":"ok","services":{"database":"up","redis":"up",...}}`.

> **Memory note.** Presidio + spaCy load *lazily* on the first PII check
> ([`backend/services/safety_checker.py`](./backend/services/safety_checker.py)).
> Idle process memory stays well under 512 MB; the first flagged background
> task is slower because it triggers the model load, then subsequent checks
> are fast.

---

## 4. Vercel (frontend)

1. <https://vercel.com/new> → **Import Git Repository** → pick this repo.
2. Set **Root Directory** to `frontend`. Vercel reads
   [`frontend/vercel.json`](./frontend/vercel.json) for the framework
   (`vite`), build command (`npm run build`), output (`dist`), and the SPA
   rewrite for React Router.
3. **Environment Variables** → add:

   | Variable | Value |
   |---|---|
   | `VITE_API_URL` | `https://vigil-api-<hash>.onrender.com/api` |

   Note the `/api` suffix — `client.ts` does not prepend it.

4. **Deploy.** Copy the resulting `https://<project>.vercel.app` URL.

---

## 5. Wire CORS back to Render

Once Vercel has a URL:

1. Render → `vigil-api` service → **Environment** → set `FRONTEND_URL` to
   the Vercel URL. Comma-separated origins are supported:

   ```
   FRONTEND_URL=https://your-app.vercel.app,https://your-app-git-main.vercel.app
   ```

2. Render redeploys on the variable change. Verify by registering an
   account at `https://your-app.vercel.app/register` — no CORS errors in
   devtools.

[`backend/app/main.py`](./backend/app/main.py) parses the list with a
trailing-slash strip; both production and preview Vercel URLs work.

---

## 6. Keep-warm

Render free spins web services down after **15 min idle**. Supabase free
pauses the project after **7 days no activity**. The `/health` endpoint
solves both at once — its `SELECT 1` ([`backend/app/routers/health.py`](./backend/app/routers/health.py))
counts as Supabase DB activity, and the HTTP hit keeps the Render service
warm. One pinger does the job:

- **UptimeRobot** (recommended, simplest): free monitor, 5-minute interval,
  HTTP GET against `https://vigil-api-<hash>.onrender.com/health`.
- **GitHub Actions cron** (alternative, lives in this repo):

  ```yaml
  # .github/workflows/keep-warm.yml
  on:
    schedule:
      - cron: "*/10 * * * *"   # every 10 min
  jobs:
    ping:
      runs-on: ubuntu-latest
      steps:
        - run: curl -fsS https://vigil-api-<hash>.onrender.com/health
  ```

The DB round-trip in `_check_database()` is **intentional** — a comment in
[`health.py`](./backend/app/routers/health.py) calls this out so it doesn't
get "optimized" into a no-op later.

---

## 7. Post-deploy

### Seed demo data

Render → `vigil-api` → **Shell** → run:

```bash
python seeds/demo_data.py --reset
```

This wipes any prior `admin@vigil.demo`-owned rows and seeds 2 users, 5
models, 100 audit logs, and 10 safety flags. Output:

```
Seeded: 2 users, 5 models, 100 logs, 10 flags. Login: admin@vigil.demo
```

### Promote a real admin

`/auth/register` always creates a `viewer`. From the Render shell:

```bash
python - <<'PY'
import asyncio
from sqlalchemy import update
from database import AsyncSessionLocal
from models import User

async def main():
    async with AsyncSessionLocal() as db:
        await db.execute(update(User).where(User.email=="you@example.com").values(role="admin"))
        await db.commit()
asyncio.run(main())
PY
```

### Rolling deploys

- Migrations apply on every boot via `start.sh`. A bad Alembic revision
  fails `/health`, Render keeps the old container, and the deploy is
  effectively rolled back.
- Rotating `SECRET_KEY` invalidates every issued JWT (access + refresh).
  Plan a forced re-login window.

---

## Sanity checklist

After all four platforms are green:

- [ ] `GET https://<backend>/health` returns `{"status":"ok",...}` with
      `database: "up"` and `redis: "up"`
- [ ] `GET https://<backend>/docs` loads Swagger UI
- [ ] `https://<frontend>` loads the login page and `/register` works
- [ ] Browser devtools show no CORS errors against `<backend>/api/*`
- [ ] Keep-warm pinger configured (UptimeRobot or GH Actions cron)
- [ ] Sentry receives a test event (if `SENTRY_DSN` is set)
