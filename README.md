# Clinostato 3D

Arquitectura:

- `ESP32 + MPU6050/MPU60xx`
- `MQTT Broker`
- `Python MQTT Consumer`
- `SQLite`
- `Dashboard HTML`

## Firmware ESP32

Archivo: [firmware/esp32_mpu6050_wifi.ino](C:/Users/claud/OneDrive/Escritorio/Inclinometro/firmware/esp32_mpu6050_wifi.ino)

Configura estas constantes:

- `DEVICE_ID`
- `WIFI_SSID`
- `MQTT_HOST`
- `MQTT_PORT`

El firmware:

- captura muestras del `MPU6050` a `50 Hz`
- genera `sample_time_us = micros() - capture_start_time_us`
- llena batches de `250` muestras
- enciende `WiFi/MQTT` solo para publicar
- publica un mensaje MQTT por batch
- apaga `WiFi/MQTT` despues de publicar

Topic MQTT:

- `clinostat/{device_id}/motion_batch`

## Backend

Archivos:

- [server/consumer.py](C:/Users/claud/OneDrive/Escritorio/Inclinometro/server/consumer.py)
- [server/db.py](C:/Users/claud/OneDrive/Escritorio/Inclinometro/server/db.py)
- [server/analysis.py](C:/Users/claud/OneDrive/Escritorio/Inclinometro/server/analysis.py)
- [server/api.py](C:/Users/claud/OneDrive/Escritorio/Inclinometro/server/api.py)

El consumidor:

- se suscribe a `clinostat/+/motion_batch`
- valida `device_id`, `batch_id`, `sample_format` y `samples`
- detecta nuevas pruebas cuando el `batch_id` o `sample_time_us` vuelven a empezar
- guarda pruebas, batches y muestras en SQLite

La API:

- lista dispositivos
- lista pruebas
- permite nombrar pruebas
- calcula gravedad residual, RPM estimadas, horas de operacion, `pitch`, `roll` y aceleracion
- entrega tabla paginada y descargas CSV

## Dashboard

Ruta:

- `http://localhost:8000/`

Permite:

- filtrar por dispositivo
- filtrar por prueba
- filtrar por rango de recepcion
- elegir eje para estimar RPM
- ver metricas
- ver tabla de muestras
- descargar CSV crudo
- descargar CSV de metricas
- poner nombre a una prueba

## SQLite

Base por defecto:

- `server/data/clinostat.db`

Tablas:

- `trials`
- `motion_batches`
- `motion_samples`

## Docker Compose

Archivo:

- [docker-compose.yml](C:/Users/claud/OneDrive/Escritorio/Inclinometro/docker-compose.yml)

Variables:

- [ .env ](C:/Users/claud/OneDrive/Escritorio/Inclinometro/.env)

Levantar servicios:

```powershell
docker compose up --build
```

Servicios:

- `mqtt` expuesto en `1884`
- `api` expuesta en `8000`
- `consumer` conectado al broker interno

El ESP32 debe apuntar a:

- `MQTT_HOST = IP del servidor`
- `MQTT_PORT = 1884`

## Ejecucion local sin Docker

```powershell
cd server
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python consumer.py
```

En otra terminal:

```powershell
cd server
.venv\Scripts\activate
python api.py
```

## Verificar SQLite

```powershell
@'
import sqlite3
con = sqlite3.connect("server/data/clinostat.db")
for row in con.execute("select device_id, trial_number, batch_count, sample_count from trials order by id desc limit 5"):
    print(row)
'@ | python -
```
