# Customer delivery map: rider-to-destination route

## Customer view
- Sign in as a customer and place a **delivery** order with a confirmed destination map pin.
- When the order is picked up and the assigned rider selects **Start sharing location** on the Rider Dashboard (HTTPS/localhost required), navigate to **My Orders → View rider route**.
- A purple dot marks the rider, a green dot marks the delivery destination. A **solid purple line** is the estimated road route when a public routing service responds. A **dashed gray line** is a straight-line fallback, not turn-by-turn roads.
- The map polls the existing private `/customer/orders/live` endpoint every 6 seconds. The route refreshes after sufficient rider movement with a 35-second minimum gap between routing requests. No ETA is promised.
- When GPS is stale, sharing stops, or the order is delivered, the customer map closes and does not keep showing outdated coordinates.
- Closing the map stops routing requests and does not disable the existing delivery or payment workflow.

## Production / privacy
- Route is fetched **only when the customer clicks** View rider route. The public OSRM demonstration server `router.project-osrm.org` receives the assigned rider and delivery coordinates for routing. Its availability is not guaranteed and it should not be depended on for production traffic. Use an approved production routing provider or self-host routing before a public deployment, updating the allowed `connect-src` domain in `security.py`.
- GPS is shared only when the assigned rider actively starts sharing. Customers only receive their own orders from the authenticated server endpoint; no public tracking URL was introduced.
- The Leaflet/OpenStreetMap tiles also require an internet connection. The existing user data/database, `.env` and private uploads are not included in the source ZIP.

## Technical changes
- `templates/customer/orders.html` — new View/Hide rider route control.
- `static/js/customer-tracking.js` — lazy Leaflet map, current markers, road-route polyline, clear fallback, throttled requests, cleanup.
- `static/css/pages/tracking.css` — responsive styling.
- `security.py` — allow the OSRM route request under CSP.
- **Admin Rider Cash remains removed**; all workshop payment features remain as they were.
