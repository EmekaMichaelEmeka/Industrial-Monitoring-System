# Start Mosquitto broker + web dashboard
Set-Location $PSScriptRoot
docker compose up -d
Write-Host ""
Write-Host "Dashboard:  http://localhost:8080"
Write-Host "MQTT:       localhost:1883"
Write-Host "WebSocket:  ws://localhost:9001"
Write-Host ""
Write-Host "Next: cd simulator && python sensor_simulator.py"
