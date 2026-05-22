from __future__ import annotations

import json
import logging
import os

import paho.mqtt.client as mqtt

from db import initialize_db, insert_batch

MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1884"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "clinostat/motion_batch")
MQTT_KEEPALIVE = int(os.getenv("MQTT_KEEPALIVE", "30"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("clinostat-consumer")


def parse_payload(raw_payload: bytes) -> tuple[str, int, list[list[int]]]:
    payload = json.loads(raw_payload.decode("utf-8"))
    session_id = payload.get("session_id")
    batch_id = payload.get("batch_id")
    samples = payload.get("samples")

    if not isinstance(session_id, str) or not session_id:
        raise ValueError("invalid_session_id")
    if not isinstance(batch_id, int):
        raise ValueError("invalid_batch_id")
    if not isinstance(samples, list) or not samples:
        raise ValueError("invalid_samples")

    last_time_us = -1
    for sample in samples:
        if not isinstance(sample, list) or len(sample) != 7:
            raise ValueError("invalid_sample_shape")
        if not all(isinstance(value, int) for value in sample):
            raise ValueError("invalid_sample_value")
        if sample[0] <= last_time_us:
            raise ValueError("sample_time_us_not_increasing")
        last_time_us = sample[0]
    return session_id, batch_id, samples


def on_connect(client: mqtt.Client, userdata, flags, reason_code, properties=None) -> None:
    del client, userdata, flags, properties
    if reason_code != 0:
        logger.error("Error al conectar MQTT: rc=%s", reason_code)
        return
    logger.info("MQTT conectado. Suscribiendo a %s", MQTT_TOPIC)
    mqtt_client.subscribe(MQTT_TOPIC, qos=1)


def on_message(client: mqtt.Client, userdata, message: mqtt.MQTTMessage) -> None:
    del client, userdata
    try:
        session_id, batch_id, samples = parse_payload(message.payload)
        insert_batch(session_id, batch_id, samples)
        logger.info("Batch guardado: session=%s batch=%s muestras=%s", session_id, batch_id, len(samples))
    except Exception as exc:
        logger.exception("Error procesando MQTT: %s", exc)


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
