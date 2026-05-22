from __future__ import annotations

import json
import logging
import os

import paho.mqtt.client as mqtt

from db import initialize_db, save_motion_batch

MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1884"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "clinostat/+/motion_batch")
MQTT_KEEPALIVE = int(os.getenv("MQTT_KEEPALIVE", "30"))

EXPECTED_SAMPLE_FORMAT = [
    "sample_time_us",
    "accel_x_raw",
    "accel_y_raw",
    "accel_z_raw",
    "gyro_x_raw",
    "gyro_y_raw",
    "gyro_z_raw",
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("clinostat-consumer")


def topic_device_id(topic: str) -> str:
    parts = topic.split("/")
    if len(parts) != 3 or parts[0] != "clinostat" or parts[2] != "motion_batch":
        raise ValueError("invalid_topic")
    return parts[1]


def validate_message(payload: dict, expected_device_id: str) -> tuple[str, int, list[list[int]]]:
    if not isinstance(payload, dict):
        raise ValueError("payload_must_be_object")

    device_id = payload.get("device_id")
    batch_id = payload.get("batch_id")
    sample_format = payload.get("sample_format")
    samples = payload.get("samples")

    if not isinstance(device_id, str) or not device_id:
        raise ValueError("invalid_device_id")
    if device_id != expected_device_id:
        raise ValueError("device_id_topic_mismatch")
    if not isinstance(batch_id, int):
        raise ValueError("invalid_batch_id")
    if sample_format != EXPECTED_SAMPLE_FORMAT:
        raise ValueError("invalid_sample_format")
    if not isinstance(samples, list) or not samples:
        raise ValueError("invalid_samples")

    last_sample_time_us = -1
    for sample in samples:
        if not isinstance(sample, list) or len(sample) != 7:
            raise ValueError("invalid_sample_shape")
        if not all(isinstance(value, int) for value in sample):
            raise ValueError("invalid_sample_value")
        if sample[0] <= last_sample_time_us:
            raise ValueError("sample_time_us_not_increasing")
        last_sample_time_us = sample[0]

    return device_id, batch_id, samples


def on_connect(client: mqtt.Client, userdata, flags, reason_code, properties=None) -> None:
    del client, userdata, flags, properties
    if reason_code == 0:
        logger.info("MQTT conectado. Suscribiendo a %s", MQTT_TOPIC)
        mqtt_client.subscribe(MQTT_TOPIC, qos=1)
        return
    logger.error("Error al conectar MQTT: rc=%s", reason_code)


def on_message(client: mqtt.Client, userdata, message: mqtt.MQTTMessage) -> None:
    del client, userdata
    try:
        payload = json.loads(message.payload.decode("utf-8"))
        device_id, batch_id, samples = validate_message(payload, topic_device_id(message.topic))
        trial_number = save_motion_batch(device_id, batch_id, samples)
        logger.info(
            "Batch guardado: %s / trial %s / batch %s (%s muestras)",
            device_id,
            trial_number,
            batch_id,
            len(samples),
        )
    except Exception as exc:
        logger.exception("Error procesando mensaje MQTT: %s", exc)


initialize_db()

mqtt_client = mqtt.Client(protocol=mqtt.MQTTv311)
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message


def main() -> None:
    logger.info("Conectando a broker MQTT %s:%s", MQTT_HOST, MQTT_PORT)
    mqtt_client.connect(MQTT_HOST, MQTT_PORT, MQTT_KEEPALIVE)
    mqtt_client.loop_forever()


if __name__ == "__main__":
    main()
