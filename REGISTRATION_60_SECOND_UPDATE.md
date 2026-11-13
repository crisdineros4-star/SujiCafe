# SUJI Café registration: 60-second resend fix

- You may resend an email verification code **60 seconds** after the last send, not after 10 minutes.
- Each new code expires **10 minutes after it was sent**.
- Returning to Sign Up in the same browser keeps the active code and shows **Continue verification**.
- If the browser was closed or session disappeared, submitting the sign-up form again with the same email resumes the existing request (or resends after 60 seconds); there is no duplicate-email insertion failure.
- **I already have a code** still lets you complete signup with the code from your inbox without needing your old browser session.
- To prevent abuse there is still a maximum of five sends and five verification attempts per pending signup, plus server-side request throttles.

## Installation

1. Back up your current project, database and `.env`.
2. Unzip the full source into a new folder and install Python requirements if needed.
3. Copy over your own `.env` and keep your existing MySQL database; the ZIP intentionally has no real `.env`, database or uploaded customer files.
4. Restart Flask after updating.
5. Test sending, Back → Continue Verification, Resend after 60s, and complete signup with the newest OTP.

Do not share your real Gmail App Password, database password, SECRET_KEY or verification codes.
