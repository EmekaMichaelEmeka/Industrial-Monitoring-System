# Industrial Monitoring System

Simulated wellhead / pipeline monitoring with realistic sensor telemetry, MQTT streaming, threshold alerts, and a real-time dashboard.

## Architecture

```text
┌─────────────────────┐     MQTT (1883)      ┌──────────────────┐
│  Sensor Simulator   │ ───────────────────► │    Mosquitto     │
│  (Python or C++)    │                      │  + WebSocket     │
└─────────────────────┘                      │    (9001)        │
                                             └────────┬─────────┘
                                                      │
                        ┌─────────────────────────────┼─────────────────────────────┐
                        ▼                             ▼                             ▼
               ┌────────────────┐           ┌─────────────────┐           ┌─────────────────┐
               │ Web Dashboard  │           │    Node-RED     │           │ Grafana (opt.)  │
               │  localhost:8080│           │  import flow    │           │ MQTT datasource │
               └────────────────┘           └─────────────────┘           └─────────────────┘
```

## Sensors

| Sensor      | Typical range | Warning threshold | Critical threshold |
|-------------|-----------------|-------------------|--------------------|
| Pressure    | ~850–900 psi    | ≥ 920 psi         | ≥ 950 psi          |
| Temperature | ~64–72 °C       | ≥ 82 °C           | ≥ 88 °C            |
| Flow rate   | ~1100–1250 bbl/d| ≤900 or ≥1450     | ≤750 or ≥1600      |
| Vibration   | ~2.5–4.5 mm/s   | ≥ 7.5 mm/s        | ≥ 10 mm/s          |

The Python simulator injects random anomalies (~2% of samples) such as pressure surges, flow drops, vibration spikes, and overheating events.

## MQTT topics

| Topic | Payload |
|-------|---------|
| `wellhead/WH-001/telemetry` | Aggregated JSON with all sensors |
| `wellhead/WH-001/sensors/{pressure\|temperature\|flow_rate\|vibration}` | Individual sensor reading |
| `wellhead/WH-001/alerts` | Threshold alert events (triggered / cleared) |

Example telemetry:

```json
{
  "site_id": "WH-001",
  "site_name": "North Ridge Wellhead",
  "timestamp": "2026-07-03T19:30:00Z",
  "overall_status": "warning",
  "sensors": {
    "pressure": { "value": 928.4, "unit": "psi", "status": "warning" }
  }
}
```

Example alert:

```json
{
  "sensor": "pressure",
  "event": "triggered",
  "severity": "critical",
  "value": 956.2,
  "unit": "psi",
  "message": "Pressure exceeds safe limit — immediate action required"
}
```

## Quick start

### 1. Start MQTT broker and dashboard

```bash
cd industrial-monitor
docker compose up -d
```

- MQTT broker: `localhost:1883`
- MQTT WebSocket: `ws://localhost:9001`
- Dashboard: http://localhost:8080

### 2. Run the Python simulator (recommended)

```bash
cd simulator
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
python sensor_simulator.py
```

Open http://localhost:8080 and watch live sensor cards, trend charts, and alert feed.

### 3. Optional: C++ simulator

Requires CMake 3.16+ and a C++17 compiler.

```bash
cd simulator-cpp
cmake -B build
cmake --build build

# Windows
build\Debug\wellhead_simulator.exe

# Linux / macOS
./build/wellhead_simulator
```

Only run **one** simulator at a time (Python or C++) to avoid duplicate telemetry.

## Configuration

Edit `simulator/config.yaml` to change:

- MQTT broker host/port
- Sample interval and anomaly rate
- Baselines, noise, and thresholds per sensor

## Node-RED integration

1. Install [Node-RED](https://nodered.org/) and the `node-red-dashboard` / MQTT nodes.
2. Add an MQTT broker node pointing to `localhost:1883`.
3. Import `nodered/flows.json` via **Menu → Import**.
4. Deploy and open the debug sidebar to see sensor values and alerts.

## Grafana (optional)

Use the [MQTT datasource plugin](https://grafana.com/grafana/plugins/): subscribe to `wellhead/WH-001/telemetry` and map JSON fields (`sensors.pressure.value`, etc.) to time-series panels. Set alert rules on the same thresholds defined in `config.yaml`.

## Project layout

```text
industrial-monitor/
├── docker-compose.yml       # Mosquitto + nginx dashboard
├── mqtt/mosquitto.conf
├── simulator/               # Python simulator (primary)
│   ├── sensor_simulator.py
│   ├── config.yaml
│   └── requirements.txt
├── simulator-cpp/           # C++ alternative
├── dashboard/               # Real-time web UI
├── nodered/flows.json       # Optional Node-RED flow
└── README.md
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Dashboard shows "Disconnected" | Ensure `docker compose up` is running and port 9001 is free |
| No telemetry on dashboard | Start `sensor_simulator.py` after the broker is up |
| Alerts not appearing | Anomalies are probabilistic; wait ~30s or lower `anomaly_probability` in config |
| C++ build fails on network | CMake fetches Paho MQTT C from GitHub during configure |
