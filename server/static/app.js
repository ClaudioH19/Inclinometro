const deviceSelect = document.getElementById("deviceSelect");
const trialSelect = document.getElementById("trialSelect");
const rpmAxis = document.getElementById("rpmAxis");
const receivedAfter = document.getElementById("receivedAfter");
const receivedBefore = document.getElementById("receivedBefore");
const metricsGrid = document.getElementById("metricsGrid");
const metricsStatus = document.getElementById("metricsStatus");
const samplesTable = document.querySelector("#samplesTable tbody");
const samplesStatus = document.getElementById("samplesStatus");
const trialsTable = document.querySelector("#trialsTable tbody");
const trialLabelInput = document.getElementById("trialLabelInput");
const rawDownload = document.getElementById("rawDownload");
const metricsDownload = document.getElementById("metricsDownload");
const resetDatabaseButton = document.getElementById("resetDatabase");

let trialsCache = [];
let sampleOffset = 0;
const sampleLimit = 100;

function toQueryString(params) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== "" && value !== null && value !== undefined) {
      query.set(key, value);
    }
  });
  return query.toString();
}

function currentFilters() {
  return {
    device_id: deviceSelect.value || "",
    trial_id: trialSelect.value || "",
    rpm_axis: rpmAxis.value,
    received_after: receivedAfter.value ? new Date(receivedAfter.value).toISOString() : "",
    received_before: receivedBefore.value ? new Date(receivedBefore.value).toISOString() : "",
  };
}

function updateDownloadLinks() {
  const query = toQueryString(currentFilters());
  rawDownload.href = `/api/download/raw.csv?${query}`;
  metricsDownload.href = `/api/download/metrics.csv?${query}`;
}

function metricCard(label, value) {
  return `<article class="metric"><small>${label}</small><strong>${value}</strong></article>`;
}

function formatNumber(value, digits = 3) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return Number(value).toFixed(digits);
}

async function loadDevices() {
  const devices = await fetch("/api/devices").then((response) => response.json());
  deviceSelect.innerHTML = `<option value="">Todos</option>` + devices
    .map((device) => `<option value="${device.device_id}">${device.device_id}</option>`)
    .join("");
}

async function loadTrials() {
  const currentTrialId = trialSelect.value;
  const query = deviceSelect.value ? `?device_id=${encodeURIComponent(deviceSelect.value)}` : "";
  trialsCache = await fetch(`/api/trials${query}`).then((response) => response.json());

  trialSelect.innerHTML = `<option value="">Todas</option>` + trialsCache
    .map((trial) => `<option value="${trial.id}">#${trial.trial_number} ${trial.label || ""}</option>`)
    .join("");

  if (trialsCache.some((trial) => String(trial.id) === currentTrialId)) {
    trialSelect.value = currentTrialId;
  }

  trialsTable.innerHTML = trialsCache
    .map(
      (trial) => `
        <tr>
          <td>${trial.id}</td>
          <td>${trial.trial_number}</td>
          <td>${trial.label || "-"}</td>
          <td>${trial.started_at}</td>
          <td>${trial.ended_at}</td>
          <td>${trial.batch_count}</td>
          <td>${trial.sample_count}</td>
        </tr>
      `,
    )
    .join("");

  const selectedTrial = trialsCache.find((trial) => String(trial.id) === trialSelect.value);
  trialLabelInput.value = selectedTrial?.label || "";
}

