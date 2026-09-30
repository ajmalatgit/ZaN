# Production deployment

## Environment configuration

Use `.env.example` as a reference for the required settings. For production,
configure the variables in the deployment platform's secret/environment
settings (or a protected `.env` file). Do not commit `.env`.

For local HTTP development, set `DEBUG=True`, use `ALLOWED_HOSTS=localhost,127.0.0.1`,
leave `DATABASE_URL` empty to use SQLite, and disable the secure cookie and
redirect flags. These local-only settings must not be used in production.

Generate a unique Django secret key and set it as `SECRET_KEY`. The application
requires at least 50 characters and rejects Django's insecure development key.
Set `DEBUG=False`, a comma-separated `ALLOWED_HOSTS` list containing the
production hostnames, and `CSRF_TRUSTED_ORIGINS` containing their full HTTPS
origins.

Set `DATABASE_URL` to the production database connection string. PostgreSQL
URLs are supported; URL-encode special characters in credentials. If it is
omitted in development, the application uses local SQLite. With `DEBUG=False`,
production startup requires `DATABASE_URL`, preventing an accidental
deployment against a local SQLite file.

Set Razorpay API credentials and the separate webhook signing secret using the
deployment platform's secret store. Rotate any credentials previously exposed
in chat or source-controlled files.

With `DEBUG=False`, secure CSRF/session cookies and HTTPS redirection default to
enabled and cannot be disabled by environment overrides. For local HTTP-only
development, set `DEBUG=True`; never use debug mode in production.

Set `SECURE_HSTS_SECONDS=31536000` only after confirming the complete site is
served over HTTPS. Do not enable HSTS subdomains or preload unless every
subdomain is also permanently HTTPS-capable; those options are off by default.

## Deploy checks

From the project root, apply migrations, collect static assets, and run Django's
deployment checks before serving traffic:

```powershell
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py check --deploy
```

Serve the application behind an HTTPS-terminating reverse proxy and ensure
HTTP traffic is redirected to HTTPS. Configure the platform to pass the
correct host and CSRF trusted origins. If TLS terminates at a trusted proxy,
set `TRUST_PROXY_SSL_HEADER=True` only when the proxy replaces the
`X-Forwarded-Proto` header and the application cannot be reached directly by
untrusted clients; otherwise HTTPS redirection can be spoofed or loop.
Do not expose the development server to the public internet.
