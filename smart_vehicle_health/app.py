"""
Smart Vehicle Health Monitoring and Predictive Maintenance System
-------------------------------------------------------------------
Full-featured lightweight demo backend.

Architecture (matches project PPT):
  Vehicle Sensors --> IoT Gateway (simulated) --> Cloud & AI Engine (health
  score + predictive maintenance, rule-based for a fast, dependency-free
  demo) --> Web Dashboard (login, fleet overview, alerts, service log,
  report export, configurable thresholds)

Run:
    pip install -r requirements.txt
    python app.py
Then open http://127.0.0.1:5000  (login: admin / admin123)

Only dependency: Flask. Storage: SQLite (built into Python, zero setup).
Everything -- vehicles, readings, alerts, service history, settings -- is
generated/stored locally, so it starts in seconds with no internet and no
heavy ML/JS frameworks, and stays fast no matter how long it runs.
"""

import csv
import io
import json
import random
import sqlite3
import threading
import time
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import (Flask, Response, g, jsonify, redirect, render_template,
                    request, session, url_for)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "vehicle_health.db"

app = Flask(__name__)
app.secret_key = "smart-vehicle-health-demo-secret"  # fine for a local demo

ADMIN_USER = "admin"
ADMIN_PASS = "admin123"

# ---------------------------------------------------------------------------
# Defaults / reference data
# ---------------------------------------------------------------------------

DEFAULT_THRESHOLDS = {
    "engine_temp":   {"min": 70,  "max": 100, "unit": "°C",  "critical": 112},
    "battery_volt":  {"min": 12.0, "max": 14.4, "unit": "V",  "critical_low": 11.2},
    "tyre_pressure": {"min": 30,  "max": 35,  "unit": "psi", "critical_low": 24},
    "brake_wear":    {"min": 0,   "max": 70,  "unit": "%",   "critical": 85},
    "vibration":     {"min": 0,   "max": 3.0, "unit": "mm/s", "critical": 5.5},
}

# in-memory copy kept in sync with the `settings` table
THRESHOLDS = json.loads(json.dumps(DEFAULT_THRESHOLDS))

CONDITION_PROFILES = {
    "healthy": {
        "engine_temp": (78, 86), "battery_volt": (12.8, 13.6),
        "tyre_pressure": (31, 34), "brake_wear": (5, 20), "vibration": (0.6, 1.6),
    },
    "moderate": {
        "engine_temp": (88, 98), "battery_volt": (12.1, 12.6),
        "tyre_pressure": (28, 30.5), "brake_wear": (45, 65), "vibration": (1.8, 2.8),
    },
    "at_risk": {
        "engine_temp": (100, 110), "battery_volt": (11.3, 11.9),
        "tyre_pressure": (24.5, 27.5), "brake_wear": (68, 82), "vibration": (3.2, 4.8),
    },
}

SERVICE_ACTIONS = {
    "brake_service":   {"label": "Brake Pad Replacement",      "reset": {"brake_wear": 3}},
    "battery_replace": {"label": "Battery Replacement",        "reset": {"battery_volt": 13.4}},
    "tyre_service":     {"label": "Tyre Rotation / Refill",     "reset": {"tyre_pressure": 33}},
    "general_service":  {"label": "General Service / Coolant Flush", "reset": {"engine_temp": 82, "vibration": 1.0}},
}

_lock = threading.Lock()


