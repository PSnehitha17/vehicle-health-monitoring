# Smart Vehicle Health Monitoring & Predictive Maintenance System

A full working demo matching your project's architecture:
**Vehicle Sensors → IoT Gateway → Cloud & AI Engine → Web Dashboard.**

Lightweight by design: **only dependency is Flask**, storage is **SQLite**
(built into Python, zero setup), and the frontend is plain HTML/CSS/JS —
no React build, no TensorFlow install, no internet connection needed. It
starts in a couple of seconds and stays fast no matter how long it runs.

## Features

- **Login system** — simple session-based auth protecting the dashboard
- **Fleet overview** — every vehicle as a card, live health score, sorted
  worst-first, with search
- **Add / delete vehicles** at any time, right from the dashboard — new
  vehicles get a realistic starting condition (healthy / moderate wear /
  at risk / random mix), not always a perfect score
- **Live sensor simulation** — engine temp, battery voltage, tyre pressure,
  brake wear, vibration — updating every 3 seconds per vehicle, with
  occasional simulated anomalies so alerts actually fire during a demo
- **Rule-based AI prediction engine** — scores each vehicle 0–100 and
  raises warning/critical alerts, standing in for a trained ML model so
  the demo needs no training data or GPU
- **Predicted maintenance** — a simple trend-based projection ("brake
  service predicted in ~X min/hrs", "health trending downward") shown on
  each vehicle's page
- **Service log** — log a real maintenance action (brake pad replacement,
  battery swap, tyre service, general service); it resets the relevant
  sensor and keeps a dated history
- **Configurable alert thresholds** — a Settings page to tune what counts
  as "normal" per sensor, applied instantly across the whole fleet
- **CSV report export** — download a full per-vehicle report (readings,
  alerts, service history) for your project report/viva
- **Live trend chart & alert feed** per vehicle, drawn with plain
  Canvas/SVG (no chart library, so it loads instantly)

## How to run

```bash
pip install -r requirements.txt
python app.py
```

Then open your browser to:

```
http://127.0.0.1:5000
```

**Login:** `admin` / `admin123`

To stop the server, press `CTRL+C` in the terminal.

## Project structure

```
smart_vehicle_health/
├── app.py                  # Flask backend: auth, simulator, AI engine, all APIs
├── requirements.txt         # Only Flask
├── templates/
│   ├── base.html             # Shared nav layout
│   ├── login.html
│   ├── fleet.html             # Fleet overview + Add Vehicle modal
│   ├── vehicle.html           # Per-vehicle dashboard + service log
│   └── settings.html          # Threshold configuration
├── static/
│   ├── style.css
│   ├── fleet.js
│   ├── vehicle.js
│   └── settings.js
└── README.md
```

A `vehicle_health.db` SQLite file is created automatically on first run —
that's where all vehicles, readings, alerts, service history, and settings
live. Delete it any time to reset the demo to a clean state.

## What's happening under the hood

- `app.py` runs a background thread that simulates every vehicle's sensors
  with a small random walk, occasionally injecting an anomaly (~4% chance
  per tick) so real alerts appear during a live demo.
- `predict_health()` is the rule-based "AI engine" — it scores 0–100 based
  on how far each sensor is from the currently configured normal range
  (editable on the Settings page).
- `predict_maintenance()` does a lightweight linear-regression trend on
  recent brake-wear and health-score readings (no numpy needed) to produce
  a simulated "predicted maintenance" message — this maps to the
  Remaining-Useful-Life (RUL) prediction concept from your proposal.
- Logging a service in the UI resets the relevant sensor to a "just
  serviced" baseline and records it in `service_log`, so you can
  demonstrate the full maintenance loop end to end.

## Extending it for your report / viva

- Swap `predict_health()` for a real trained model (e.g. a scikit-learn
  `IsolationForest` or `RandomForestClassifier`) if evaluators want to see
  actual ML — it already takes one reading and returns a score + alert
  list, so nothing else in the app needs to change.
- Replace the simulator with real ESP32/OBD-II sensor input by posting
  readings to a new `/api/ingest` endpoint instead of generating them in
  `simulate_tick()`.
- Swap SQLite for PostgreSQL (as named in your tech stack) by changing the
  `sqlite3.connect` calls to a `psycopg2`/`SQLAlchemy` connection — the SQL
  is standard enough to port directly.
- Replace the hardcoded `admin/admin123` login with a real `users` table
  and password hashing (`werkzeug.security.generate_password_hash`) for a
  production-style auth flow.
