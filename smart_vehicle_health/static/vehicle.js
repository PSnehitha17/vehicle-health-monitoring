const SENSOR_META = {
  engine_temp:   { label: "Engine Temperature", unit: "°C" },
  battery_volt:  { label: "Battery Voltage",    unit: "V" },
  tyre_pressure: { label: "Tyre Pressure",      unit: "psi" },
  brake_wear:    { label: "Brake Wear",         unit: "%" },
  vibration:     { label: "Vibration",          unit: "mm/s" },
};

const RING_CIRC = 2 * Math.PI * 52;
let currentThresholds = null;

function scoreColor(score) {
  if (score >= 80) return "var(--good)";
  if (score >= 55) return "var(--warn)";
  return "var(--bad)";
}

function sensorStatus(key, value) {
  if (!currentThresholds) return "ok";
  const t = currentThresholds[key];
  if (!t) return "ok";
  if (key === "engine_temp" || key === "brake_wear" || key === "vibration") {
    const crit = t.critical;
    if (value > crit) return "bad";
    if (value > t.max) return "warn";
    return "ok";
  }
  if (key === "battery_volt" || key === "tyre_pressure") {
    const critLow = t.critical_low;
    if (value < critLow) return "bad";
    if (value < t.min) return "warn";
    return "ok";
  }
  return "ok";
}

function renderSensors(latest) {
  const grid = document.getElementById("sensor-grid");
  grid.innerHTML = "";
  Object.keys(SENSOR_META).forEach((key) => {
    const meta = SENSOR_META[key];
    const val = latest ? latest[key] : null;
    const status = val !== null ? sensorStatus(key, val) : "ok";
    const div = document.createElement("div");
    div.className = "sensor-card";
    div.innerHTML = `
      <div class="label">${meta.label}</div>
      <div class="value ${status}">${val !== null ? val.toFixed(1) : "--"} ${meta.unit}</div>
    `;
    grid.appendChild(div);
  });
}

function renderScore(score) {
  const valueEl = document.getElementById("score-value");
  const statusEl = document.getElementById("score-status");
  const ring = document.getElementById("ring-fg");

  if (score === null || score === undefined) {
    valueEl.textContent = "--";
    statusEl.textContent = "Loading sensor data…";
    return;
  }
  valueEl.textContent = score;
  ring.style.strokeDashoffset = RING_CIRC - (score / 100) * RING_CIRC;
  ring.style.stroke = scoreColor(score);

  if (score >= 80) statusEl.textContent = "Vehicle healthy — no action needed.";
  else if (score >= 55) statusEl.textContent = "Minor issues detected — schedule a checkup soon.";
  else statusEl.textContent = "Attention needed — service recommended immediately.";
}

function renderAlerts(alerts) {
  const list = document.getElementById("alerts-list");
  list.innerHTML = "";
  if (!alerts || alerts.length === 0) {
    list.innerHTML = `<li class="alert-empty">No alerts — vehicle is healthy.</li>`;
    return;
  }
  alerts.forEach((a) => {
    const li = document.createElement("li");
    li.className = a.severity;
    li.innerHTML = `${a.message}<span class="ts">${a.ts} · ${a.severity.toUpperCase()}</span>`;
    list.appendChild(li);
  });
}

function renderServiceLog(entries) {
  const list = document.getElementById("service-list");
  list.innerHTML = "";
  if (!entries || entries.length === 0) {
    list.innerHTML = `<li class="alert-empty">No service records yet.</li>`;
    return;
  }
  entries.forEach((s) => {
    const li = document.createElement("li");
    li.className = "info";
    li.innerHTML = `${s.service_type}${s.notes ? " — " + s.notes : ""}<span class="ts">${s.ts}</span>`;
    list.appendChild(li);
  });
}

function renderTrend(history) {
  const canvas = document.getElementById("trend-canvas");
  const ctx = canvas.getContext("2d");
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  if (!history || history.length < 2) return;

  const scores = history.map((r) => r.health_score);
  const padX = 10, padY = 14;
  const stepX = (w - padX * 2) / (scores.length - 1);

  ctx.strokeStyle = "#262f45";
  ctx.lineWidth = 1;
  [0, 25, 50, 75, 100].forEach((v) => {
    const y = h - padY - (v / 100) * (h - padY * 2);
    ctx.beginPath();
    ctx.moveTo(padX, y);
    ctx.lineTo(w - padX, y);
    ctx.stroke();
  });

  ctx.strokeStyle = "#3fb6ff";
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  scores.forEach((s, i) => {
    const x = padX + i * stepX;
    const y = h - padY - (s / 100) * (h - padY * 2);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();

  ctx.lineTo(padX + (scores.length - 1) * stepX, h - padY);
  ctx.lineTo(padX, h - padY);
  ctx.closePath();
  ctx.fillStyle = "rgba(63,182,255,0.12)";
  ctx.fill();
}

async function fetchVehicle() {
  try {
    const res = await fetch(`/api/vehicle/${VEHICLE_ID}`);
    if (res.status === 401) { window.location = "/login"; return; }
    const data = await res.json();
    currentThresholds = data.thresholds;
    renderScore(data.latest ? data.latest.health_score : null);
    renderSensors(data.latest);
    renderAlerts(data.alerts);
    renderServiceLog(data.service_log);
    renderTrend(data.history);
    document.getElementById("prediction-box").textContent = "Predicted maintenance: " + data.prediction;
  } catch (e) {
    console.error("Failed to fetch vehicle data", e);
  }
}

async function logService() {
  const type = document.getElementById("service-type").value;
  const notes = document.getElementById("service-notes").value.trim();
  const btn = document.getElementById("log-service-btn");
  btn.disabled = true;
  btn.textContent = "Logging…";
  try {
    const res = await fetch(`/api/vehicle/${VEHICLE_ID}/service`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type, notes }),
    });
    if (res.ok) {
      document.getElementById("service-notes").value = "";
      fetchVehicle();
    } else {
      alert("Failed to log service.");
    }
  } finally {
    btn.disabled = false;
    btn.textContent = "Log Service";
  }
}

async function deleteVehicle() {
  if (!confirm("Delete this vehicle and all its history? This cannot be undone.")) return;
  const res = await fetch(`/api/vehicle/${VEHICLE_ID}`, { method: "DELETE" });
  if (res.ok) window.location = "/";
  else alert("Failed to delete vehicle.");
}

document.addEventListener("DOMContentLoaded", () => {
  fetchVehicle();
  setInterval(fetchVehicle, 3000);
  document.getElementById("log-service-btn").addEventListener("click", logService);
  document.getElementById("delete-vehicle").addEventListener("click", deleteVehicle);
});
