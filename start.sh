#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
docker compose up -d
echo ""
echo "Dashboard:  http://localhost:8080"
echo "MQTT:       localhost:1883"
echo "WebSocket:  ws://localhost:9001"
echo ""
echo "Next: cd simulator && python sensor_simulator.py"
