const sessionSelect = document.getElementById("sessionSelect");
const receivedAfter = document.getElementById("receivedAfter");
const receivedBefore = document.getElementById("receivedBefore");
const limitSelect = document.getElementById("limitSelect");
const metricsGrid = document.getElementById("metricsGrid");
const metricsStatus = document.getElementById("metricsStatus");
const sessionsTable = document.querySelector("#sessionsTable tbody");
const samplesTable = document.querySelector("#samplesTable tbody");
const samplesStatus = document.getElementById("samplesStatus");
const rawDownload = document.getElementById("rawDownload");
const metricsDownload = document.getElementById("metricsDownload");
const resetDatabaseButton = document.getElementById("resetDatabase");

const ACCEL_LSB_PER_G = 8192.0;
const GYRO_LSB_PER_DPS = 65.5;
const DASHBOARD_REFRESH_MS = 5000;

let sampleOffset = 0;
let sessionCache = [];

function queryFrom(params) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== "" && value !== null && value !== undefined) {
      query.set(key, value);
    }
  });
  return query.toString();
}

function activeFilters() {
  return {
    session_id: sessionSelect.value || "",
    received_after: receivedAfter.value ? new Date(receivedAfter.value).toISOString() : "",
    received_before: receivedBefore.value ? new Date(receivedBefore.value).toISOString() : "",
  };
}

function asNumber(value, digits = 3) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return Number(value).toFixed(digits);
}

function metric(label, value) {
  return `<article class="metric"><small>${label}</small><strong>${value}</strong></article>`;
}

function updateDownloads() {
  const query = queryFrom(activeFilters());
  rawDownload.href = `/api/download/raw.csv?${query}`;
  metricsDownload.href = `/api/download/metrics.csv?${query}`;
}

function derivedValues(row) {
  const ax = row.accel_x_raw / ACCEL_LSB_PER_G;
  const ay = row.accel_y_raw / ACCEL_LSB_PER_G;
  const az = row.accel_z_raw / ACCEL_LSB_PER_G;
  const gxDps = row.gyro_x_raw / GYRO_LSB_PER_DPS;
  const gyDps = row.gyro_y_raw / GYRO_LSB_PER_DPS;
  const gzDps = row.gyro_z_raw / GYRO_LSB_PER_DPS;
  return {
    accelG: Math.sqrt(ax * ax + ay * ay + az * az),
    pitchDeg: (Math.atan2(-ax, Math.sqrt(ay * ay + az * az)) * 180.0) / Math.PI,
    rollDeg: (Math.atan2(ay, az) * 180.0) / Math.PI,
    rpm: Math.abs(gzDps) / 6.0,
  };
}

async function loadSessions() {
  const current = sessionSelect.value;
  sessionCache = await fetch("/api/sessions").then((response) => response.json());
  sessionSelect.innerHTML = '<option value="">Todas</option>' + sessionCache
    .map((session) => `<option value="${session.session_id}">${session.session_id}</option>`)
    .join("");

  if (sessionCache.some((session) => session.session_id === current)) {
    sessionSelect.value = current;
  }

  sessionsTable.innerHTML = sessionCache
    .map(
      (session) => `
        <tr>
          <td>${session.session_id}</td>
          <td>${session.batch_count}</td>
          <td>${session.sample_count}</td>
          <td>${session.first_sample_time_us}</td>
          <td>${session.last_sample_time_us}</td>
          <td>${session.first_received_at}</td>
          <td>${session.last_received_at}</td>
        </tr>
      `,
    )
    .join("");
}

async function loadMetrics() {
  const metrics = await fetch(`/api/metrics?${queryFrom(activeFilters())}`).then((response) => response.json());
  if (!metrics.sample_count) {
    metricsStatus.textContent = "No hay datos para este filtro.";
    metricsGrid.innerHTML = metric("Estado", metrics.message || "Sin datos");
    return;
  }

  metricsStatus.textContent = `${metrics.sample_count} muestras | ${metrics.session_count} sesiones | refresco panel cada ${DASHBOARD_REFRESH_MS / 1000}s`;
  metricsGrid.innerHTML = [
    metric("Tasa de muestreo (Hz)", asNumber(metrics.sample_rate_hz, 2)),
    metric("Periodo de muestra (ms)", asNumber(metrics.sample_period_ms, 2)),
    metric("RPM estimada media", asNumber(metrics.rpm_mean, 2)),
    metric("Gravedad residual (g)", asNumber(metrics.residual_gravity_g, 4)),
    metric("Aceleracion media (g)", asNumber(metrics.accel_magnitude_g_mean, 4)),
    metric("Horas de operacion", asNumber(metrics.operation_hours, 3)),
    metric("Pitch medio (deg)", asNumber(metrics.pitch_deg_mean, 2)),
    metric("Roll medio (deg)", asNumber(metrics.roll_deg_mean, 2)),
  ].join("");
}

async function loadSamples() {
  const limit = Number(limitSelect.value || 100);
  const query = queryFrom({ ...activeFilters(), limit, offset: sampleOffset });
  const payload = await fetch(`/api/samples?${query}`).then((response) => response.json());
  samplesStatus.textContent = `${payload.total} filas totales | mostrando ${payload.items.length} | offset ${payload.offset}`;

  samplesTable.innerHTML = payload.items
    .map((row) => {
      const calc = derivedValues(row);
      return `
        <tr>
          <td>${row.id}</td>
          <td>${row.session_id}</td>
          <td>${row.batch_id}</td>
          <td>${row.sample_index}</td>
          <td>${row.sample_time_us}</td>
          <td>${row.received_at}</td>
          <td>${row.accel_x_raw}</td>
          <td>${row.accel_y_raw}</td>
          <td>${row.accel_z_raw}</td>
          <td>${row.gyro_x_raw}</td>
          <td>${row.gyro_y_raw}</td>
          <td>${row.gyro_z_raw}</td>
          <td>${asNumber(calc.accelG, 4)}</td>
          <td>${asNumber(calc.pitchDeg, 2)}</td>
          <td>${asNumber(calc.rollDeg, 2)}</td>
          <td>${asNumber(calc.rpm, 2)}</td>
        </tr>
      `;
    })
    .join("");
}

async function refreshAll() {
  await loadSessions();
  updateDownloads();
  await Promise.all([loadMetrics(), loadSamples()]);
}

document.getElementById("applyFilters").addEventListener("click", async () => {
  sampleOffset = 0;
  await refreshAll();
});

sessionSelect.addEventListener("change", async () => {
  sampleOffset = 0;
  updateDownloads();
  await Promise.all([loadMetrics(), loadSamples()]);
});

limitSelect.addEventListener("change", async () => {
  sampleOffset = 0;
  await loadSamples();
});

document.getElementById("prevPage").addEventListener("click", async () => {
  const limit = Number(limitSelect.value || 100);
  sampleOffset = Math.max(sampleOffset - limit, 0);
  await loadSamples();
});

document.getElementById("nextPage").addEventListener("click", async () => {
  const limit = Number(limitSelect.value || 100);
  sampleOffset += limit;
  await loadSamples();
});

resetDatabaseButton.addEventListener("click", async () => {
  if (!window.confirm("Esto borrara todos los datos. Continuar?")) {
    return;
  }
  await fetch("/api/admin/reset", { method: "POST" });
  sampleOffset = 0;
  await refreshAll();
});

refreshAll();
setInterval(async () => {
  await Promise.all([loadMetrics(), loadSamples(), loadSessions()]);
}, DASHBOARD_REFRESH_MS);
