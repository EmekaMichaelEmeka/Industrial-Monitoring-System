const SITE_ID = new URLSearchParams(window.location.search).get("site") || "WH-001";
const MQTT_HOST = new URLSearchParams(window.location.search).get("mqtt") || "ws://localhost:9001";
const BASE_TOPIC = `wellhead/${SITE_ID}`;
const MAX_POINTS = 60;

const sensorMeta = {
  pressure: { label: "Pressure", color: "#60a5fa" },
  temperature: { label: "Temperature", color: "#f97316" },
  flow_rate: { label: "Flow Rate", color: "#34d399" },
  vibration: { label: "Vibration", color: "#c084fc" },
};

const statusBanner = document.getElementById("status-banner");
const overallStatusText = document.getElementById("overall-status-text");
const connectionStatus = document.getElementById("connection-status");
const lastUpdate = document.getElementById("last-update");
const sensorCards = document.getElementById("sensor-cards");
const alertFeed = document.getElementById("alert-feed");
const siteIdEl = document.getElementById("site-id");

siteIdEl.textContent = SITE_ID;

const history = {
  labels: [],
  pressure: [],
  temperature: [],
  flow_rate: [],
  vibration: [],
};

const chart = new Chart(document.getElementById("trend-chart"), {
  type: "line",
  data: {
    labels: history.labels,
    datasets: Object.entries(sensorMeta).map(([key, meta]) => ({
      label: meta.label,
      data: history[key],
      borderColor: meta.color,
      backgroundColor: `${meta.color}33`,
      tension: 0.25,
      pointRadius: 0,
      borderWidth: 2,
    })),
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { labels: { color: "#cbd5e1" } },
    },
    scales: {
      x: {
        ticks: { color: "#8ea0c5", maxTicksLimit: 8 },
        grid: { color: "rgba(255,255,255,0.05)" },
      },
      y: {
        ticks: { color: "#8ea0c5" },
        grid: { color: "rgba(255,255,255,0.05)" },
      },
    },
  },
});

function renderSensorCards(sensors) {
  sensorCards.innerHTML = Object.entries(sensors)
    .map(([name, reading]) => {
      const meta = sensorMeta[name] || { label: name };
      return `
        <article class="sensor-card">
          <h3>${meta.label}</h3>
          <div class="sensor-value">
            ${reading.value}
            <span class="sensor-unit">${reading.unit}</span>
          </div>
          <span class="sensor-status ${reading.status}">${reading.status.toUpperCase()}</span>
        </article>
      `;
    })
    .join("");
}

function pushHistory(timestamp, sensors) {
  const label = new Date(timestamp).toLocaleTimeString();
  history.labels.push(label);
  for (const key of Object.keys(sensorMeta)) {
    history[key].push(sensors[key]?.value ?? null);
    if (history[key].length > MAX_POINTS) history[key].shift();
  }
  if (history.labels.length > MAX_POINTS) history.labels.shift();
  chart.update("none");
}

function setOverallStatus(status, anomalyType) {
  statusBanner.className = `status-banner ${status}`;
  const messages = {
    normal: "All sensors within safe operating thresholds",
    warning: "One or more sensors approaching threshold limits",
    critical: "Critical threshold exceeded — check alerts immediately",
  };
  let text = messages[status] || status;
  if (anomalyType) text += ` (${anomalyType.replaceAll("_", " ")})`;
  overallStatusText.textContent = text;
}

function prependAlert(alert) {
  const item = document.createElement("li");
  item.className = `alert-item ${alert.severity}`;
  item.innerHTML = `
    <div class="time">${new Date(alert.timestamp).toLocaleString()}</div>
    <div class="message">${alert.message}</div>
    <div class="meta">${alert.sensor} · ${alert.event} · ${alert.value} ${alert.unit}</div>
  `;
  alertFeed.prepend(item);
  while (alertFeed.children.length > 25) {
    alertFeed.removeChild(alertFeed.lastChild);
  }
}

function handleTelemetry(payload) {
  lastUpdate.textContent = new Date(payload.timestamp).toLocaleString();
  renderSensorCards(payload.sensors);
  pushHistory(payload.timestamp, payload.sensors);
  setOverallStatus(payload.overall_status, payload.anomaly_type);
}

function setConnection(online) {
  connectionStatus.textContent = online ? "MQTT Connected" : "Disconnected";
  connectionStatus.className = `badge ${online ? "badge-online" : "badge-offline"}`;
}

const client = mqtt.connect(MQTT_HOST, {
  clean: true,
  reconnectPeriod: 2000,
});

client.on("connect", () => {
  setConnection(true);
  client.subscribe(`${BASE_TOPIC}/telemetry`);
  client.subscribe(`${BASE_TOPIC}/alerts`);
});

client.on("reconnect", () => setConnection(false));
client.on("close", () => setConnection(false));
client.on("error", () => setConnection(false));

client.on("message", (topic, buffer) => {
  try {
    const payload = JSON.parse(buffer.toString());
    if (topic.endsWith("/telemetry")) {
      handleTelemetry(payload);
    } else if (topic.endsWith("/alerts")) {
      prependAlert(payload);
    }
  } catch (error) {
    console.error("Invalid MQTT payload", error);
  }
});
