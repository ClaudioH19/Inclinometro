#include <Arduino.h>
#include <WiFi.h>
#include <Wire.h>
#include <AsyncMqttClient.h>
#include <ArduinoJson.h>
#include <esp_system.h>

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

const char* WIFI_SSID = "Utalca-visitas";
const char* MQTT_HOST = "38.242.251.218";
const uint16_t MQTT_PORT = 1884;

const uint16_t SAMPLE_RATE_HZ = 50;
const uint16_t SAMPLES_PER_BATCH = 250;
const uint32_t SAMPLE_INTERVAL_US = 1000000UL / SAMPLE_RATE_HZ;
const uint32_t WIFI_TIMEOUT_MS = 6000;
const uint32_t MQTT_TIMEOUT_MS = 3000;
const size_t JSON_BUFFER_SIZE = 32000;
const size_t JSON_DOC_SIZE = 65536;

const uint8_t MPU_ADDR = 0x68;
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
char jsonPayload[JSON_BUFFER_SIZE];
char sessionId[16];

AsyncMqttClient mqttClient;

uint16_t captureCount = 0;
uint16_t publishCount = 0;
uint32_t captureStartUs = 0;
uint32_t nextSampleUs = 0;
uint32_t nextBatchId = 1;
uint32_t publishBatchId = 0;
uint32_t wifiStartMs = 0;
uint32_t mqttStartMs = 0;

bool publishPending = false;
bool mqttConnected = false;
bool mqttConnecting = false;
bool publishInFlight = false;
bool wifiStarted = false;

void stopRadio() {
  mqttClient.disconnect();
  WiFi.disconnect(true, true);
  WiFi.mode(WIFI_OFF);
  wifiStarted = false;
  mqttConnecting = false;
  mqttConnected = false;
  publishInFlight = false;
}

void dropPendingBatch(const char* reason) {
  Serial.println(reason);
  publishPending = false;
  publishCount = 0;
  stopRadio();
}

void onMqttConnect(bool sessionPresent) {
  (void)sessionPresent;
  mqttConnected = true;
  mqttConnecting = false;
}

void onMqttDisconnect(AsyncMqttClientDisconnectReason reason) {
  (void)reason;
  mqttConnected = false;
  mqttConnecting = false;
  publishInFlight = false;
}

void onMqttPublish(uint16_t packetId) {
  (void)packetId;
  publishPending = false;
  publishCount = 0;
  publishInFlight = false;
  stopRadio();
}

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(300);

  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
  Wire.setClock(400000);

  Wire.beginTransmission(MPU_ADDR);
  Wire.write(MPU_PWR_MGMT_1);
  Wire.write(0x00);
  if (Wire.endTransmission(true) != 0) {
    Serial.println("No se pudo inicializar el MPU6050.");
    while (true) {
      delay(1000);
    }
  }

  delay(100);
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(MPU_CONFIG);
  Wire.write(0x03);
  Wire.write(0x08);
  Wire.write(0x08);
  Wire.write(0x03);
  if (Wire.endTransmission(true) != 0) {
    Serial.println("No se pudo configurar el MPU6050.");
    while (true) {
      delay(1000);
    }
  }

  snprintf(sessionId, sizeof(sessionId), "%lu", static_cast<unsigned long>(esp_random()));
  captureStartUs = micros();
  nextSampleUs = micros() + SAMPLE_INTERVAL_US;

  WiFi.persistent(false);
  mqttClient.setServer(MQTT_HOST, MQTT_PORT);
  mqttClient.setKeepAlive(30);
  mqttClient.onConnect(onMqttConnect);
  mqttClient.onDisconnect(onMqttDisconnect);
  mqttClient.onPublish(onMqttPublish);

  stopRadio();
  Serial.print("Captura iniciada. session_id=");
  Serial.println(sessionId);
}

