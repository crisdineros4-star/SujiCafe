FINAL UPDATE — Live views, workshop and Rider cleanup — 13 November 2026
The uploaded design and previous cash/receipt/Owner-only payment settings fixes remain.

LIVE UPDATES:
Visible pages check fresh server data about every 5 seconds while the tab is open.
Order tables update individual rows so an active rider/status selection does not
block new orders elsewhere. My Orders now receives newly created order cards.
Menu/products, counter catalog, bookings, dashboard data and payment-review pages
update without manual refresh. Returning to a tab/reconnecting triggers another check.
Search filters, typed inputs and open dialogs are retained. Cameras and maps retain
their existing live controllers. Login/security forms and transactional checkout
are not background-replaced. Checkout continues to validate data on the server.
The counter keeps member/quantities while refreshing catalog prices/totals. If a
selected item changes price or becomes unavailable, review the notice before recording
payment; a previously checked GCash wallet acknowledgement is cleared for rechecking.

WORKSHOP:
Owner/Admin: Pending shows Confirm + Cancel; Confirmed shows Confirmed + Cancel;
Cancelled has no actions. Staff confirmation updates open Owner/Admin pages.
Cancellation remains allowed after confirmation and now has a confirmation dialog.
Confirmation is not payment and cancellation does not automatically issue a refund.
Reserve my slot has its own modal with selected date, time and guests. Balikan
submits nothing; Confirm reservation submits once.

RIDER:
Removed Legacy COD cash-to-hand-over and recent cash-handover panels from Rider UI.
Current rider-advance delivery operations remain. Historical accounting records were
retained; removing a panel is not a financial write-off.

INSTALL:
The full ZIP includes all source and previous fixes. Copy the contents of suji-cafe/
into your project, preserving your own .env and database. For changed-files ZIP,
replace the EXISTING files and add all BAGO JavaScript/vendor files. The local
idiomorph dependency and its 0BSD license are included; no npm installation required.
New test files are optional for running regression checks.
Restart Flask, then Ctrl+F5 ONCE to load the new scripts. Subsequent data updates
appear automatically (about 5 seconds, depending on connectivity).
No SQL migration, authentication change or 7-day device-trust change.

VALIDATION:
31 focused Python regression tests passed on isolated SQLite data.
Browser checks passed for new orders across Owner/Admin/Staff/Customer, preserved
rider selections, products/menu/counter updates with live search, add-to-cart, counter
quantities and repricing, external payment confirmation, booking status sync,
Cancel/Reserve dialogs, and Rider rendering without legacy panels.
No JavaScript errors in these tested flows. The live engine passed CSP checks.
Full legacy suite and live MySQL were not run for this update.