async function loadMetrics() {
  const query = toQueryString(currentFilters());
  const metrics = await fetch(`/api/metrics?${query}`).then((response) => response.json());

  if (!metrics.sample_count) {
    metricsGrid.innerHTML = metricCard("Estado", metrics.message || "Sin datos");
    metricsStatus.textContent = "No hay datos para este filtro.";
    return;
  }

  metricsStatus.textContent = `${metrics.sample_count} muestras en ${metrics.trial_count} prueba(s).`;
  metricsGrid.innerHTML = [
    metricCard("Gravedad residual", `${formatNumber(metrics.residual_gravity_g)} g`),
    metricCard("RPM media", formatNumber(metrics.rpm_mean)),
    metricCard("RPM maxima", formatNumber(metrics.rpm_max)),
    metricCard("Velocidad angular media", `${formatNumber(metrics.angular_speed_dps_mean)} dps`),
    metricCard("Aceleracion media", `${formatNumber(metrics.accel_magnitude_g_mean)} g`),
    metricCard("Horas de operacion", formatNumber(metrics.operation_hours)),
    metricCard("Pitch medio", `${formatNumber(metrics.pitch_deg_mean)} deg`),
    metricCard("Roll medio", `${formatNumber(metrics.roll_deg_mean)} deg`),
    metricCard("Vector medio ax", `${formatNumber(metrics.mean_ax_g)} g`),
    metricCard("Vector medio ay", `${formatNumber(metrics.mean_ay_g)} g`),
    metricCard("Vector medio az", `${formatNumber(metrics.mean_az_g)} g`),
    metricCard("Residual g*h", formatNumber(metrics.residual_gravity_g_hours)),
  ].join("");
}

async function loadSamples() {
  const query = toQueryString({ ...currentFilters(), limit: sampleLimit, offset: sampleOffset });
  const payload = await fetch(`/api/samples?${query}`).then((response) => response.json());
  samplesStatus.textContent = `${payload.total} filas. Mostrando ${payload.items.length} desde offset ${payload.offset}.`;
  samplesTable.innerHTML = payload.items
    .map(
      (sample) => `
        <tr>
          <td>${sample.device_id}</td>
          <td>${sample.trial_number}</td>
          <td>${sample.trial_label || "-"}</td>
          <td>${sample.batch_id}</td>
          <td>${sample.sample_index}</td>
          <td>${sample.sample_time_us}</td>
          <td>${sample.received_at}</td>
          <td>${sample.accel_x_raw}</td>
          <td>${sample.accel_y_raw}</td>
          <td>${sample.accel_z_raw}</td>
          <td>${sample.gyro_x_raw}</td>
          <td>${sample.gyro_y_raw}</td>
          <td>${sample.gyro_z_raw}</td>
        </tr>
      `,
    )
    .join("");
}

async function refreshAll() {
  await loadTrials();
  updateDownloadLinks();
  await Promise.all([loadMetrics(), loadSamples()]);
}

document.getElementById("applyFilters").addEventListener("click", async () => {
  sampleOffset = 0;
  await refreshAll();
});

deviceSelect.addEventListener("change", async () => {
  sampleOffset = 0;
  await refreshAll();
});

trialSelect.addEventListener("change", async () => {
  const selectedTrial = trialsCache.find((trial) => String(trial.id) === trialSelect.value);
  trialLabelInput.value = selectedTrial?.label || "";
  updateDownloadLinks();
  sampleOffset = 0;
  await Promise.all([loadMetrics(), loadSamples()]);
});

document.getElementById("prevPage").addEventListener("click", async () => {
  sampleOffset = Math.max(sampleOffset - sampleLimit, 0);
  await loadSamples();
});

document.getElementById("nextPage").addEventListener("click", async () => {
  sampleOffset += sampleLimit;
  await loadSamples();
});

document.getElementById("saveTrialLabel").addEventListener("click", async () => {
  if (!trialSelect.value) {
    return;
  }
  await fetch(`/api/trials/${trialSelect.value}/label`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ label: trialLabelInput.value }),
  });
  await loadTrials();
});

resetDatabaseButton.addEventListener("click", async () => {
  const confirmed = window.confirm("Esto borrara todas las pruebas y muestras. Continuar?");
  if (!confirmed) {
    return;
  }

  await fetch("/api/admin/reset", { method: "POST" });
  trialLabelInput.value = "";
  sampleOffset = 0;
  await loadDevices();
  await refreshAll();
});

async function boot() {
  await loadDevices();
  await refreshAll();
}

boot();
