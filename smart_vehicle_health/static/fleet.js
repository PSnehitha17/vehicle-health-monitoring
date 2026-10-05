let allVehicles = [];

function scoreClass(score) {
  if (score === null || score === undefined) return "";
  if (score >= 80) return "ok";
  if (score >= 55) return "warn";
  return "bad";
}

function renderFleet(vehicles) {
  const grid = document.getElementById("fleet-grid");
  grid.innerHTML = "";
  if (vehicles.length === 0) {
    grid.innerHTML = `<p class="muted">No vehicles match your search.</p>`;
    return;
  }
  vehicles.forEach((v) => {
    const cls = scoreClass(v.health_score);
    const card = document.createElement("a");
    card.href = `/vehicle/${v.id}`;
    card.className = "fleet-card";
    card.innerHTML = `
      <div class="fleet-card-top">
        <span class="fleet-score ${cls}">${v.health_score !== null ? v.health_score : "--"}</span>
        <span class="fleet-score-label">Health Score</span>
      </div>
      <div class="fleet-card-name">${v.name}</div>
      <div class="fleet-card-status ${cls}">
        ${cls === "ok" ? "Healthy" : cls === "warn" ? "Needs attention" : cls === "bad" ? "Critical" : "No data yet"}
      </div>
    `;
    grid.appendChild(card);
  });
}

async function loadFleet() {
  try {
    const res = await fetch("/api/vehicles");
    if (res.status === 401) { window.location = "/login"; return; }
    allVehicles = await res.json();
    // worst health first, so problems surface immediately
    allVehicles.sort((a, b) => (a.health_score ?? 999) - (b.health_score ?? 999));
    applySearch();
  } catch (e) {
    console.error("Failed to load fleet", e);
  }
}

function applySearch() {
  const q = document.getElementById("search-box").value.trim().toLowerCase();
  const filtered = q ? allVehicles.filter((v) => v.name.toLowerCase().includes(q)) : allVehicles;
  renderFleet(filtered);
}

function openModal() { document.getElementById("add-modal").classList.add("open"); }
function closeModal() {
  document.getElementById("add-modal").classList.remove("open");
  document.getElementById("new-vehicle-name").value = "";
}

async function submitAddVehicle() {
  const name = document.getElementById("new-vehicle-name").value.trim();
  const condition = document.getElementById("new-vehicle-condition").value;
  if (!name) { alert("Please enter a vehicle name."); return; }
  const btn = document.getElementById("confirm-add");
  btn.disabled = true;
  btn.textContent = "Adding…";
  try {
    const res = await fetch("/api/vehicles", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, condition }),
    });
    if (!res.ok) {
      const err = await res.json();
      alert(err.error || "Failed to add vehicle.");
      return;
    }
    closeModal();
    loadFleet();
  } catch (e) {
    alert("Failed to add vehicle.");
  } finally {
    btn.disabled = false;
    btn.textContent = "Add Vehicle";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  loadFleet();
  setInterval(loadFleet, 4000);
  document.getElementById("search-box").addEventListener("input", applySearch);
  document.getElementById("open-add-modal").addEventListener("click", openModal);
  document.getElementById("cancel-add").addEventListener("click", closeModal);
  document.getElementById("confirm-add").addEventListener("click", submitAddVehicle);
  document.getElementById("add-modal").addEventListener("click", (e) => {
    if (e.target.id === "add-modal") closeModal();
  });
});
