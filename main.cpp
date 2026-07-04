/**
 * C++ wellhead sensor simulator — publishes JSON telemetry over MQTT.
 * Build: cmake -B build && cmake --build build
 */

#include <MQTTClient.h>

#include <chrono>
#include <cmath>
#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <random>
#include <sstream>
#include <string>
#include <thread>

namespace {

constexpr const char* kSiteId = "WH-001";
constexpr const char* kBroker = "tcp://localhost:1883";
constexpr const char* kClientId = "wellhead-simulator-cpp";
constexpr double kIntervalSec = 1.0;

struct Thresholds {
  double warning;
  double critical;
};

struct SensorModel {
  const char* name;
  const char* unit;
  double baseline;
  double noise;
  Thresholds thresholds;
};

const SensorModel kSensors[] = {
    {"pressure", "psi", 875.0, 3.5, {920.0, 950.0}},
    {"temperature", "C", 68.0, 0.4, {82.0, 88.0}},
    {"flow_rate", "bbl/day", 1180.0, 15.0, {1450.0, 1600.0}},
    {"vibration", "mm/s", 3.2, 0.15, {7.5, 10.0}},
};

std::mt19937 rng{std::random_device{}()};

double gaussian(double mean, double stddev) {
  std::normal_distribution<double> dist(mean, stddev);
  return dist(rng);
}

double elapsedSeconds(const std::chrono::steady_clock::time_point& start) {
  return std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
}

std::string isoTimestamp() {
  const auto now = std::chrono::system_clock::now();
  const std::time_t t = std::chrono::system_clock::to_time_t(now);
  char buffer[32];
  std::strftime(buffer, sizeof(buffer), "%Y-%m-%dT%H:%M:%SZ", std::gmtime(&t));
  return buffer;
}

std::string evaluateStatus(const SensorModel& sensor, double value) {
  if (sensor.name == std::string("flow_rate")) {
    if (value <= 750.0) return "critical";
    if (value <= 900.0) return "warning";
    if (value >= sensor.thresholds.critical) return "critical";
    if (value >= sensor.thresholds.warning) return "warning";
    return "normal";
  }
  if (value >= sensor.thresholds.critical) return "critical";
  if (value >= sensor.thresholds.warning) return "warning";
  return "normal";
}

double simulateValue(const SensorModel& sensor, double elapsed, double& pressureDrift) {
  if (std::strcmp(sensor.name, "pressure") == 0) {
    pressureDrift += 2.0 * (kIntervalSec / 3600.0);
    return sensor.baseline + pressureDrift +
           std::sin(elapsed * 2.0 * M_PI / (6.0 * 3600.0)) * 8.0 + gaussian(0.0, sensor.noise);
  }
  if (std::strcmp(sensor.name, "temperature") == 0) {
    const double hours = elapsed / 3600.0;
    return sensor.baseline + 4.0 * std::sin((hours - 6.0) * 2.0 * M_PI / 24.0) +
           gaussian(0.0, sensor.noise);
  }
  if (std::strcmp(sensor.name, "flow_rate") == 0) {
    return sensor.baseline + 80.0 * std::sin(elapsed * 2.0 * M_PI / 45.0) +
           gaussian(0.0, sensor.noise);
  }
  return sensor.baseline + gaussian(0.0, sensor.noise) +
         std::abs(std::sin(elapsed * 0.7)) * 0.4;
}

bool publish(MQTTClient client, const std::string& topic, const std::string& payload) {
  MQTTClient_message message = MQTTClient_message_initializer;
  message.payload = const_cast<char*>(payload.c_str());
  message.payloadlen = static_cast<int>(payload.size());
  message.qos = 1;
  message.retained = 0;

  MQTTClient_deliveryToken token;
  const int rc = MQTTClient_publishMessage(client, topic.c_str(), &message, &token);
  if (rc != MQTTCLIENT_SUCCESS) {
    std::cerr << "Publish failed: " << rc << std::endl;
    return false;
  }
  MQTTClient_waitForCompletion(client, token, 2000);
  return true;
}

std::string buildTelemetry(double elapsed, double& pressureDrift, std::string& overall) {
  overall = "normal";
  std::ostringstream json;
  json << "{"
       << "\"site_id\":\"" << kSiteId << "\","
       << "\"site_name\":\"North Ridge Wellhead\","
       << "\"site_type\":\"wellhead\","
       << "\"timestamp\":\"" << isoTimestamp() << "\","
       << "\"overall_status\":\"PLACEHOLDER\","
       << "\"sensors\":{";

  bool first = true;
  for (const auto& sensor : kSensors) {
    const double value = simulateValue(sensor, elapsed, pressureDrift);
    const std::string status = evaluateStatus(sensor, value);
    if (status == "critical") overall = "critical";
    else if (status == "warning" && overall != "critical") overall = "warning";

    if (!first) json << ",";
    first = false;
    json << "\"" << sensor.name << "\":{"
         << "\"value\":" << value << ","
         << "\"unit\":\"" << sensor.unit << "\","
         << "\"status\":\"" << status << "\"}";
  }

  json << "}}";
  std::string payload = json.str();
  const auto pos = payload.find("PLACEHOLDER");
  if (pos != std::string::npos) payload.replace(pos, 11, overall);
  return payload;
}

}  // namespace

int main() {
  MQTTClient client;
  MQTTClient_connectOptions connOpts = MQTTClient_connectOptions_initializer;
  connOpts.keepAliveInterval = 60;
  connOpts.cleansession = 1;

  if (MQTTClient_create(&client, kBroker, kClientId, MQTTCLIENT_PERSISTENCE_NONE, nullptr) !=
      MQTTCLIENT_SUCCESS) {
    std::cerr << "Failed to create MQTT client" << std::endl;
    return 1;
  }

  std::cout << "Connecting to " << kBroker << "..." << std::endl;
  if (MQTTClient_connect(client, &connOpts) != MQTTCLIENT_SUCCESS) {
    std::cerr << "Failed to connect to MQTT broker" << std::endl;
    MQTTClient_destroy(&client);
    return 1;
  }

  const auto start = std::chrono::steady_clock::now();
  double pressureDrift = 0.0;

  std::cout << "Publishing wellhead telemetry every " << kIntervalSec << "s (Ctrl+C to stop)"
            << std::endl;

  while (true) {
    const double elapsed = elapsedSeconds(start);
    std::string overall;
    const std::string telemetry =
        buildTelemetry(elapsed, pressureDrift, overall);

    const std::string topic = std::string("wellhead/") + kSiteId + "/telemetry";
    publish(client, topic, telemetry);

    if (overall != "normal") {
      std::cout << "Status: " << overall << std::endl;
    }

    std::this_thread::sleep_for(std::chrono::duration<double>(kIntervalSec));
  }

  MQTTClient_disconnect(client, 1000);
  MQTTClient_destroy(&client);
  return 0;
}
