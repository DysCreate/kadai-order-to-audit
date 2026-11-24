# Deploying Kadai: Cloudflare + Render + Neon

This is the managed, free-tier deployment:

| Piece | Where | Job |
|-------|-------|-----|
| React app + `/api` forwarder | Cloudflare Workers (static assets) | What users open in the browser |
| Django API | Render (free web service, Docker) | Business logic and PDFs |
| PostgreSQL | Neon (free) | Data |

The self-hosted Docker Compose path in `README.md` still works and is
independent of this guide.

Deploy in this order: **Neon → Render → Cloudflare**. The Worker needs the
Render URL, and Render needs the Neon connection string.

---

## 1. Neon (database)

1. Create a project at <https://console.neon.tech> (region closest to your
   Render region; `singapore` is used in `render.yaml`).
2. Copy the **pooled** connection string. It contains `-pooler` in the host,
   for example:

   ```
   postgresql://kadai_owner:password@ep-cool-name-123456-pooler.ap-southeast-1.aws.neon.tech/kadai?sslmode=require
   ```

3. Keep `sslmode=require`. Production settings also disable prepared statements
   (`prepare_threshold=None`), which is required through a transaction pooler,
   and enable connection health checks so a suspended Neon compute reconnects
   cleanly.

Create the database name you want (the default `neondb` works); use whatever
appears in the connection string. No tables are created yet — Render migrations
do that on first boot.

## 2. Render (Django API)

The repository contains `render.yaml`, so a Blueprint deploy configures the
service, Docker build, health check and non-secret environment variables.

1. Push the repository to GitHub.
2. In Render: **New → Blueprint**, pick the repository, and apply
   `render.yaml`.
   - If you prefer a manual service: **New → Web Service**, runtime **Docker**,
     root directory `backend`, Dockerfile `backend/Dockerfile`, health check
     path `/api/health/`, plan **Free**.
3. Set these environment variables when prompted:

   | Variable | Value |
   |----------|-------|
   | `DATABASE_URL` | Neon **pooled** connection string from step 1 |
   | `ALLOWED_HOSTS` | Your Render hostname, e.g. `kadai-api.onrender.com` |
   | `CSRF_TRUSTED_ORIGINS` | The Worker URL, e.g. `https://kadai.example.workers.dev` (add a custom domain later too) |
   | `CORS_ALLOWED_ORIGINS` | Leave empty: the SPA and API share the Worker origin |
   | `TRUSTED_PROXY_SECRET` | A long random value, identical on Render and the Worker (see step 3) |

   `render.yaml` already sets `SECRET_KEY` (generated), `RUN_MIGRATIONS=true`,
   `GUNICORN_WORKERS=1`, `GUNICORN_THREADS=4` and
   `DJANGO_SETTINGS_MODULE=config.settings.production`.

   `RENDER_EXTERNAL_HOSTNAME` is injected by Render and appended to
   `ALLOWED_HOSTS` automatically.

4. Wait for the first deploy. The container runs `migrate --noinput` and then
   gunicorn bound to Render's `$PORT`. The build runs `collectstatic` for
   WhiteNoise.
5. Confirm the health endpoint:

   ```bash
   curl -fsS https://kadai-api.onrender.com/api/health/
   ```

6. Create the first owner. A production database has **no demo users** and the
   seed command is disabled. From the Render **Shell**:

   ```bash
   ADMIN_USERNAME=owner \
   ADMIN_PASSWORD='a-long-unique-password' \
   ADMIN_EMAIL='owner@example.com' \
   python manage.py bootstrap_admin
   ```

   The command validates the password with Django's validators and creates an
   owner superuser. Re-running it is a no-op; `--update-password` promotes an
   existing user and resets the password. If the Shell is unavailable, run the
   same command from a machine that can reach Neon:

   ```bash
   cd backend
   DATABASE_URL='postgresql://...neon...' \
   DJANGO_SETTINGS_MODULE=config.settings.production \
   ADMIN_USERNAME=owner ADMIN_PASSWORD='...' \
   python manage.py bootstrap_admin
   ```

   Django admin remains available at
   `https://kadai-api.onrender.com/admin/` for owner/master-data work.

### Free-plan behavior

- The service sleeps after ~15 minutes without traffic. The first request after
  that can take 30–60 seconds; the SPA should be opened once before a shift.
- Free instances have no persistent disk. Kadai stores business data in
  PostgreSQL, not on local disk, so this is safe; the login throttle's file
  cache resets when the instance restarts (it still enforces limits while
  running).
