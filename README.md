# Clinostato 3D

Arquitectura:

- `ESP32 + MPU6050/MPU60xx`
- `MQTT Broker`
- `Python MQTT Consumer`
- `SQLite`
- `Dashboard HTML`

## Firmware ESP32

Archivo: [firmware/esp32_mpu6050_wifi.ino](C:/Users/claud/OneDrive/Escritorio/Inclinometro/firmware/esp32_mpu6050_wifi.ino)

Configura:

- `WIFI_SSID`
- `MQTT_HOST`
- `MQTT_PORT`

El firmware:

- captura a `50 Hz`
- usa `sample_time_us = micros() - capture_start_us`
- publica batches de `250` muestras
- enciende WiFi/MQTT solo para publicar
- apaga WiFi/MQTT despues de publicar
- genera `session_id` unico en cada encendido

Topic MQTT:

- `clinostat/motion_batch`

Payload MQTT:

```json
{
  "session_id": "123456789",
  "batch_id": 1,
  "samples": [
    [0, 120, -32, 16380, 3, -1, 4]
  ]
}
```

## Backend

Archivos:

- [server/consumer.py](C:/Users/claud/OneDrive/Escritorio/Inclinometro/server/consumer.py)
- [server/db.py](C:/Users/claud/OneDrive/Escritorio/Inclinometro/server/db.py)
- [server/analysis.py](C:/Users/claud/OneDrive/Escritorio/Inclinometro/server/analysis.py)
- [server/api.py](C:/Users/claud/OneDrive/Escritorio/Inclinometro/server/api.py)

El consumidor:

- se suscribe a `clinostat/motion_batch`
- valida `session_id`, `batch_id` y `samples`
- guarda cada muestra como un registro en SQLite

## SQLite

Base por defecto:

- `server/data/clinostat.db`

Tabla:

- `motion_records`

Campos:

- `id`
- `session_id`
- `batch_id`
- `sample_index`
- `sample_time_us`
- `accel_x_raw`, `accel_y_raw`, `accel_z_raw`
- `gyro_x_raw`, `gyro_y_raw`, `gyro_z_raw`
- `received_at`

## API

Rutas:

- `GET /api/health`
- `GET /api/sessions`
- `GET /api/metrics`
- `GET /api/samples`
- `GET /api/download/raw.csv`
- `GET /api/download/metrics.csv`
- `POST /api/admin/reset`

Filtros:

- `session_id`
- `received_after`
- `received_before`
- `rpm_axis` (solo en metricas)

## Dashboard

Ruta:

- `http://localhost:8000/`

Incluye:

- selector de sesion
- metricas
- tabla de sesiones
- tabla de datos crudos
- descarga CSV
- boton para vaciar base

## Docker Compose

Archivo:

- [docker-compose.yml](C:/Users/claud/OneDrive/Escritorio/Inclinometro/docker-compose.yml)

Variables:

- [.env](C:/Users/claud/OneDrive/Escritorio/Inclinometro/.env)

Levantar:

```powershell
docker compose up --build
```

Servicios:

- `mqtt` en `1884`
- `api` en `8000`
- `consumer` conectado al broker interno

## Verificacion rapida

```powershell
@'
import sqlite3
con = sqlite3.connect("server/data/clinostat.db")
for row in con.execute("select session_id, batch_id, sample_index, sample_time_us from motion_records order by id desc limit 5"):
    print(row)
'@ | python -
```
