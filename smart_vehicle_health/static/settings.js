function collectThresholds() {
  const form = document.getElementById("settings-form");
  const inputs = form.querySelectorAll("input[name]");
  const out = {};
  inputs.forEach((inp) => {
    const [sensor, field] = inp.name.split("::");
    if (!out[sensor]) out[sensor] = {};
    out[sensor][field] = inp.value;
  });
  return out;
}

async function saveSettings() {
  const status = document.getElementById("settings-status");
  status.textContent = "Saving…";
  try {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectThresholds()),
    });
    if (res.ok) {
      status.textContent = "Saved ✓";
      setTimeout(() => (status.textContent = ""), 2500);
    } else {
      status.textContent = "Failed to save.";
    }
  } catch (e) {
    status.textContent = "Failed to save.";
  }
}

async function resetSettings() {
  if (!confirm("Reset all thresholds to defaults?")) return;
  const res = await fetch("/api/settings/reset", { method: "POST" });
  if (res.ok) window.location.reload();
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("save-settings").addEventListener("click", (e) => {
    e.preventDefault();
    saveSettings();
  });
  document.getElementById("reset-settings").addEventListener("click", (e) => {
    e.preventDefault();
    resetSettings();
  });
});
