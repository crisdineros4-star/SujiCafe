> Security release: read SECURITY_SETUP.md before replacing files or deploying. Use requirements.lock for the audited dependency versions. This release never deletes accounts or resets your database.

# Suji Café web application

Flask/Python, HTML5/CSS3, Bootstrap and JavaScript, with MySQL as the required deployment/submission database. SQLite is available for isolated development/testing; it is not a substitute for the course's MySQL requirement.

The app includes public café/menu pages, verified customer signup, device-aware login, orders, workshops, item rewards, customer profiles, and Owner/Admin/Staff/Rider workspaces. GCash is manually reviewed against the store wallet; the app does not automatically move money or operate a payment gateway.

## Run locally

Use Python 3.11+ and MySQL Server 8.x. MySQL Workbench is a client for the server.

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Create a MySQL database named suji_cafe (or your configured MYSQL_DATABASE), then fill the private .env:

- DB_BACKEND=mysql, MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD and MYSQL_DATABASE.
- A persistent random SECRET_KEY.
- OWNER_EMAIL for the actual local owner bootstrap account.
- SMTP/Gmail sender settings, including a Google App Password when using Gmail.
- PUBLIC_BASE_URL: the actual reachable HTTPS origin used in employee invitation links. For same-computer development only, http://127.0.0.1:5000 is supported.

Never commit .env, real databases, payment proofs or credentials.

```powershell
flask --app app create-owner
flask --app app check-setup
python app.py
```

Open http://127.0.0.1:5000. Initial tables and additive migrations are applied at startup. The MySQL user needs the corresponding CREATE/ALTER permissions. For an additional Admin, the Owner sends an email invitation from the Owner workspace. Admins must activate their invitation before access. The create-admin CLI does not bypass this verification.

Keep Python modules, templates, data/ and static/ together. Before updates, back up the existing source/database and retain the private .env and existing uploads. Apply matching versions of core.py, commerce.py, auth.py and feature modules together.

## Accounts

- Public signup creates only a Customer, after a code proves access to the submitted email.
- Personal/contact signup fields and birthday selections survive reloads in that tab's sessionStorage. Passwords and confirmation are excluded and cleared on reload/restoration. A successful verified registration clears the draft.
- Owner/Admin invite Staff and Riders by email; Owner also invites Admins through the verified invitation flow. These accounts remain Pending activation until the employee opens the expiring link and chooses a private password. The manager does not set an employee's password.
- Invitation links last 24 hours. Resend replaces the old link; cancellation blocks pending activation. Existing active accounts remain usable.
- Only Owner can create Admin accounts. Pending employees cannot bypass activation through Google sign-in, password reset, sessions or rider assignment.
- Email-code and device verification, lockouts, protected pages and POST logout remain server-enforced.

Read [employee invitation setup](EMPLOYEE_INVITATIONS_SETUP.md) and [email verification setup](EMAIL_VERIFICATION_SETUP.md). Product/domain rules, reward policy and financial actions must remain consistent with the actual café's approved requirements.

## Current operations improvements

Read [operations improvements](OPERATIONS_IMPROVEMENTS.md) for the redesigned product manager, Staff live counter search, per-role account settings, employee deactivation and customer in-app notifications. The guidelines review is a separate later step.

## Architecture

Domain entities are in domain.py. Repositories encapsulate database operations; services coordinate validated transactions. Email delivery is implemented with smtplib. SQL uses parameter binding, and routes enforce permissions, CSRF and validation.

[Setup](docs/SETUP.md) · [Architecture](docs/ARCHITECTURE.md) · [Roles](docs/ROLES.md) · [Transactions](docs/TRANSACTIONS_AND_CALENDAR.md)

## Verify

Focused invitation tests:

```powershell
python -m unittest discover -s tests -p test_employee_invitations.py
```

The broader test command is python -m unittest discover -s tests. Some inherited assertions still target older reward/signup contracts and an old fixed template count; do not claim that the entire suite is green. See [the current guidelines audit](docs/GUIDELINES_AUDIT.md) and [UI update notes](UI_UPDATE_NOTES.md) for evidence and limits.

MySQL integration tests in tests/run_mysql.py must target a disposable server using MYSQL_TEST_* variables; never point destructive test setup at the café database. Actual SMTP inbox delivery and MySQL execution were not verified in this coding session. The private static preview uses demo data and cannot replace a Flask/MySQL deployment.

## Course submission

[Guidelines audit](docs/GUIDELINES_AUDIT.md) separates implemented features from live configuration, client documentation, title approval, GitHub submission and defense obligations. Do not invent client interviews, client sign-off or instructor approval. The private preview is not the required GitHub repository submission.

## SQL menu files

Both schema.sql (SQLite) and schema.mysql.sql (MySQL) seed all 58 entries from data/menu_catalog.json plus the required cake workshop product. These CREATE TABLE scripts are for fresh databases only. For an existing database, select the correct database and run UPDATE_MENU_MYSQL.sql in Workbench, or UPDATE_MENU_SQLITE.sql using SQLite tooling. Stop the app and back up first. Matching catalog names/prices/descriptions/images are replaced; missing items are added. Existing IDs, custom products, availability and order history are retained, with the five old sample-only products hidden. No personal accounts are inserted or removed. Restart Flask afterwards for additive application migrations. The menu update does not recompute existing reward costs; review those in the Owner settings if prices were customized.

## Business continuity / Owner succession

OWNER_RECOVERY_SETUP.md documents server-terminal-only preparation, automatic private database backup, business authorization records and email-verified acceptance by a successor. Existing Owner access is revoked only after atomic completion; accounts/history are retained. There is no public Owner creation/reset endpoint. Applying the release does not initiate a succession.
