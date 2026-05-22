const sessionSelect = document.getElementById("sessionSelect");
const rpmAxis = document.getElementById("rpmAxis");
const receivedAfter = document.getElementById("receivedAfter");
const receivedBefore = document.getElementById("receivedBefore");
const metricsGrid = document.getElementById("metricsGrid");
const metricsStatus = document.getElementById("metricsStatus");
const sessionsTable = document.querySelector("#sessionsTable tbody");
const samplesTable = document.querySelector("#samplesTable tbody");
const samplesStatus = document.getElementById("samplesStatus");
const rawDownload = document.getElementById("rawDownload");
const metricsDownload = document.getElementById("metricsDownload");
const resetDatabaseButton = document.getElementById("resetDatabase");

let sampleOffset = 0;
const sampleLimit = 100;
let sessionsCache = [];

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
    rpm_axis: rpmAxis.value,
    received_after: receivedAfter.value ? new Date(receivedAfter.value).toISOString() : "",
    received_before: receivedBefore.value ? new Date(receivedBefore.value).toISOString() : "",
  };
}

function metric(label, value) {
  return `<article class="metric"><small>${label}</small><strong>${value}</strong></article>`;
}

function asNumber(value, digits = 3) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return Number(value).toFixed(digits);
}

function updateDownloads() {
  const query = queryFrom(activeFilters());
  rawDownload.href = `/api/download/raw.csv?${query}`;
  metricsDownload.href = `/api/download/metrics.csv?${query}`;
}

async function loadSessions() {
  const current = sessionSelect.value;
  sessionsCache = await fetch("/api/sessions").then((response) => response.json());
  sessionSelect.innerHTML = '<option value="">Todas</option>' + sessionsCache
    .map((session) => `<option value="${session.session_id}">${session.session_id}</option>`)
    .join("");
  if (sessionsCache.some((session) => session.session_id === current)) {
    sessionSelect.value = current;
  }

  sessionsTable.innerHTML = sessionsCache
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

  metricsStatus.textContent = `${metrics.sample_count} muestras en ${metrics.session_count} sesion(es). Horas calculadas con sample_time_us relativo por sesion.`;
  metricsGrid.innerHTML = [
    metric("Gravedad residual", `${asNumber(metrics.residual_gravity_g)} g`),
    metric("RPM media", asNumber(metrics.rpm_mean)),
    metric("RPM maxima", asNumber(metrics.rpm_max)),
    metric("Velocidad angular media", `${asNumber(metrics.angular_speed_dps_mean)} dps`),
    metric("Aceleracion media", `${asNumber(metrics.accel_magnitude_g_mean)} g`),
    metric("Horas de operacion", asNumber(metrics.operation_hours)),
    metric("Pitch medio", `${asNumber(metrics.pitch_deg_mean)} deg`),
    metric("Roll medio", `${asNumber(metrics.roll_deg_mean)} deg`),
    metric("Vector medio ax", `${asNumber(metrics.mean_ax_g)} g`),
    metric("Vector medio ay", `${asNumber(metrics.mean_ay_g)} g`),
    metric("Vector medio az", `${asNumber(metrics.mean_az_g)} g`),
    metric("Residual g*h", asNumber(metrics.residual_gravity_g_hours)),
  ].join("");
}

async function loadSamples() {
  const query = queryFrom({ ...activeFilters(), limit: sampleLimit, offset: sampleOffset });
  const payload = await fetch(`/api/samples?${query}`).then((response) => response.json());
  samplesStatus.textContent = `${payload.total} filas. Mostrando ${payload.items.length} desde offset ${payload.offset}.`;
  samplesTable.innerHTML = payload.items
    .map(
      (sample) => `
        <tr>
          <td>${sample.id}</td>
          <td>${sample.session_id}</td>
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

async function refresh() {
  await loadSessions();
  updateDownloads();
  await Promise.all([loadMetrics(), loadSamples()]);
}

document.getElementById("applyFilters").addEventListener("click", async () => {
  sampleOffset = 0;
  await refresh();
});

sessionSelect.addEventListener("change", async () => {
  sampleOffset = 0;
  updateDownloads();
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

resetDatabaseButton.addEventListener("click", async () => {
  if (!window.confirm("Esto borrara todos los datos. Continuar?")) {
    return;
  }
  await fetch("/api/admin/reset", { method: "POST" });
  sampleOffset = 0;
  await refresh();
});

refresh();
