# Production deployment

## Free Render + PostgreSQL + Cloudinary deployment

The project is configured for a Render Python web service, PostgreSQL, WhiteNoise
static assets, and Cloudinary-hosted uploads. Free-tier availability, quotas,
sleep behavior, and database retention can change; confirm current plan limits
with each provider before putting important data on a free service.

### 1. Create the managed services

1. Create a PostgreSQL database with Render or another managed PostgreSQL
   provider. Copy its connection URL; use Render's internal URL for a Render
   service in the same region, or the provider's externally accessible URL
   (including its required TLS parameters) otherwise.
2. Create a Cloudinary account and copy its cloud name, API key, and API secret.
   These credentials are required in production because an ephemeral web
   service filesystem is not suitable for user/product uploads.
3. Create a Render **Web Service** from this repository. Set the root directory
   to the repository root, runtime to Python, build command to `bash build.sh`,
   and configure the start command from the checked-in `Procfile`:

   ```shell
   python manage.py migrate --noinput && gunicorn core.wsgi:application --bind 0.0.0.0:$PORT
   ```

The checked-in build script installs `requirements.txt` and runs
`collectstatic`. Migrations run before Gunicorn starts, so the application does
not serve traffic against an unapplied schema.

### 2. Configure Render environment variables

Copy the required names from `.env.example` into the Render service's
Environment settings. Use actual values in the provider dashboard, never in
source control:

```text
SECRET_KEY=<new randomly generated Django key, at least 50 characters>
DEBUG=False
ALLOWED_HOSTS=<your-service>.onrender.com
CSRF_TRUSTED_ORIGINS=https://<your-service>.onrender.com
DATABASE_URL=<managed PostgreSQL connection URL>
CLOUDINARY_CLOUD_NAME=<Cloudinary cloud name>
CLOUDINARY_API_KEY=<Cloudinary API key>
CLOUDINARY_API_SECRET=<Cloudinary API secret>
TRUST_PROXY_SSL_HEADER=True
```

Generate a key locally with:

```shell
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```
Add a custom domain to both `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` if you
use one. `TRUST_PROXY_SSL_HEADER=True` is appropriate for Render's trusted TLS
proxy; only enable it where the platform controls/overwrites
`X-Forwarded-Proto` and clients cannot bypass that proxy.

Razorpay variables can remain empty while testing browsing, authentication,
uploads, reviews, and persistence. Online payment will remain unavailable until
valid Razorpay API and webhook credentials are configured. `SECURE_SSL_REDIRECT`,
`CSRF_COOKIE_SECURE`, and `SESSION_COOKIE_SECURE` are forced on when
`DEBUG=False`. Keep `SECURE_HSTS_SECONDS=0` during initial verification; only
enable HSTS after HTTPS and all required subdomains are confirmed.

### 3. Deploy and verify

After the first deployment:

1. Open the public HTTPS URL and confirm the home page, catalog, product detail,
   navigation, registration, and login pages load.
2. Create a test buyer and verify data survives a service restart/redeploy.
3. Upload a profile photo and product/review media, then verify they still load
   after restarting the web service. Media uploads should resolve to Cloudinary,
   not `/media/` on the Render instance.
4. Check Render logs for successful migrations and static collection. In a
   Render shell (or locally using the same production environment), run:

```shell
python manage.py check --deploy
python manage.py showmigrations
```

`build.sh` uses `collectstatic --noinput`; WhiteNoise serves the resulting
compressed, content-hashed static files. Cloudinary backs Django's default file
storage only when all three Cloudinary variables are present. Production startup
fails clearly when persistent media credentials or `DATABASE_URL` are missing;
local development continues to use SQLite and local media when `DEBUG=True`.

Do not use Django's development server in production. Take backups before
database changes, and for multi-instance/zero-downtime deployments run
migrations as a single release/pre-deploy step rather than concurrently in
every web process.

## Local development

Use `.env.example` as a reference and a local, ignored `.env` file. For local
HTTP development set `DEBUG=True`, use `ALLOWED_HOSTS=localhost,127.0.0.1`,
leave `DATABASE_URL` empty to use SQLite, and leave Cloudinary credentials empty
to store media under the ignored local `media/` directory. Do not use these
local-only settings in production.

Run targeted checks before deployment:

```shell
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py check --deploy
```
