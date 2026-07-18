# Deploying The Sterling Syndicate (always-on) on Render

This app runs locally only while your machine is on. To keep it reachable for
other users at any time, deploy it to a host. The repo ships a Render Blueprint
(`render.yaml`) that provisions everything in one shot.

## What gets created

| Service        | What it is                          | Plan |
|----------------|-------------------------------------|------|
| `sterling-db`  | PostgreSQL 16 (+ pgvector)          | free |
| `sterling-api` | FastAPI backend (Docker)            | free |
| `sterling-web` | React SPA served by nginx (Docker)  | free |

> Free-plan services sleep after ~15 min idle and cold-start on the next
> request (a few seconds). For true 24/7 with no cold starts, bump the two web
> services to a paid plan later — no code change needed.

## One-time: generate the encryption key

Render auto-generates `JWT_SECRET_KEY`, but the Fernet field-encryption key must
be created by you (it protects client data at rest). Run locally:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copy the output — you'll paste it in step 4.

## Deploy steps

1. **Sign in** at <https://dashboard.render.com> (log in with GitHub).
2. **New + → Blueprint**. Pick the `sterling-syndicate` repo. Render reads
   `render.yaml` and shows the 3 resources above. Click **Apply**.
3. Render builds the database first, then the API and web images. First build
   takes ~5–8 min.
4. **Set the two manual secrets** on the `sterling-api` service
   (Dashboard → sterling-api → Environment):
   - `FIELD_ENCRYPTION_KEY` = the Fernet key from above **(required)**
   - `OPENAI_API_KEY` = your key **(only if you use the AI drafting features)**
   Save — the service redeploys automatically.
5. When all three show **Live**, open the `sterling-web` URL
   (`https://sterling-web.onrender.com`). Sign up and you're in.

## How the wiring works (no manual URLs needed)

- `DATABASE_URL` is injected from `sterling-db`. The backend auto-rewrites the
  `postgres://` scheme to the `postgresql+psycopg://` driver form it needs.
- `CORS_ORIGINS` is set from the `sterling-web` host, and `VITE_API_URL` from the
  `sterling-api` host. Render provides bare hostnames; both the backend (CORS)
  and frontend (fetch base) prepend `https://` automatically.
- Migrations (`alembic upgrade head`) run on every backend boot, so the schema
  and the pgvector extension are created before traffic is served.

## Not deployed: the DinD execution sandbox

`docker-compose.yml` includes a Docker-in-Docker service for the Execution
Agent's untrusted-code sandbox. Render has no privileged DinD, so it's excluded
here. The whole product except that one feature runs normally, and
`SANDBOX_ALLOW_SUBPROCESS_FALLBACK` stays `false` so no untrusted code ever runs
directly on the host. To use that feature, deploy `docker-compose.yml` on a VPS
you control instead.

## Custom domain (optional)

Dashboard → sterling-web → Settings → Custom Domains. Add your domain, create the
shown CNAME at your registrar. Then add that domain to the API's `CORS_ORIGINS`
(comma-separated) so the browser calls are allowed.

