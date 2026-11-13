# Suji website UI update

This update builds on the homepage and authentication changes already supplied. The changed-files ZIP includes only files changed during the all-pages review and the registration-draft update. Existing files must be replaced, not added a second time.

## Install

1. Back up the current source and database. Keep your private .env and live database.
2. Replace the existing files listed in the source viewer. Add the two restored browser scripts, static/js/form-validation.js and static/js/staff-live.js. The original ZIP had their content under different filenames, so the URLs requested by the pages returned 404.
3. password_reset.py already exists in the ZIP but was empty: replace its contents. Its table is created automatically on first use for SQLite or MySQL. The database user needs CREATE TABLE permission. No manual reset of user records is required.
4. Tests under tests/ are optional for running the website. UI_UPDATE_NOTES.md is documentation.
5. Restart Flask and hard-refresh the browser with Ctrl+F5.

## What changed

- Consistent, readable input borders, labels, focused controls, buttons, tabs, panels and tables across customer and store workspaces.
- Tables scroll within their own container; order IDs, phone numbers, amounts and order types remain readable.
- Single-column menu cards on narrow phones, a scrolling category selector, a more compact cart row, and a usable full-width Staff code field.
- Clear headings for Owner, Admin and Rider; keyboard support for workspace tabs. Staff starts on the existing active Orders tab.
- Order status selectors require an explicit next status instead of defaulting to a potentially destructive action.
- Accessible form-label associations, required-field markers, and keyboard-focusable table regions, including dynamically refreshed content.
- Consistent compact password-recovery screens, receipt printing refinements and a responsive error state.
- Recovered the existing reset-password flow: real emailed code, five wrong-attempt limit, 60-second resend cooldown, ten-minute expiry, and a separate ten-minute single-use password-update grant. Successful password changes revoke old trusted devices and email codes. A failed SMTP send never enables a development bypass.

## Registration draft

Only these values are written to this tab's sessionStorage: first_name, middle_name, last_name, email, phone, birthdate, birth_month, birth_day and birth_year. Both complete and partially selected birthdays are retained.

Password and Confirm password are never written to browser storage. Both are cleared on initial load, page restoration and before leaving the registration document. The server already returns account pages with Cache-Control: private, no-store and does not render submitted passwords back into the HTML.

The personal/contact draft survives refreshes, normal navigation and the email-code step. It clears after successful verified registration. Google registration clears it only when a new account was actually created. Returning with Back does not repopulate a completed registration. sessionStorage is scoped to a browser tab and normally ends when that tab closes; browser session-restore features are controlled by the browser.

## Preview

The private preview hub shows 28 example pages covering all 27 templates, with guest/customer variants and demo workspaces. Names, addresses, orders and payments in previews are sample data from an isolated disposable database. No real email, account creation, payment update, camera capture or GPS sharing takes place in the hosted previews. The installed Flask app retains its normal permissions and actions.

## Validation and known limits

- All 27 templates were inspected. 29 route/render states passed 116 browser layout cases at 320, 375, 768 and 1440px, with no page-level horizontal overflow or JavaScript exceptions. The duplicated Admin-settings redirect is omitted from the preview hub.
- Owner, Admin and Staff tabs were opened at 320 and 1440px. Keyboard tab switching and explicit order-status selection were checked.
- Browser checks passed for per-tab registration drafts, complete/partial birthday restoration, navigation, password clearing, absence of passwords in storage, completion clearing and Back navigation.
- Focused email-registration and password-reset tests pass. Actual SMTP delivery and MySQL were not exercised because deployment credentials are not configured here.
- The broad existing suite ran 137 tests and reported 15 failures/errors. Eight reward-policy assertions also fail against the unmodified uploaded ZIP (four in test_commerce.py and four in test_ops.py). Six older registration cases assume accounts are created without the requested email-verification step; one case assumes exactly 25 templates. These legacy expectations/business-rule mismatches were not changed as part of the UI work. The full suite is therefore not green; do not interpret this UI review as validation of every business rule.