- `GUNICORN_WORKERS=1` with 4 threads keeps memory inside the free instance and
  suits this workload. The login throttle uses a file cache shared by processes
  on the same host; if you later run multiple Render instances, point `CACHES`
  at a shared cache so the limits stay global.
- Render terminates TLS; leave `SECURE_SSL_REDIRECT=true`. The Worker forwards
  `X-Forwarded-Proto: https`.

## 3. Cloudflare (SPA + API forwarder)

The frontend ships a Worker (`frontend/worker/index.ts`) and
`frontend/wrangler.jsonc`:

- Static assets in `frontend/dist` are served by Cloudflare.
- Only `/api` and `/api/*` run the Worker; everything else is static assets, so
  the Worker is never an open proxy.
- The Worker sets `X-Real-IP` from `CF-Connecting-IP` and proves it with
  `X-Kadai-Proxy-Secret`, so Django's login throttle sees each visitor
  separately and cannot be fooled by calling Render directly.
- API responses are marked `Cache-Control: no-store`; the SPA HTML and hashed
  assets get CSP and security headers from `frontend/public/_headers`.

Set the shared proxy secret. It lets Django trust the Worker's `X-Real-IP`
while ignoring a forged header on a direct request to the Render hostname:

```bash
# Generate once and use the same value in Render's TRUSTED_PROXY_SECRET.
openssl rand -base64 32
```

Deploy:

```bash
cd frontend
npm ci
# Set the Render URL in wrangler.jsonc -> vars.API_ORIGIN (no trailing slash)
# before deploying; edit the file rather than passing --var so later deploys
# keep the same origin.
npx wrangler login   # first time only
npx wrangler secret put TRUSTED_PROXY_SECRET   # paste the shared value
npx wrangler deploy
```

Wrangler prints the `https://<name>.<subdomain>.workers.dev` URL. Put that
origin in Render's `CSRF_TRUSTED_ORIGINS` and redeploy the Render service.

Optional custom domain: add it to the Worker in Cloudflare, then append it to
`CSRF_TRUSTED_ORIGINS` (and to `ALLOWED_HOSTS` only if it points directly at
Render, which it should not).

### Why both `_headers` and worker headers

Cloudflare's `_headers` file applies to static-asset responses only. Responses
produced by the Worker (the `/api` proxy) therefore set their own
`X-Content-Type-Options` and `Cache-Control` in `worker/index.ts`.

## 4. Smoke test

Run these after the first deploy and after every production change:

```bash
BASE=https://kadai.<subdomain>.workers.dev

# SPA loads with security headers
curl -fsSI "$BASE/" | grep -i -E 'content-security-policy|strict-transport|x-frame'

# API health through the Worker
curl -fsS "$BASE/api/health/"

# Unknown API paths are JSON 404s, not an open proxy
curl -s -o /dev/null -w '%{http_code}\n' "$BASE/api/does-not-exist/"

# Unauthenticated data access is refused
curl -s -o /dev/null -w '%{http_code}\n' "$BASE/api/orders/"
```

Then in the browser:

1. Log in as the owner created above.
2. Create a customer, item and order; confirm the PDF download works
   (WeasyPrint is installed in the image).
3. Log in as a salesman and confirm customer scoping still limits the catalog
   and orders.
4. Enter a wrong password repeatedly and confirm the throttle responds with
   HTTP 429 before locking the account.
5. Check Render logs for 5xx errors and Cloudflare → Workers → Logs for proxy
   failures.

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| Render deploy fails with `ImproperlyConfigured` | Missing `SECRET_KEY`, `ALLOWED_HOSTS` or `DATABASE_URL`; the container refuses to start without them |
| `DisallowedHost` | `ALLOWED_HOSTS` lacks the Render hostname (usually auto-injected, but set it explicitly) |
| Login returns 403 CSRF | `CSRF_TRUSTED_ORIGINS` does not include the exact Worker/custom-domain origin (scheme included) |
| `502 The API is unavailable` | Render is cold-starting or the service is down; check Render logs and `API_ORIGIN` |
| Login throttling never triggers per user | `X-Real-IP` is not reaching Django; confirm requests go through the Worker, not directly to Render |
| Login throttling treats everyone as one client | `TRUSTED_PROXY_SECRET` differs between the Worker and Render, so Django falls back to `REMOTE_ADDR`; set the same value in both |
| All assets 404 after deploy | `npm run build` was not run before `wrangler deploy`; Wrangler uploads `frontend/dist` |
| PDF endpoint 500 | WeasyPrint system libraries are missing; use the repository Dockerfile, which installs Pango/HarfBuzz and fonts |
