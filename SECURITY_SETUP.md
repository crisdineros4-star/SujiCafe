# Security hardening and deployment

This release hardens the application; it is not a guarantee against every vulnerability. It does not delete accounts, reset the database or send test emails.

## Applying this release

Extract the complete ZIP to a new directory, retain the existing private .env/database/uploads, and install the audited dependency versions:

```
python -m pip install -r requirements.lock
```

Restart Flask, then hard-refresh the browser. The security_rate_limits table is created automatically on startup, together with additive application tables. Do not import CREATE TABLE schemas into an existing database. Existing accounts/menu/settings remain.

Local testing: APP_ENV=development, HTTPS=0, FLASK_DEBUG=0. Keep a persistent random SECRET_KEY in your private .env. To generate one locally: `python -c "import secrets; print(secrets.token_hex(32))"`. Store it privately; do not paste it into chat or commit it. Changing it invalidates signed sessions and order/member QR signatures, so do not rotate it casually on an existing store.

## Changes

- Shared database-backed rate limits for login, signup, availability checks, Google login, reset/verification and profile changes. IP limits survive a new browser cookie and are shared between application workers. Email lookup limits use canonical email keys; rate bucket identifiers are keyed hashes, not stored addresses. Expect a 429 response and Retry-After when limits are reached.
- Atomic code attempt caps and single-use login proofs. Re-entering a password within one minute reuses the existing code instead of sending another. Failed SMTP sends preserve the previous proof; exhausted attempts cannot be reset by repeatedly logging in.
- Fresh CSRF/session state after authentication; authenticated sessions have a 12-hour maximum signed lifetime. Device verification still expires after seven days without foreground activity. Background polling does not extend device inactivity.
- Logout ends the server-bound login session and clears signed-in browser state, while keeping device trust for seven days since last authenticated foreground activity. A correct password on the same active trusted browser signs in without a new email code. Seven idle days, a new browser, cleared trust cookies, password change/reset or account deactivation require verification again. Already signed-in sessions from before this update may need a fresh password once; valid seven-day device trust is retained.
- Password changes and deactivation revoke old device tokens, login codes AND outstanding password-reset grants. New-device login, self password changes and password reset preserve intended role permissions.
- Login failures use a generic message, and successful/failed logins/logout are recorded in the Owner Activity log. No entered passwords, raw device tokens, OTPs or password hashes are written to those events.
- Google tokens are checked for audience/issuer/expiry/verified email and a per-browser nonce challenge.
- All mutation forms require CSRF and reject cross-origin/cross-site submissions. Role and ownership checks remain server authoritative. JSON APIs do not grant cross-origin access.
- CSP uses nonces and strict-dynamic for scripts, blocks inline event handlers and plug-ins, and limits external resources. Required styles still allow inline CSS for Bootstrap/maps. Receipts print through an external script. Frame embedding is denied. Camera/geolocation are same-origin only; microphone/payment browser APIs are disabled. Responses carrying private information are not cached.
- Verified uploads decode and re-encode only JPEG/PNG/WebP, reject oversized/malformed/other formats and use random filenames. Payment proofs stay outside static/ behind ownership/role checks. Legacy save_image callers use the same checks.
- Fresh SQL schemas retain all 58 catalog entries PLUS the required cake workshop listing. Existing-database menu updates only restore a missing workshop listing. The MySQL schema loader respects semicolons inside quoted descriptions.

## Required production configuration

Set these in your PRIVATE .env, using your actual website origin:

```
APP_ENV=production
HTTPS=1
FLASK_DEBUG=0
DEV_PRINT_OTP=0
SECRET_KEY=<your private random secret, at least 32 characters>
PUBLIC_BASE_URL=https://your-actual-domain.example
ALLOWED_HOSTS=your-actual-domain.example
TRUSTED_PROXY_HOPS=0
```

Production startup refuses missing/placeholder secrets, insecure public origins, missing HTTPS, debug mode or OTP printing. Hostnames are allowlisted; forwarded Host headers are not trusted. HTTPS requests receive HSTS (one year); plain HTTP application requests are rejected. A correctly configured TLS proxy must redirect HTTP before it reaches the app.

Use a production WSGI server, not `python app.py` exposed to the internet. For example, on a host with one local HTTPS reverse proxy:

```
waitress-serve --listen=127.0.0.1:8000 --trusted-proxy=127.0.0.1 --trusted-proxy-count=1 --trusted-proxy-headers="x-forwarded-for x-forwarded-proto" app:app
```

The proxy must connect locally, strip/replace client-supplied forwarded headers, set X-Forwarded-Proto=https, set a permitted Host, and prevent direct public access to the backend port. Waitress handles the trusted proxy in this example; keep TRUSTED_PROXY_HOPS=0 to avoid a second forwarding layer. For a different WSGI server without its own forwarding handling, TRUSTED_PROXY_HOPS=1 enables exactly one ProxyFix hop, ONLY after the same network restrictions are in place. Never trust arbitrary client IP forwarding or expose the debug server.

Use a database-specific MySQL account, not the server root account. For a remote MySQL host in production, set MYSQL_SSL_CA to a trusted CA file; the application requires certificate and hostname verification and bounded connection/read/write timeouts. Local loopback MySQL can use an empty CA setting. App startup currently needs its schema CREATE/ALTER/index permissions for migrations; isolate those privileges to this database. Restrict DB network access, protect disk/backups, configure SMTP with TLS/App Passwords, and keep .env, DB exports and payment proofs out of Git. Configure request/body/connection limits at the proxy. The app's rate limits do not replace network-level DoS protection or deployment monitoring.

## Verification and limits

See SECURITY_TEST_RESULTS.md for measured results and outstanding findings. Automated mail uses mocks; actual inbox delivery, live Google sign-in, TLS/proxy correctness, database privileges, backups and production traffic are environment-dependent and must be verified on the deployed host. Email availability checks intentionally provide registration feedback and are rate limited; do not describe them as anonymous or resistant to all account enumeration. The separate historical guidelines audit is not a current security certification.
