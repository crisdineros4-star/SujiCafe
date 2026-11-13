# Workshop Payment: Staff / Admin / Owner update

- Staff: Dashboard → Workshop → Record Cash / GCash payment.
- Admin: Dashboard → Workshop → Record Cash / GCash payment (new).
- Owner: Dashboard → Workshop → Record Cash / GCash payment (new), and refund only after booking cancellation and actual funds return.
- Only confirmed, unpaid bookings can accept a payment record.
- Staff, Admin, and Owner must verify the actual incoming cash or GCash transaction before recording it.
- Payment is a manual record, **not** a GCash API transfer or automatic verification.
- Backend blocks duplicate charges and duplicate GCash reference IDs, mismatched totals, and missing confirmation.
- The Workshop tab's 5-second live refresh also shows these forms for newly confirmed reservations.

## Upgrading an existing installation

Back up your existing project files, database and .env. This ZIP intentionally excludes the .env file, database and private user uploads. Extract the source project and merge source code files. Keep the existing production .env, database, payment uploads and customer upload data. Check environment requirements and README before running the app.

Updated source: admin.py; templates/admin/dashboard.html; templates/owner/dashboard.html; templates/shared/workshop_payment_form.html; static/js/booking-status.js; static/js/workshop-payment-ui.js. A test file is also updated.
