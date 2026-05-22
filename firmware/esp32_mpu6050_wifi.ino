#include <Arduino.h>
#include <WiFi.h>
#include <Wire.h>
#include <AsyncMqttClient.h>
#include <ArduinoJson.h>

struct MotionSample {
  uint32_t sample_time_us;
  int16_t accel_x_raw;
  int16_t accel_y_raw;
  int16_t accel_z_raw;
  int16_t gyro_x_raw;
  int16_t gyro_y_raw;
  int16_t gyro_z_raw;
};

namespace {

const char* DEVICE_ID = "clinostat_node_01";
const char* WIFI_SSID = "Utalca-visitas";
const char* MQTT_HOST = "38.242.251.218";
const uint16_t MQTT_PORT = 1884;

const uint16_t SAMPLE_RATE_HZ = 50;
const uint16_t SAMPLES_PER_BATCH = 250;
const uint32_t SAMPLE_INTERVAL_US = 1000000UL / SAMPLE_RATE_HZ;
const uint32_t WIFI_TIMEOUT_MS = 6000;
const uint32_t MQTT_TIMEOUT_MS = 3000;
const size_t JSON_CAPACITY = 32000;
const size_t JSON_DOCUMENT_CAPACITY = 65536;

const uint8_t MPU_ADDRESS = 0x68;
const uint8_t MPU_PWR_MGMT_1 = 0x6B;
const uint8_t MPU_CONFIG = 0x1A;
const uint8_t MPU_GYRO_CONFIG = 0x1B;
const uint8_t MPU_ACCEL_CONFIG = 0x1C;
const uint8_t MPU_ACCEL_CONFIG_2 = 0x1D;
const uint8_t MPU_ACCEL_XOUT_H = 0x3B;
const uint8_t I2C_SDA_PIN = 21;
const uint8_t I2C_SCL_PIN = 22;

MotionSample captureBuffer[SAMPLES_PER_BATCH];
MotionSample publishBuffer[SAMPLES_PER_BATCH];
char jsonPayload[JSON_CAPACITY];

AsyncMqttClient mqttClient;

uint16_t captureCount = 0;
uint16_t publishCount = 0;
uint32_t captureStartUs = 0;
uint32_t nextSampleUs = 0;
uint32_t nextBatchId = 1;
uint32_t publishBatchId = 0;
uint32_t wifiStartedAtMs = 0;
uint32_t mqttStartedAtMs = 0;

bool publishPending = false;
bool wifiConnecting = false;
bool mqttConnecting = false;
bool wifiConnected = false;
bool mqttConnected = false;

bool writeRegister(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(MPU_ADDRESS);
  Wire.write(reg);
  Wire.write(value);
  return Wire.endTransmission(true) == 0;
}

bool readRegisters(uint8_t startReg, uint8_t* buffer, size_t length) {
  Wire.beginTransmission(MPU_ADDRESS);
  Wire.write(startReg);
  if (Wire.endTransmission(false) != 0) {
    return false;
  }

  size_t received = Wire.requestFrom(MPU_ADDRESS, static_cast<uint8_t>(length), static_cast<uint8_t>(true));
  if (received != length) {
    return false;
  }

  for (size_t i = 0; i < length; ++i) {
    buffer[i] = Wire.read();
  }
  return true;
}

int16_t readInt16BE(const uint8_t* buffer, size_t offset) {
  return static_cast<int16_t>((static_cast<uint16_t>(buffer[offset]) << 8) | buffer[offset + 1]);
}

bool initializeSensor() {
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
  Wire.setClock(400000);

  if (!writeRegister(MPU_PWR_MGMT_1, 0x00)) {
    return false;
  }

  delay(100);

  return writeRegister(MPU_CONFIG, 0x03) &&
         writeRegister(MPU_GYRO_CONFIG, 0x08) &&
         writeRegister(MPU_ACCEL_CONFIG, 0x08) &&
         writeRegister(MPU_ACCEL_CONFIG_2, 0x03);
}

bool readMotionSample(MotionSample& sample) {
  uint8_t raw[14];
  if (!readRegisters(MPU_ACCEL_XOUT_H, raw, sizeof(raw))) {
    return false;
  }

  sample.sample_time_us = micros() - captureStartUs;
  sample.accel_x_raw = readInt16BE(raw, 0);
  sample.accel_y_raw = readInt16BE(raw, 2);
  sample.accel_z_raw = readInt16BE(raw, 4);
  sample.gyro_x_raw = readInt16BE(raw, 8);
  sample.gyro_y_raw = readInt16BE(raw, 10);
  sample.gyro_z_raw = readInt16BE(raw, 12);
  return true;
}

void enterWirelessLowPowerMode() {
  // Apaga radio entre batches.
  mqttClient.disconnect();
  WiFi.disconnect(true, true);
  WiFi.mode(WIFI_OFF);
  wifiConnecting = false;
  mqttConnecting = false;
  wifiConnected = false;
  mqttConnected = false;
}

void exitWirelessLowPowerMode() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(true);
  WiFi.begin(WIFI_SSID);
  wifiConnecting = true;
  mqttConnecting = false;
  wifiConnected = false;
  mqttConnected = false;
  wifiStartedAtMs = millis();
}

