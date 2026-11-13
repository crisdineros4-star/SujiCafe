# Authorized Owner recovery and succession

This feature is for a real, business-authorized ownership succession when the current Owner is unavailable. It is not a public Owner signup, an Admin permission or a way to skip email verification. Merely applying this code does not prepare a transfer, send an email, change an account or disable the existing Owner.

## What it does

A technical operator with local server/database access records the business authorization, creates a private database backup and sends a one-hour, single-use acceptance link to the new Owner's unused email. The successor supplies their own name, unique personal mobile number and password. Only valid acceptance changes ownership, in a single transaction.

The old account is retained as disabled `former_owner`; its name/ID and transaction references remain. Its trusted devices, login codes and reset grants are revoked. Exactly one Owner remains. Other Admin/Staff/Rider/Customer accounts, products, points, orders and settings are not deleted. Recovery events are recorded in Owner Activity log with operator, approval reference and transfer ID. Completed recovery also prevents the old configured OWNER_EMAIL/legacy Admin migration from recreating another Owner on restart.

## Before the operator begins

- Obtain authorization from the café's actual authorized representative. Record a document/ticket reference and the operator's name. The software records these details; it cannot independently determine legal ownership, verify a death certificate or prove consent.
- Stop the web application for maintenance while preparing and accepting the transfer, or arrange a controlled maintenance window with the operator. The emailed link needs the app running to be opened; restart the application after preparing it and keep ordinary store writes/DDL changes paused during the maintenance window.
- Keep the existing SECRET_KEY, private .env, database and uploaded files. Do not reset the database or run CREATE TABLE schema files on existing data.
- SMTP must work. PUBLIC_BASE_URL must be the reachable HTTPS origin. Same-machine `http://127.0.0.1:5000` is supported for local development, but that link cannot reach your computer from another person's phone.
- Use a new email that is not registered to any account. This recovery does not silently promote/overwrite an existing Customer/Admin account. The successor needs an unused personal mobile number; the former Owner's contact record is preserved.

## Terminal commands (inside the project / active virtual environment)

View the current Owner and recent transfer statuses:

```text
flask --app app owner-recovery status
```

Prepare a transfer (replace all examples with authorized details):

```text
flask --app app owner-recovery prepare --current-owner old.owner@gmail.com --new-email successor@gmail.com --operator "Authorized IT Operator" --approval-reference "AUTH-2026-001" --reason "Business-authorized ownership succession"
```

Review the displayed old/new emails and confirmation prompt. The operation then creates a database backup and emails the private link. Terminal output shows a transfer ID and private backup location, never a raw activation token or a password. Existing ownership remains unchanged until acceptance. An email-delivery/preparation error leaves access unchanged; an already created backup is retained for the operator.

The successor opens the email link, confirms the transfer and enters their own details/password. The token is in a URL fragment, which is removed by the browser and submitted in a CSRF-protected POST; it is not placed in the HTTP query/access log. An expired, cancelled, used or invalid proof cannot complete the operation. Missing or modified backup files block acceptance. After success, sign in with the new verified email/password.

Check one transfer:

```text
flask --app app owner-recovery status --transfer-id TRANSFER_ID_FROM_PREPARE
```

Cancel a pending transfer (this leaves the current Owner unchanged):

```text
flask --app app owner-recovery cancel --transfer-id TRANSFER_ID_FROM_PREPARE --operator "Authorized IT Operator" --reason "Cancellation approved by the business"
```

There is no public resend/prepare endpoint. To replace an unexpired link, cancel it in the terminal, then prepare a new transfer. Expired attempts can be replaced by a new preparation. Replaced proofs become unusable.

## After successful acceptance

Update OWNER_EMAIL in the private .env to the successor's verified email; if ADMIN_EMAIL was used as the old fallback, use the explicit new OWNER_EMAIL. Restart the application. Do not change SECRET_KEY just to transfer ownership: QR signatures and sessions depend on that secret. Retain the old account and audit/backup evidence rather than deleting transaction history.

Regular logout still retains the requested seven-day browser trust. Ownership succession explicitly revokes the former Owner's access; it is an intentional security revocation, just like deactivation/password reset.

## Backup and restore limits

Automatic backups are under `private/owner-recovery/<transfer-id>/` with restricted file permissions where the OS supports them. They contain sensitive database records/hashes and must remain outside public hosting/Git. There is no web download endpoint for them. Set appropriate Windows folder ACLs when using Windows and preserve the private directory between deployments.

SQLite uses the database backup API. MySQL uses a consistent InnoDB snapshot exported as `.sql.gz`, respecting configured TLS/connection settings. Non-InnoDB application tables are refused. The automatic snapshot is the database, not the private .env, uploaded images, payment-proof files or an offsite backup; securely preserve those separately.

Restore only under operator control, with the app stopped, into a NEW empty test/restore database first. Do not run the pre-transfer dump against live tables. A pre-transfer backup restores the previous ownership state; re-establish authorized ownership and revoke old sessions before reopening a restored system publicly. Keep backup files under the café's approved access/retention policy; applying this feature never deletes them automatically.

If both the Owner and technical operator become unavailable, the business still needs a trusted custodian/provider account, infrastructure recovery access and offsite backups. This feature does not bypass lost server/hosting access.

## Verification

See SECURITY_TEST_RESULTS.md for measured test results. Automated tests use isolated SQLite/MySQL data and mocked emails. Actual inbox delivery, authorization handling, hosting access and the café's restore procedure must be checked with its authorized operator. Never run a production succession as a demo; use a separate test database.