void loop() {
  // 1) Leer muestra por cadencia fija.
  uint32_t nowUs = micros();
  if (static_cast<int32_t>(nowUs - nextSampleUs) >= 0) {
    nextSampleUs += SAMPLE_INTERVAL_US;

    uint8_t raw[14];
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(MPU_ACCEL_XOUT_H);
    if (Wire.endTransmission(false) == 0 &&
        Wire.requestFrom(MPU_ADDR, static_cast<uint8_t>(14), static_cast<uint8_t>(true)) == 14) {
      for (uint8_t i = 0; i < 14; ++i) {
        raw[i] = Wire.read();
      }

      MotionSample sample{};
      sample.sample_time_us = micros() - captureStartUs;
      sample.accel_x_raw = static_cast<int16_t>((static_cast<uint16_t>(raw[0]) << 8) | raw[1]);
      sample.accel_y_raw = static_cast<int16_t>((static_cast<uint16_t>(raw[2]) << 8) | raw[3]);
      sample.accel_z_raw = static_cast<int16_t>((static_cast<uint16_t>(raw[4]) << 8) | raw[5]);
      sample.gyro_x_raw = static_cast<int16_t>((static_cast<uint16_t>(raw[8]) << 8) | raw[9]);
      sample.gyro_y_raw = static_cast<int16_t>((static_cast<uint16_t>(raw[10]) << 8) | raw[11]);
      sample.gyro_z_raw = static_cast<int16_t>((static_cast<uint16_t>(raw[12]) << 8) | raw[13]);

      if (captureCount < SAMPLES_PER_BATCH) {
        captureBuffer[captureCount++] = sample;
      }
    }
  }

  // 2) Cerrar batch al llenarse.
  if (captureCount == SAMPLES_PER_BATCH) {
    if (publishPending) {
      Serial.println("Batch descartado: envio anterior aun pendiente.");
      captureCount = 0;
    } else {
      memcpy(publishBuffer, captureBuffer, sizeof(MotionSample) * captureCount);
      publishCount = captureCount;
      publishBatchId = nextBatchId++;
      captureCount = 0;
      publishPending = true;
    }
  }

  // 3) Si hay batch pendiente: activar radio, conectar y publicar.
  if (publishPending) {
    uint32_t nowMs = millis();

    if (!wifiStarted) {
      WiFi.mode(WIFI_STA);
      WiFi.setSleep(true);
      WiFi.begin(WIFI_SSID);
      wifiStarted = true;
      wifiStartMs = nowMs;
    }

    if (wifiStarted && WiFi.status() != WL_CONNECTED && nowMs - wifiStartMs > WIFI_TIMEOUT_MS) {
      dropPendingBatch("Timeout WiFi.");
    }

    if (wifiStarted && WiFi.status() == WL_CONNECTED && !mqttConnected && !mqttConnecting) {
      mqttClient.connect();
      mqttConnecting = true;
      mqttStartMs = nowMs;
    }

    if (mqttConnecting && !mqttConnected && nowMs - mqttStartMs > MQTT_TIMEOUT_MS) {
      dropPendingBatch("Timeout MQTT.");
    }

    if (mqttConnected && !publishInFlight && publishCount > 0) {
      DynamicJsonDocument doc(JSON_DOC_SIZE);
      doc["session_id"] = sessionId;
      doc["batch_id"] = publishBatchId;
      JsonArray samples = doc.createNestedArray("samples");

      for (uint16_t i = 0; i < publishCount; ++i) {
        JsonArray item = samples.createNestedArray();
        item.add(publishBuffer[i].sample_time_us);
        item.add(publishBuffer[i].accel_x_raw);
        item.add(publishBuffer[i].accel_y_raw);
        item.add(publishBuffer[i].accel_z_raw);
        item.add(publishBuffer[i].gyro_x_raw);
        item.add(publishBuffer[i].gyro_y_raw);
        item.add(publishBuffer[i].gyro_z_raw);
      }

      size_t payloadSize = serializeJson(doc, jsonPayload, JSON_BUFFER_SIZE);
      if (payloadSize == 0 || payloadSize >= JSON_BUFFER_SIZE) {
        dropPendingBatch("Batch demasiado grande para el buffer JSON.");
      } else {
        uint16_t packetId = mqttClient.publish("clinostat/motion_batch", 1, false, jsonPayload, payloadSize);
        if (packetId == 0) {
          dropPendingBatch("No se pudo publicar el batch MQTT.");
        } else {
          publishInFlight = true;
        }
      }
    }
  }

  delay(1);
}