void initializeMqtt() {
  mqttClient.setServer(MQTT_HOST, MQTT_PORT);
  mqttClient.setKeepAlive(30);
}

void resetCaptureBuffer() {
  captureCount = 0;
}

void moveBatchToPublishBuffer() {
  if (publishPending) {
    Serial.println("Batch descartado: envio anterior aun pendiente.");
    resetCaptureBuffer();
    return;
  }

  memcpy(publishBuffer, captureBuffer, sizeof(MotionSample) * SAMPLES_PER_BATCH);
  publishCount = captureCount;
  publishBatchId = nextBatchId++;
  publishPending = true;
  resetCaptureBuffer();
}

bool buildBatchJson(size_t& payloadLength) {
  // El JSON se arma como estructura y luego se serializa al buffer.
  DynamicJsonDocument doc(JSON_DOCUMENT_CAPACITY);
  doc["device_id"] = DEVICE_ID;
  doc["batch_id"] = publishBatchId;

  JsonArray sampleFormat = doc.createNestedArray("sample_format");
  sampleFormat.add("sample_time_us");
  sampleFormat.add("accel_x_raw");
  sampleFormat.add("accel_y_raw");
  sampleFormat.add("accel_z_raw");
  sampleFormat.add("gyro_x_raw");
  sampleFormat.add("gyro_y_raw");
  sampleFormat.add("gyro_z_raw");

  JsonArray samples = doc.createNestedArray("samples");
  for (uint16_t index = 0; index < publishCount; ++index) {
    JsonArray sample = samples.createNestedArray();
    sample.add(publishBuffer[index].sample_time_us);
    sample.add(publishBuffer[index].accel_x_raw);
    sample.add(publishBuffer[index].accel_y_raw);
    sample.add(publishBuffer[index].accel_z_raw);
    sample.add(publishBuffer[index].gyro_x_raw);
    sample.add(publishBuffer[index].gyro_y_raw);
    sample.add(publishBuffer[index].gyro_z_raw);
  }

  payloadLength = serializeJson(doc, jsonPayload, JSON_CAPACITY);
  return payloadLength > 0 && payloadLength < JSON_CAPACITY;
}

void publishMotionBatch() {
  if (!mqttConnected || !publishPending || publishCount == 0) {
    return;
  }

  size_t payloadLength = 0;
  if (!buildBatchJson(payloadLength)) {
    Serial.println("Batch demasiado grande para el buffer JSON.");
    publishPending = false;
    publishCount = 0;
    enterWirelessLowPowerMode();
    return;
  }

  char topic[96];
  snprintf(topic, sizeof(topic), "clinostat/%s/motion_batch", DEVICE_ID);

  uint16_t packetId = mqttClient.publish(topic, 1, false, jsonPayload, payloadLength);
  if (packetId == 0) {
    Serial.println("No se pudo publicar el batch MQTT.");
    publishPending = false;
    publishCount = 0;
    enterWirelessLowPowerMode();
  }
}

