#!/usr/bin/env python3
"""
Wellhead / pipeline sensor simulator.

Generates realistic pressure, temperature, flow rate, and vibration readings,
publishes telemetry over MQTT, and emits threshold-based alert events.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("Install dependencies: pip install -r requirements.txt", file=sys.stderr)
    raise


@dataclass
class Thresholds:
    warning: float | None = None
    critical: float | None = None
    low_warning: float | None = None
    low_critical: float | None = None
    high_warning: float | None = None
    high_critical: float | None = None


@dataclass
class SensorConfig:
    unit: str
    baseline: float
    noise: float
    thresholds: Thresholds
    drift_per_hour: float = 0.0
    diurnal_amplitude: float = 0.0
    pump_cycle_period: float = 0.0
    pump_cycle_amplitude: float = 0.0


@dataclass
class SimulatorState:
    start_time: float = field(default_factory=time.time)
    pressure_drift: float = 0.0
    anomaly_until: float = 0.0
    anomaly_type: str = ""
    last_alerts: dict[str, str] = field(default_factory=dict)


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SensorSimulator:
    def __init__(self, config: dict[str, Any]) -> None:
        self.site_id = config["site"]["id"]
        self.site_name = config["site"]["name"]
        self.site_type = config["site"]["type"]
        self.interval = float(config["simulation"]["interval_seconds"])
        self.anomaly_probability = float(config["simulation"]["anomaly_probability"])
        self.state = SimulatorState()

        raw = config["sensors"]
        self.sensors = {
            name: SensorConfig(
                unit=spec["unit"],
                baseline=float(spec["baseline"]),
                noise=float(spec["noise"]),
                thresholds=Thresholds(**spec.get("thresholds", {})),
                drift_per_hour=float(spec.get("drift_per_hour", 0.0)),
                diurnal_amplitude=float(spec.get("diurnal_amplitude", 0.0)),
                pump_cycle_period=float(spec.get("pump_cycle_period", 0.0)),
                pump_cycle_amplitude=float(spec.get("pump_cycle_amplitude", 0.0)),
            )
            for name, spec in raw.items()
        }

    def _elapsed(self) -> float:
        return time.time() - self.state.start_time

    def _maybe_trigger_anomaly(self) -> None:
        now = time.time()
        if now < self.state.anomaly_until:
            return
        if random.random() < self.anomaly_probability:
            self.state.anomaly_type = random.choice(
                ["pressure_surge", "flow_drop", "vibration_spike", "overheat"]
            )
            self.state.anomaly_until = now + random.uniform(8.0, 25.0)

    def _pressure(self, spec: SensorConfig) -> float:
        hours = self._elapsed() / 3600.0
        self.state.pressure_drift += spec.drift_per_hour * (self.interval / 3600.0)
        value = spec.baseline + self.state.pressure_drift
        value += math.sin(hours * 2 * math.pi / 6.0) * 8.0
        value += random.gauss(0.0, spec.noise)

        if self.state.anomaly_type == "pressure_surge" and time.time() < self.state.anomaly_until:
            value += random.uniform(60.0, 110.0)

        return round(max(0.0, value), 2)

    def _temperature(self, spec: SensorConfig) -> float:
        hours = self._elapsed() / 3600.0
        diurnal = spec.diurnal_amplitude * math.sin((hours - 6.0) * 2 * math.pi / 24.0)
        value = spec.baseline + diurnal + random.gauss(0.0, spec.noise)

        if self.state.anomaly_type == "overheat" and time.time() < self.state.anomaly_until:
            value += random.uniform(8.0, 18.0)

        return round(value, 2)

    def _flow_rate(self, spec: SensorConfig) -> float:
        elapsed = self._elapsed()
        cycle = 0.0
        if spec.pump_cycle_period > 0:
            cycle = spec.pump_cycle_amplitude * math.sin(
                elapsed * 2 * math.pi / spec.pump_cycle_period
            )
        value = spec.baseline + cycle + random.gauss(0.0, spec.noise)

        if self.state.anomaly_type == "flow_drop" and time.time() < self.state.anomaly_until:
            value -= random.uniform(250.0, 450.0)

        return round(max(0.0, value), 1)

    def _vibration(self, spec: SensorConfig) -> float:
        value = spec.baseline + random.gauss(0.0, spec.noise)
        value += abs(math.sin(self._elapsed() * 0.7)) * 0.4

        if self.state.anomaly_type == "vibration_spike" and time.time() < self.state.anomaly_until:
            value += random.uniform(4.0, 7.0)

        return round(max(0.0, value), 3)

    def generate_readings(self) -> dict[str, dict[str, Any]]:
        self._maybe_trigger_anomaly()
        generators = {
            "pressure": self._pressure,
            "temperature": self._temperature,
            "flow_rate": self._flow_rate,
            "vibration": self._vibration,
        }

        readings: dict[str, dict[str, Any]] = {}
        for name, generator in generators.items():
            spec = self.sensors[name]
            value = generator(spec)
            readings[name] = {
                "value": value,
                "unit": spec.unit,
                "status": self._evaluate_status(name, value, spec.thresholds),
            }
        return readings

    def _evaluate_status(self, name: str, value: float, thresholds: Thresholds) -> str:
        if name == "flow_rate":
            if thresholds.low_critical is not None and value <= thresholds.low_critical:
                return "critical"
            if thresholds.high_critical is not None and value >= thresholds.high_critical:
                return "critical"
            if thresholds.low_warning is not None and value <= thresholds.low_warning:
                return "warning"
            if thresholds.high_warning is not None and value >= thresholds.high_warning:
                return "warning"
            return "normal"

        if thresholds.critical is not None and value >= thresholds.critical:
            return "critical"
        if thresholds.warning is not None and value >= thresholds.warning:
            return "warning"
        return "normal"

    def build_telemetry(self, readings: dict[str, dict[str, Any]]) -> dict[str, Any]:
        overall = "normal"
        if any(r["status"] == "critical" for r in readings.values()):
            overall = "critical"
        elif any(r["status"] == "warning" for r in readings.values()):
            overall = "warning"

        payload = {
            "site_id": self.site_id,
            "site_name": self.site_name,
            "site_type": self.site_type,
            "timestamp": utc_iso(),
            "overall_status": overall,
            "anomaly_active": time.time() < self.state.anomaly_until,
            "anomaly_type": self.state.anomaly_type if time.time() < self.state.anomaly_until else None,
            "sensors": readings,
        }
        return payload

    def detect_alerts(self, readings: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        alerts: list[dict[str, Any]] = []
        for sensor, data in readings.items():
            status = data["status"]
            previous = self.state.last_alerts.get(sensor, "normal")

            if status != previous:
                self.state.last_alerts[sensor] = status
                if status == "normal":
                    alerts.append(self._alert_event(sensor, data, "cleared", previous))
                else:
                    alerts.append(self._alert_event(sensor, data, "triggered", status))

        return alerts

    def _alert_event(
        self,
        sensor: str,
        data: dict[str, Any],
        event: str,
        severity: str,
    ) -> dict[str, Any]:
        messages = {
            ("pressure", "triggered", "warning"): "Pressure approaching safe operating limit",
            ("pressure", "triggered", "critical"): "Pressure exceeds safe limit — immediate action required",
            ("temperature", "triggered", "warning"): "Wellhead temperature elevated",
            ("temperature", "triggered", "critical"): "Temperature exceeds safe limit — shutdown recommended",
            ("flow_rate", "triggered", "warning"): "Flow rate outside expected operating band",
            ("flow_rate", "triggered", "critical"): "Critical flow anomaly detected on pipeline",
            ("vibration", "triggered", "warning"): "Elevated vibration detected on pump assembly",
            ("vibration", "triggered", "critical"): "Critical vibration — mechanical fault likely",
        }
        message = messages.get(
            (sensor, event, severity),
            f"{sensor.replace('_', ' ').title()} alert {event}",
        )

        return {
            "site_id": self.site_id,
            "timestamp": utc_iso(),
            "sensor": sensor,
            "event": event,
            "severity": severity if event == "triggered" else "info",
            "value": data["value"],
            "unit": data["unit"],
            "message": message if event == "triggered" else f"{sensor.replace('_', ' ').title()} returned to normal",
        }


class MqttPublisher:
    def __init__(self, config: dict[str, Any]) -> None:
        mqtt_cfg = config["mqtt"]
        self.site_id = config["site"]["id"]
        self.base_topic = f"wellhead/{self.site_id}"
        self.qos = int(mqtt_cfg.get("qos", 1))

        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=mqtt_cfg.get("client_id", "wellhead-simulator"),
        )
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self._connected = False

        host = mqtt_cfg["host"]
        port = int(mqtt_cfg["port"])
        print(f"Connecting to MQTT broker at {host}:{port}...")
        self.client.connect(host, port, keepalive=60)
        self.client.loop_start()

        deadline = time.time() + 10.0
        while not self._connected and time.time() < deadline:
            time.sleep(0.1)
        if not self._connected:
            raise RuntimeError("Failed to connect to MQTT broker within 10 seconds")

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        if reason_code == 0:
            self._connected = True
            print("MQTT connected.")
        else:
            print(f"MQTT connection failed: {reason_code}", file=sys.stderr)

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties=None) -> None:
        self._connected = False
        print(f"MQTT disconnected: {reason_code}")

    def publish(self, telemetry: dict[str, Any], alerts: list[dict[str, Any]]) -> None:
        payload = json.dumps(telemetry)
        self.client.publish(f"{self.base_topic}/telemetry", payload, qos=self.qos, retain=False)

        for sensor, reading in telemetry["sensors"].items():
            sensor_payload = json.dumps(
                {
                    "site_id": self.site_id,
                    "timestamp": telemetry["timestamp"],
                    "sensor": sensor,
                    **reading,
                }
            )
            self.client.publish(
                f"{self.base_topic}/sensors/{sensor}",
                sensor_payload,
                qos=self.qos,
            )

        for alert in alerts:
            self.client.publish(
                f"{self.base_topic}/alerts",
                json.dumps(alert),
                qos=self.qos,
            )

    def disconnect(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Industrial wellhead sensor MQTT simulator")
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=Path(__file__).with_name("config.yaml"),
        help="Path to YAML configuration file",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Publish a single telemetry frame and exit",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    simulator = SensorSimulator(config)
    publisher = MqttPublisher(config)

    running = True

    def shutdown(_signum, _frame) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print(
        f"Simulating site {simulator.site_name} ({simulator.site_id}) "
        f"every {simulator.interval}s — Ctrl+C to stop"
    )

    try:
        while running:
            readings = simulator.generate_readings()
            telemetry = simulator.build_telemetry(readings)
            alerts = simulator.detect_alerts(readings)
            publisher.publish(telemetry, alerts)

            if alerts:
                for alert in alerts:
                    print(f"ALERT [{alert['severity'].upper()}] {alert['message']}")

            if args.once:
                break
            time.sleep(simulator.interval)
    finally:
        publisher.disconnect()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
