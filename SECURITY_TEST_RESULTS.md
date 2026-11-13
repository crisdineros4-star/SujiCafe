# Security verification — 12 November 2026

This report describes the supplied source, not a security certification of a deployed server. No live café database, real customer inbox or real payment wallet was used. The latest evaluation-specific loyalty journey also passed on SQLite and a disposable MySQL schema; see docs/EVALUATION_ESTIMATE.md.

## Verification

- Complete SQLite regression suite: 202 tests passed. Covers current public signup verification, Owner/Admin boundaries, account management, reset, rewards, payments, workshops, QR, uploads, notifications and device activity.
- MySQL 8.4 disposable server: the 52-test security/account suite passed; four supplemental checks passed; two database-connection/security-option checks passed. After the missing-workshop repair, the four supplemental checks passed again. All test schemas were isolated with suji_test_ names and disposable credentials. After restoring seven-day trust across logout, five focused MySQL checks passed for logout, replay prevention, six/seven-day expiry, legacy-device continuity and password reset. This is not the full MySQL business regression suite.
- Browser pages: 140 route/viewport cases at 320, 375, 768 and 1440 px, with no final horizontal overflow, page JavaScript errors, unexpected HTTP failures or CSP violations. A map stylesheet initially blocked by the new policy was allowlisted and affected pages were rerun.
- Browser interactions: 20 role/viewport workspace cases passed (Products filters/edit layout, Admin invitations, Counter Sale quantity retention, profiles and notifications).
- Account forms: 24 role/viewport cases passed (field errors, first-error focus, read-only email, email-only manager invitation forms).
- Native browser CSP probe: injected inline scripts, an injected CDN script and inline event handlers were blocked while trusted navigation JavaScript ran.
- Python dependency scan: no known vulnerabilities reported for the 13 resolved application dependencies in requirements.lock. Audit output is in docs/security-dependencies.json. This is point-in-time evidence, not a guarantee about unknown or future issues.

## Fixed findings

1. Public authentication endpoints lacked shared rate limits. Added hashed-key, database-backed request/email quotas and Retry-After responses; forwarding is not trusted unless explicitly configured.
2. Device-login proofs could be reused or have their attempts reset through repeated sends. Added atomic attempts and single-use consumption, bounded sends, short resend reuse and SMTP failure rollback.
3. Logout now revokes the server-bound login session while preserving the requested seven-day device trust. An old signed-in session cannot be replayed with a retained device cookie after logout; a fresh password is required. Authentication rotates signed-session/CSRF state.
4. An earlier reset grant could survive a self-service password change/deactivation. Credential revocation now includes reset grants, devices and login codes.
5. Google sign-in lacked a per-browser challenge. Added nonce binding in addition to audience/issuer/expiry/email checks.
6. Production could start with development settings. Added fail-closed secret/HTTPS/debug/host/public-origin checks, secure-cookie/session limits, production HSTS and verified remote-MySQL TLS options.
7. Browser hardening was incomplete. Added explicit script nonces/strict-dynamic CSP, framing restrictions, permissions policy, mutation origin checks and private-response caching restrictions. Existing template/dynamic output escaping and server-side ownership checks were retained and exercised.
8. The legacy upload helper only checked an extension. It now delegates to verified decoding/re-encoding; supported formats and size/dimension bounds are enforced.
9. Fresh SQL menu seeds had lost the workshop listing and the MySQL loader split quoted semicolons. Restored the workshop product, added an existing-database repair that preserves custom workshop prices, and made SQL statement splitting quote-aware.
10. Old tests assumed immediate signup, manager-set employee details/passwords, the former reward eligibility and an exact old template count. Updated tests to prove inbox verification/approved invitations and exercise reward/debt cases using eligible dine-in orders. Existing delivery cash tests still check cash preservation and zero delivery earnings. No business eligibility rule was changed to satisfy those tests.

## Required deployment verification

Actual SMTP inbox delivery and live Google OAuth remain untested here. Verify those with your own configured accounts. Production TLS/proxy boundaries, remote-MySQL CA files/privileges, backups, disk access, monitoring and perimeter DoS controls depend on the host. Test the complete real customer-to-store-to-rider flow on the deployment before public use. The production WSGI/proxy setup is documented but was not deployed to the user's computer/server in this task.

Existing emails can be checked for signup availability by design; those endpoints are rate limited, not a promise of absolute account-enumeration resistance. CSP retains inline styles for Bootstrap/maps and trusted third-party resource dependencies. Physical uploaded-file cleanup after failed transactions/account cleanup is an operational task; applying this security update does not remove files or accounts.

The historical academic-guidelines audit is a separate, earlier report. It is not a current security or final-project compliance sign-off.

## Owner succession addition

The OwnerRecoveryService and terminal-only prepare/status/cancel commands now support authorized succession. Sixteen recovery-focused cases passed using isolated SQLite data. Fifteen MySQL recovery cases passed, and the additional backup-restore case passed on a fresh disposable MySQL database. The complete updated SQLite suite passed 202 tests. Tests cover pending-owner continuity, one active transfer, email failure rollback, invalid/expired/cancelled proofs, missing/tampered backups, failed-commit rollback, concurrent preparation/acceptance, preservation of menu/settings/history, revocation of the former Owner and prevention of legacy re-promotion on restart.

A native browser run verified the fragment-token claim and acceptance form at 320/375/768/1440 px, validation, successor login, former Owner lockout, retained history and absence of the private token from HTTP URLs. The existing employee activation and Staff login flow also passed in the browser with the same private-form security headers. Private no-referrer forms now allow opaque Origin only with same-origin browser fetch metadata AND the existing CSRF checks; cross-site/missing-CSRF requests are still rejected. See OWNER_RECOVERY_SETUP.md for the authorization, backup and maintenance requirements. Real recovery email delivery was mocked, and no live business succession was performed.