def random_state(profile_key=None):
    if profile_key is None or profile_key == "random":
        profile_key = random.choices(
            ["healthy", "moderate", "at_risk"], weights=[0.5, 0.35, 0.15]
        )[0]
    p = CONDITION_PROFILES[profile_key]
    return {k: round(random.uniform(*rng), 2) for k, rng in p.items()}


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS vehicles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            engine_temp REAL, battery_volt REAL, tyre_pressure REAL,
            brake_wear REAL, vibration REAL
        );
        CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vehicle_id INTEGER NOT NULL,
            ts TEXT NOT NULL,
            engine_temp REAL, battery_volt REAL, tyre_pressure REAL,
            brake_wear REAL, vibration REAL, health_score REAL
        );
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vehicle_id INTEGER NOT NULL,
            ts TEXT NOT NULL,
            severity TEXT NOT NULL,
            message TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS service_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vehicle_id INTEGER NOT NULL,
            ts TEXT NOT NULL,
            service_type TEXT NOT NULL,
            notes TEXT
        );
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            thresholds_json TEXT NOT NULL
        );
        """
    )
    conn.commit()

    if conn.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 0:
        conn.execute(
            "INSERT INTO settings (id, thresholds_json) VALUES (1, ?)",
            (json.dumps(DEFAULT_THRESHOLDS),),
        )
        conn.commit()
    else:
        global THRESHOLDS
        THRESHOLDS = json.loads(
            conn.execute("SELECT thresholds_json FROM settings WHERE id=1").fetchone()[0]
        )

    if conn.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0] == 0:
        seed = [
            ("Vehicle A - Sedan (TS09 AB 1234)", random_state("healthy")),
            ("Vehicle B - SUV (TS09 CD 5678)", random_state("moderate")),
            ("Vehicle C - Delivery Van (TS09 EF 9012)", random_state("at_risk")),
        ]
        for name, s in seed:
            conn.execute(
                """INSERT INTO vehicles (name, engine_temp, battery_volt,
                   tyre_pressure, brake_wear, vibration) VALUES (?,?,?,?,?,?)""",
                (name, s["engine_temp"], s["battery_volt"], s["tyre_pressure"],
                 s["brake_wear"], s["vibration"]),
            )
        conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Not authenticated"}), 401
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if username == ADMIN_USER and password == ADMIN_PASS:
            session["logged_in"] = True
            session["username"] = username
            return redirect(request.args.get("next") or url_for("fleet_overview"))
        return render_template("login.html", error="Invalid username or password.")
    return render_template("login.html", error=None)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Prediction engine
# ---------------------------------------------------------------------------

def predict_health(reading):
    """Rule-based predictive-maintenance 'AI engine'. Scores 0-100 using
    the currently configured thresholds (editable from the Settings page).
    Stands in for a trained ML model (scikit-learn/TensorFlow, as named in
    the tech-stack slide) so the demo runs instantly with no training step."""
    score = 100.0
    alerts = []
    T = THRESHOLDS

    t = reading["engine_temp"]
    if t > T["engine_temp"]["critical"]:
        score -= 35
        alerts.append(("critical", f"Engine overheating: {t:.1f}°C"))
    elif t > T["engine_temp"]["max"]:
        score -= 12
        alerts.append(("warning", f"Engine temperature high: {t:.1f}°C"))

    v = reading["battery_volt"]
    if v < T["battery_volt"]["critical_low"]:
        score -= 30
        alerts.append(("critical", f"Battery critically low: {v:.2f}V"))
    elif v < T["battery_volt"]["min"]:
        score -= 10
        alerts.append(("warning", f"Battery voltage low: {v:.2f}V"))

    p = reading["tyre_pressure"]
    if p < T["tyre_pressure"]["critical_low"]:
        score -= 25
        alerts.append(("critical", f"Tyre pressure critically low: {p:.1f} psi"))
    elif p < T["tyre_pressure"]["min"]:
        score -= 8
        alerts.append(("warning", f"Tyre pressure low: {p:.1f} psi"))

    b = reading["brake_wear"]
    if b > T["brake_wear"]["critical"]:
        score -= 30
        alerts.append(("critical", f"Brake pads critically worn: {b:.0f}%"))
    elif b > T["brake_wear"]["max"]:
        score -= 10
        alerts.append(("warning", f"Brake wear high: {b:.0f}%"))

    vb = reading["vibration"]
    if vb > T["vibration"]["critical"]:
        score -= 20
        alerts.append(("critical", f"Abnormal vibration detected: {vb:.2f} mm/s"))
    elif vb > T["vibration"]["max"]:
        score -= 7
        alerts.append(("warning", f"Vibration above normal: {vb:.2f} mm/s"))

    score = max(0.0, min(100.0, score))
    return round(score, 1), alerts


def trend_slope(values):
    """Simple linear-regression slope, no numpy needed."""
    n = len(values)
    if n < 3:
        return 0.0
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(values) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, values))
    den = sum((x - mx) ** 2 for x in xs)
    return num / den if den else 0.0


def predict_maintenance(brake_history, score_history):
    """Very simple Remaining-Useful-Life style projection used for the
    dashboard's 'Predicted Maintenance' card. Clearly a simulated demo
    projection, not a certified RUL model."""
    if len(brake_history) < 5:
        return "Collecting data — prediction available shortly."

    slope = trend_slope(brake_history)  # % wear per reading (~3s apart)
    current = brake_history[-1]
    critical = THRESHOLDS["brake_wear"]["critical"]

    if slope <= 0.001:
        brake_msg = "Brake wear stable — no service trend detected."
    else:
        ticks_left = max(0, (critical - current) / slope)
        minutes_left = ticks_left * 3 / 60
        if current >= critical:
            brake_msg = "Brake pads at critical wear — service immediately."
        elif minutes_left < 15:
            brake_msg = f"Brake service predicted within ~{minutes_left:.0f} min (simulated)."
        else:
            brake_msg = f"Brake service predicted in ~{minutes_left/60:.1f} hrs of continued use (simulated)."

    score_slope = trend_slope(score_history)
    if score_slope < -0.3:
        trend_msg = "Overall health is trending downward — monitor closely."
    elif score_slope > 0.3:
        trend_msg = "Overall health is trending upward."
    else:
        trend_msg = "Overall health is stable."

    return f"{brake_msg} {trend_msg}"


# ---------------------------------------------------------------------------
# Simulation engine
# ---------------------------------------------------------------------------

def get_vehicle_ids():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ids = [r[0] for r in conn.execute("SELECT id FROM vehicles").fetchall()]
    conn.close()
    return ids


def simulate_tick(conn, vehicle_id):
    row = conn.execute("SELECT * FROM vehicles WHERE id=?", (vehicle_id,)).fetchone()
    if row is None:
        return
    s = {
        "engine_temp": row["engine_temp"], "battery_volt": row["battery_volt"],
        "tyre_pressure": row["tyre_pressure"], "brake_wear": row["brake_wear"],
        "vibration": row["vibration"],
    }
    baseline = {"engine_temp": 82, "battery_volt": 13.0, "tyre_pressure": 32, "vibration": 1.2}

    s["engine_temp"] += random.uniform(-1.2, 1.4)
    s["battery_volt"] += random.uniform(-0.05, 0.05)
    s["tyre_pressure"] += random.uniform(-0.3, 0.3)
    s["brake_wear"] += random.uniform(0, 0.15)
    s["vibration"] += random.uniform(-0.2, 0.25)

    if random.random() < 0.04:
        pick = random.choice(list(s.keys()))
        if pick == "engine_temp":
            s[pick] += random.uniform(15, 30)
        elif pick == "battery_volt":
            s[pick] -= random.uniform(1.5, 2.5)
        elif pick == "tyre_pressure":
            s[pick] -= random.uniform(8, 12)
        elif pick == "brake_wear":
            s[pick] += random.uniform(20, 30)
        elif pick == "vibration":
            s[pick] += random.uniform(3, 5)

    s["engine_temp"] = max(60, min(140, s["engine_temp"]))
    s["battery_volt"] = max(9.5, min(14.8, s["battery_volt"]))
    s["tyre_pressure"] = max(15, min(38, s["tyre_pressure"]))
    s["brake_wear"] = max(0, min(100, s["brake_wear"]))
    s["vibration"] = max(0, min(8, s["vibration"]))

    for key, target in baseline.items():
        s[key] += (target - s[key]) * 0.05

    reading = {k: round(val, 2) for k, val in s.items()}
    score, alerts = predict_health(reading)
    ts = datetime.now().isoformat(timespec="seconds")

    conn.execute(
        """UPDATE vehicles SET engine_temp=?, battery_volt=?, tyre_pressure=?,
           brake_wear=?, vibration=? WHERE id=?""",
        (reading["engine_temp"], reading["battery_volt"], reading["tyre_pressure"],
         reading["brake_wear"], reading["vibration"], vehicle_id),
    )
    conn.execute(
        """INSERT INTO readings (vehicle_id, ts, engine_temp, battery_volt,
           tyre_pressure, brake_wear, vibration, health_score)
           VALUES (?,?,?,?,?,?,?,?)""",
        (vehicle_id, ts, reading["engine_temp"], reading["battery_volt"],
         reading["tyre_pressure"], reading["brake_wear"], reading["vibration"], score),
    )
    for severity, message in alerts:
        conn.execute(
            "INSERT INTO alerts (vehicle_id, ts, severity, message) VALUES (?,?,?,?)",
            (vehicle_id, ts, severity, message),
        )

    conn.execute(
        """DELETE FROM readings WHERE id IN (
             SELECT id FROM readings WHERE vehicle_id=? ORDER BY id DESC LIMIT -1 OFFSET 200)""",
        (vehicle_id,),
    )
    conn.execute(
        """DELETE FROM alerts WHERE id IN (
             SELECT id FROM alerts WHERE vehicle_id=? ORDER BY id DESC LIMIT -1 OFFSET 50)""",
        (vehicle_id,),
    )


def background_simulator():
    while True:
        with _lock:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            for vid in get_vehicle_ids():
                simulate_tick(conn, vid)
            conn.commit()
            conn.close()
        time.sleep(3)


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@app.route("/")
@login_required
def fleet_overview():
    return render_template("fleet.html", username=session.get("username"))


@app.route("/vehicle/<int:vehicle_id>")
@login_required
def vehicle_page(vehicle_id):
    conn = get_db()
    v = conn.execute("SELECT * FROM vehicles WHERE id=?", (vehicle_id,)).fetchone()
    if v is None:
        return redirect(url_for("fleet_overview"))
    return render_template("vehicle.html", vehicle_id=vehicle_id, vehicle_name=v["name"],
                            service_actions=SERVICE_ACTIONS, username=session.get("username"))


@app.route("/settings")
@login_required
def settings_page():
    return render_template("settings.html", thresholds=THRESHOLDS, username=session.get("username"))


# ---------------------------------------------------------------------------
# API: vehicles
# ---------------------------------------------------------------------------

@app.route("/api/vehicles", methods=["GET"])
@login_required
def api_vehicles():
    conn = get_db()
    vehicles = conn.execute("SELECT id, name FROM vehicles ORDER BY id").fetchall()
    out = []
    for v in vehicles:
        row = conn.execute(
            "SELECT health_score FROM readings WHERE vehicle_id=? ORDER BY id DESC LIMIT 1",
            (v["id"],),
        ).fetchone()
        out.append({"id": v["id"], "name": v["name"],
                     "health_score": row["health_score"] if row else None})
    return jsonify(out)


@app.route("/api/vehicles", methods=["POST"])
@login_required
def api_add_vehicle():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    profile = data.get("condition", "random")
    if not name:
        return jsonify({"error": "Vehicle name is required"}), 400

    s = random_state(profile)
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """INSERT INTO vehicles (name, engine_temp, battery_volt, tyre_pressure,
               brake_wear, vibration) VALUES (?,?,?,?,?,?)""",
            (name, s["engine_temp"], s["battery_volt"], s["tyre_pressure"],
             s["brake_wear"], s["vibration"]),
        )
        new_id = cur.lastrowid
        simulate_tick(conn, new_id)
        conn.commit()
        conn.close()
    return jsonify({"id": new_id, "name": name}), 201


@app.route("/api/vehicle/<int:vehicle_id>", methods=["DELETE"])
@login_required
def api_delete_vehicle(vehicle_id):
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM vehicles WHERE id=?", (vehicle_id,))
        conn.execute("DELETE FROM readings WHERE vehicle_id=?", (vehicle_id,))
        conn.execute("DELETE FROM alerts WHERE vehicle_id=?", (vehicle_id,))
        conn.execute("DELETE FROM service_log WHERE vehicle_id=?", (vehicle_id,))
        conn.commit()
        conn.close()
    return jsonify({"deleted": vehicle_id})


@app.route("/api/vehicle/<int:vehicle_id>")
@login_required
def api_vehicle(vehicle_id):
    conn = get_db()
    latest = conn.execute(
        "SELECT * FROM readings WHERE vehicle_id=? ORDER BY id DESC LIMIT 1", (vehicle_id,)
    ).fetchone()
    history = conn.execute(
        "SELECT * FROM readings WHERE vehicle_id=? ORDER BY id DESC LIMIT 30", (vehicle_id,)
    ).fetchall()
    alerts = conn.execute(
        "SELECT * FROM alerts WHERE vehicle_id=? ORDER BY id DESC LIMIT 10", (vehicle_id,)
    ).fetchall()
    service = conn.execute(
        "SELECT * FROM service_log WHERE vehicle_id=? ORDER BY id DESC LIMIT 10", (vehicle_id,)
    ).fetchall()

    history_rows = list(reversed(history))
    prediction = predict_maintenance(
        [r["brake_wear"] for r in history_rows],
        [r["health_score"] for r in history_rows],
    )

    return jsonify({
        "latest": dict(latest) if latest else None,
        "history": [dict(r) for r in history_rows],
        "alerts": [dict(a) for a in alerts],
        "service_log": [dict(s) for s in service],
        "thresholds": THRESHOLDS,
        "prediction": prediction,
    })


@app.route("/api/vehicle/<int:vehicle_id>/service", methods=["POST"])
@login_required
def api_log_service(vehicle_id):
    data = request.get_json(silent=True) or {}
    service_type = data.get("type")
    notes = (data.get("notes") or "").strip()
    action = SERVICE_ACTIONS.get(service_type)
    if not action:
        return jsonify({"error": "Unknown service type"}), 400

    ts = datetime.now().isoformat(timespec="seconds")
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        set_clause = ", ".join(f"{k}=?" for k in action["reset"])
        conn.execute(
            f"UPDATE vehicles SET {set_clause} WHERE id=?",
            (*action["reset"].values(), vehicle_id),
        )
        conn.execute(
            "INSERT INTO service_log (vehicle_id, ts, service_type, notes) VALUES (?,?,?,?)",
            (vehicle_id, ts, action["label"], notes),
        )
        conn.execute(
            "INSERT INTO alerts (vehicle_id, ts, severity, message) VALUES (?,?,?,?)",
            (vehicle_id, ts, "info", f"Service logged: {action['label']}"),
        )
        simulate_tick(conn, vehicle_id)
        conn.commit()
        conn.close()
    return jsonify({"status": "ok", "label": action["label"]})


@app.route("/api/vehicle/<int:vehicle_id>/export")
@login_required
def api_export_vehicle(vehicle_id):
    conn = get_db()
    v = conn.execute("SELECT * FROM vehicles WHERE id=?", (vehicle_id,)).fetchone()
    if v is None:
        return jsonify({"error": "Vehicle not found"}), 404
    readings = conn.execute(
        "SELECT * FROM readings WHERE vehicle_id=? ORDER BY id", (vehicle_id,)
    ).fetchall()
    alerts = conn.execute(
        "SELECT * FROM alerts WHERE vehicle_id=? ORDER BY id", (vehicle_id,)
    ).fetchall()
    service = conn.execute(
        "SELECT * FROM service_log WHERE vehicle_id=? ORDER BY id", (vehicle_id,)
    ).fetchall()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([f"Vehicle Health Report - {v['name']}"])
    w.writerow([f"Generated: {datetime.now().isoformat(timespec='seconds')}"])
    w.writerow([])
    w.writerow(["-- Sensor Readings --"])
    w.writerow(["Timestamp", "Engine Temp (C)", "Battery (V)", "Tyre Pressure (psi)",
                "Brake Wear (%)", "Vibration (mm/s)", "Health Score"])
    for r in readings:
        w.writerow([r["ts"], r["engine_temp"], r["battery_volt"], r["tyre_pressure"],
                    r["brake_wear"], r["vibration"], r["health_score"]])
    w.writerow([])
    w.writerow(["-- Alerts --"])
    w.writerow(["Timestamp", "Severity", "Message"])
    for a in alerts:
        w.writerow([a["ts"], a["severity"], a["message"]])
    w.writerow([])
    w.writerow(["-- Service History --"])
    w.writerow(["Timestamp", "Service Type", "Notes"])
    for s in service:
        w.writerow([s["ts"], s["service_type"], s["notes"]])

    filename = f"{v['name'].replace(' ', '_')}_report.csv"
    return Response(
        buf.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ---------------------------------------------------------------------------
# API: settings & alert badge
# ---------------------------------------------------------------------------

@app.route("/api/settings", methods=["GET"])
@login_required
def api_get_settings():
    return jsonify(THRESHOLDS)


@app.route("/api/settings", methods=["POST"])
@login_required
def api_save_settings():
    global THRESHOLDS
    data = request.get_json(silent=True) or {}
    updated = json.loads(json.dumps(THRESHOLDS))  # deep copy
    for sensor, fields in data.items():
        if sensor not in updated:
            continue
        for field, value in fields.items():
            if field in updated[sensor] and field != "unit":
                try:
                    updated[sensor][field] = float(value)
                except (TypeError, ValueError):
                    pass
    THRESHOLDS = updated
    conn = get_db()
    conn.execute("UPDATE settings SET thresholds_json=? WHERE id=1", (json.dumps(THRESHOLDS),))
    conn.commit()
    return jsonify({"status": "saved", "thresholds": THRESHOLDS})


@app.route("/api/settings/reset", methods=["POST"])
@login_required
def api_reset_settings():
    global THRESHOLDS
    THRESHOLDS = json.loads(json.dumps(DEFAULT_THRESHOLDS))
    conn = get_db()
    conn.execute("UPDATE settings SET thresholds_json=? WHERE id=1", (json.dumps(THRESHOLDS),))
    conn.commit()
    return jsonify({"status": "reset", "thresholds": THRESHOLDS})


@app.route("/api/alerts/count")
@login_required
def api_alert_count():
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) c FROM alerts WHERE severity='critical' AND id > (SELECT COALESCE(MAX(id),0)-100 FROM alerts)"
    ).fetchone()
    return jsonify({"critical_count": row["c"] if row else 0})


if __name__ == "__main__":
    init_db()
    t = threading.Thread(target=background_simulator, daemon=True)
    t.start()
    app.run(debug=False, host="127.0.0.1", port=5000)
