# Sign-up email verification

Sign up now sends a six-digit code and redirects to /register/verify. No user account or mobile claim is created until the correct code is entered. This proves access to the inbox, not a person's legal identity. Gmail and other valid mail domains are supported. Google sign-in continues to rely on Google's verified-email response.

## Sender setup

Copy .env.example to .env (or update your existing private .env). Set:

```
SECRET_KEY=<a stable, long random secret>
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_SECURITY=starttls
GMAIL_USER=<your sender Gmail address>
SMTP_FROM=<the same sender Gmail address>
GMAIL_APP_PASSWORD=<your Google App Password>
DEV_PRINT_OTP=0
```

Enable Google 2-Step Verification on the sender account and create an App Password. Use that App Password, not the normal Gmail password. Do not commit .env. Restart the app after configuration. Do not share credentials in chat.

The existing database settings still apply. A new signup_verifications table is automatically created on first use for SQLite or MySQL; the database user needs CREATE TABLE permission. Existing users remain usable.

Codes expire after 10 minutes. At most five checks and five sends are allowed per pending registration, with a 60-second resend cooldown. Resending invalidates the earlier code without extending the original expiry. Pending data and password hashes stay in the database; only an opaque token is kept in the session. Expired pending records are removed when another signup starts. A failed SMTP send never creates a user or enables a development-code bypass. For an incorrect email, restart signup with the correct address. A repeated signup for an already pending email must wait for expiry or use its existing browser verification page.

## Verify the setup

Register with an inbox you control. Confirm no account exists before code entry, the code arrives (check spam), an incorrect code is rejected, and the correct code creates the account. Then log in normally. Real email delivery requires your SMTP credentials and was not exercised by the automated tests, which mock the sender. MySQL should be checked in your deployment; automated registration tests use SQLite.