void serviceSampling() {
  uint32_t nowUs = micros();
  if (static_cast<int32_t>(nowUs - nextSampleUs) < 0) {
    return;
  }

  // Mantiene una cadencia fija aunque el loop varie un poco.
  nextSampleUs += SAMPLE_INTERVAL_US;

  MotionSample sample{};
  if (!readMotionSample(sample)) {
    return;
  }

  if (captureCount < SAMPLES_PER_BATCH) {
    captureBuffer[captureCount++] = sample;
  }

  if (captureCount == SAMPLES_PER_BATCH) {
    moveBatchToPublishBuffer();
  }
}

void serviceWireless() {
  uint32_t nowMs = millis();

  if (!publishPending) {
    return;
  }

  if (!wifiConnecting && !wifiConnected) {
    exitWirelessLowPowerMode();
    return;
  }

  if (wifiConnecting && !wifiConnected && nowMs - wifiStartedAtMs > WIFI_TIMEOUT_MS) {
    Serial.println("Timeout WiFi.");
    publishPending = false;
    publishCount = 0;
    enterWirelessLowPowerMode();
    return;
  }

  if (wifiConnected && !mqttConnected && !mqttConnecting) {
    mqttClient.connect();
    mqttConnecting = true;
    mqttStartedAtMs = nowMs;
    return;
  }

  if (mqttConnecting && !mqttConnected && nowMs - mqttStartedAtMs > MQTT_TIMEOUT_MS) {
    Serial.println("Timeout MQTT.");
    publishPending = false;
    publishCount = 0;
    enterWirelessLowPowerMode();
    return;
  }
}

void onWifiEvent(WiFiEvent_t event) {
#if defined(ARDUINO_EVENT_WIFI_STA_GOT_IP)
  if (event == ARDUINO_EVENT_WIFI_STA_GOT_IP) {
    wifiConnected = true;
    wifiConnecting = false;
    return;
  }
  if (event == ARDUINO_EVENT_WIFI_STA_DISCONNECTED) {
    wifiConnected = false;
    wifiConnecting = false;
    mqttConnected = false;
    mqttConnecting = false;
    return;
  }
#else
  if (event == SYSTEM_EVENT_STA_GOT_IP) {
    wifiConnected = true;
    wifiConnecting = false;
    return;
  }
  if (event == SYSTEM_EVENT_STA_DISCONNECTED) {
    wifiConnected = false;
    wifiConnecting = false;
    mqttConnected = false;
    mqttConnecting = false;
    return;
  }
#endif
}

void onMqttConnect(bool sessionPresent) {
  (void)sessionPresent;
  mqttConnected = true;
  mqttConnecting = false;
  publishMotionBatch();
}

void onMqttDisconnect(AsyncMqttClientDisconnectReason reason) {
  (void)reason;
  mqttConnected = false;
  mqttConnecting = false;
}

void onMqttPublish(uint16_t packetId) {
  (void)packetId;
  publishPending = false;
  publishCount = 0;
  enterWirelessLowPowerMode();
}

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(300);

  if (!initializeSensor()) {
    Serial.println("No se pudo inicializar el MPU6050.");
    while (true) {
      delay(1000);
    }
  }

  captureStartUs = micros();
  nextSampleUs = micros() + SAMPLE_INTERVAL_US;

  WiFi.persistent(false);
  WiFi.onEvent(onWifiEvent);

  initializeMqtt();
  mqttClient.onConnect(onMqttConnect);
  mqttClient.onDisconnect(onMqttDisconnect);
  mqttClient.onPublish(onMqttPublish);

  enterWirelessLowPowerMode();
  Serial.println("Captura iniciada.");
}

void loop() {
  serviceSampling();
  serviceWireless();
  delay(1);
}
