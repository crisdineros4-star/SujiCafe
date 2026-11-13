# Products, counter sale, account settings and updates

This package contains only files changed in this improvement batch. Apply the matching Python files, templates, CSS and JavaScript together, keep the existing private .env/database, then restart Flask and hard-refresh the browser.

## Products (Owner/Admin)

The Products workspace now uses separate cards, readable labels, an expandable creation form and expandable edit/photo panels. Live search, category and availability filters do not rebuild forms or discard unsaved typed values. Availability changes and delete/archive still use the existing server-side product rules and history preservation.

## Staff counter sale

Search by product name/description, filter category, or show only selected products. Reset filters does not reset quantities. Filtered rows retain their quantity inputs, which remain in the submitted form and total calculation. Enter in the search field moves to the first visible quantity instead of submitting a purchase. Empty results are explicit. Invalid quantities reveal their row so the user can correct them.

## Admin invitation verification

New Admin accounts now use the same 24-hour email invitation and private-password activation as Staff/Riders. Only Owner can create/resend/cancel Admin invitations or manage Admin accounts. Public signup and Admin users cannot grant Admin roles. Existing active accounts remain active.

Local create-owner remains available for Owner bootstrap. The create-admin CLI command now directs the operator to the Owner invitation flow rather than bypassing email activation. SMTP and PUBLIC_BASE_URL remain required; see EMPLOYEE_INVITATIONS_SETUP.md. No real invitation email was sent during automated testing.

## Self-service profiles and employee management

Owner/Admin/Staff/Rider have /account for their own names, mobile and password. The customer retains the existing customer profile/member-card page. Role and sign-in email are not editable through self-service forms. Password changes require the current password and revoke other trusted devices while keeping the current verified browser usable.

Owner/Admin can edit Staff/Rider names/mobile, correct a pending invitation's email with a replacement invitation, deactivate accounts with a reason, and re-enable them. Only Owner can manage other Admins. No user can deactivate themselves or an Owner through these controls. Active email addresses and roles are not silently reassigned. A rider's active deliveries must be resolved/reassigned first. Deactivation revokes devices/codes and cancels pending invitations; re-enabling a never-activated account still requires a new invitation.

## Customer order notifications

Order placement, status, rider assignment/pickup/delivery, payment and refund events create in-app customer updates in the same transaction. No email/push-notification permissions are added. Customers have an Updates page and unread count; read/read-all actions are scoped to the signed-in customer. Notification polling does not extend device inactivity timers. Existing historical orders are not backfilled; new changes are recorded after this update.

## Database and verification

New account_access and customer_notifications tables are created automatically on startup for SQLite/MySQL. Employee invitations still use the existing employee_invitations table. Keep the live database; do not replace it with demo data.

The private preview uses isolated sample accounts/orders and disables real mutations. Automated logic/browser checks use SQLite and mocked email. Actual SMTP delivery and MySQL operation require deployment testing. The earlier broad suite has known stale reward/signup/template-count expectations; do not claim all legacy tests pass.

The project-guidelines review is deliberately deferred while this improvement batch is being evaluated. This file describes implementation and setup, not an academic-compliance verdict.

## Self-completed employee invitations and all-role validation

Owner/Admin now enter only an invitation email and the approved role. New pending accounts have empty personal details and no reserved mobile number. The recipient enters first/middle/last names, mobile and a private password at activation. Only Owner can invite Admins. Existing accounts remain intact; previously pending invitations use the same activation form. Role/email cannot be overridden by activation POST fields.

All five roles validate names, optional middle name, unique PH mobile numbers and password changes on the server. Matching browser validation shows field errors and focuses the first invalid field. Required fields have red markers. New passwords must differ from the current password, have 8–128 characters and contain uppercase/lowercase letters, a digit and a symbol; changes require the current password and revoke other trusted devices. Password inputs are cleared on page navigation/reload and never stored by this code.

Customer email is now read-only like other roles, preserving verification. Customer addresses are optional, otherwise 10–500 characters. Name policy/prohibited-language checks and mobile uniqueness remain server authoritative. Pending employee management edits only correct invitation email; recipients supply their own personal data. No birthday/other existing registration data is removed.
