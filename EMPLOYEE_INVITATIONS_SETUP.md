# Employee account invitations

Owner and Admin can invite Staff and Riders. Owner alone can invite Admin accounts, which now require the same email activation before access. This update does not add public employee registration or change existing active employees.

## Private configuration

Keep the existing .env and database. Add PUBLIC_BASE_URL to your private .env:

```
PUBLIC_BASE_URL=https://your-actual-website-domain.example
```

Use your actual reachable HTTPS origin, without a path/query. For same-computer local testing only, http://127.0.0.1:5000 is supported. A localhost link cannot open your computer's app from an employee's phone or another computer. Never put email passwords in a URL.

The existing SMTP_HOST, SMTP_PORT, SMTP_SECURITY, SMTP_FROM, GMAIL_USER and GMAIL_APP_PASSWORD settings must work. Gmail requires an App Password. No SMTP credentials or actual public origin are included in this source.

Restart Flask after changing .env. The employee_invitations table is created automatically at startup for SQLite or MySQL. Its absence does not require replacing the users table. Existing users without an invitation row are treated as active.

## Flow

1. Owner/Admin chooses Staff or Rider and supplies only the invitation email. Only Owner can choose Admin.
2. The app reserves a pending account with an unguessable password hash and emails an activation link. If sending fails, the new account rolls back.
3. The employee opens the link, verifies possession of that inbox and supplies their own first/middle/last names, unique mobile number and private password. The approved role/email are read from the invitation, never from submitted role/email fields.
4. The link expires in 24 hours and is consumed only after valid personal details and a password are saved. Simply opening it does not activate the account.
5. The activation browser is remembered after successful setup; the employee logs in using the password they chose. An already signed-in account is not silently switched.

The Owner/Admin lists show Active, Pending activation, Invitation expired or Invitation cancelled. Resend requires 60 seconds between sends and permits five sends per 24-hour send window. Resend invalidates the previous link and grants a new 24-hour expiry. Cancelling blocks pending activation; an explicit new invitation can be sent later. Active accounts cannot be cancelled using invitation controls.

Pending/cancelled accounts cannot use password login, Google sign-in, password reset or protected workspaces. Pending riders are excluded from assignment lists and rejected by the assignment repository. Owners/Admins cannot view the chosen password or the raw invitation token in their account list/activity log.

## Installation files

The source viewer labels existing files for replacement and new files for addition. Apply the matching Python modules together: core.py, commerce.py, employee_invitations.py, admin.py, auth.py, config.py, password_reset.py, repositories.py and staff.py. Also replace both Owner/Admin templates and add the activation template and activation JavaScript. Tests and documentation are optional at runtime.

.env.example is an example, not a replacement for your existing private .env. Copy only the new PUBLIC_BASE_URL setting into your private configuration. Do not overwrite credentials.

## Verification limits

Invitation logic is tested using mocked email delivery and an isolated SQLite database. Real SMTP inbox delivery, a real reachable public origin and MySQL still require deployment verification. A private static preview demonstrates the pages using fake data; it cannot create real employee accounts or send invitations.

See OPERATIONS_IMPROVEMENTS.md for verified Admin invitations, account edits/deactivation and self-service settings. The create-admin CLI no longer bypasses email activation.
