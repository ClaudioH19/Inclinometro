from __future__ import annotations

import math

from db import iterate_samples

ACCEL_LSB_PER_G = 8192.0
GYRO_LSB_PER_DPS = 65.5


def rpm_from_axis(axis: str, gx_dps: float, gy_dps: float, gz_dps: float) -> float:
    if axis == "x":
        return abs(gx_dps) / 6.0
    if axis == "y":
        return abs(gy_dps) / 6.0
    if axis == "z":
        return abs(gz_dps) / 6.0
    return math.sqrt(gx_dps * gx_dps + gy_dps * gy_dps + gz_dps * gz_dps) / 6.0


def analyze_motion(filters: dict, rpm_axis: str = "z") -> dict:
    sample_count = 0
    batch_keys = set()
    sessions = set()

    sum_ax_g = sum_ay_g = sum_az_g = 0.0
    sum_accel_g = sum_gyro_dps = sum_rpm = 0.0
    sum_roll = sum_pitch = 0.0

    min_rpm = float("inf")
    max_rpm = 0.0
    min_accel = float("inf")
    max_accel = 0.0
    min_gyro = float("inf")
    max_gyro = 0.0
    min_roll = float("inf")
    max_roll = float("-inf")
    min_pitch = float("inf")
    max_pitch = float("-inf")

    first_received_at = None
    last_received_at = None
    session_ranges: dict[str, tuple[int, int]] = {}

    for row in iterate_samples(filters):
        sample_count += 1
        sessions.add(row["session_id"])
        batch_keys.add((row["session_id"], row["batch_id"]))
        if first_received_at is None:
            first_received_at = row["received_at"]
        last_received_at = row["received_at"]

        start_us, end_us = session_ranges.get(row["session_id"], (row["sample_time_us"], row["sample_time_us"]))
        session_ranges[row["session_id"]] = (min(start_us, row["sample_time_us"]), max(end_us, row["sample_time_us"]))

        ax_g = row["accel_x_raw"] / ACCEL_LSB_PER_G
        ay_g = row["accel_y_raw"] / ACCEL_LSB_PER_G
        az_g = row["accel_z_raw"] / ACCEL_LSB_PER_G
        gx_dps = row["gyro_x_raw"] / GYRO_LSB_PER_DPS
        gy_dps = row["gyro_y_raw"] / GYRO_LSB_PER_DPS
        gz_dps = row["gyro_z_raw"] / GYRO_LSB_PER_DPS

        accel_g = math.sqrt(ax_g * ax_g + ay_g * ay_g + az_g * az_g)
        gyro_dps = math.sqrt(gx_dps * gx_dps + gy_dps * gy_dps + gz_dps * gz_dps)
        rpm = rpm_from_axis(rpm_axis, gx_dps, gy_dps, gz_dps)
        roll = math.degrees(math.atan2(ay_g, az_g))
        pitch = math.degrees(math.atan2(-ax_g, math.sqrt(ay_g * ay_g + az_g * az_g)))

        sum_ax_g += ax_g
        sum_ay_g += ay_g
        sum_az_g += az_g
        sum_accel_g += accel_g
        sum_gyro_dps += gyro_dps
        sum_rpm += rpm
        sum_roll += roll
        sum_pitch += pitch

        min_rpm = min(min_rpm, rpm)
        max_rpm = max(max_rpm, rpm)
        min_accel = min(min_accel, accel_g)
        max_accel = max(max_accel, accel_g)
        min_gyro = min(min_gyro, gyro_dps)
        max_gyro = max(max_gyro, gyro_dps)
        min_roll = min(min_roll, roll)
        max_roll = max(max_roll, roll)
        min_pitch = min(min_pitch, pitch)
        max_pitch = max(max_pitch, pitch)

    if sample_count == 0:
        return {
            "sample_count": 0,
            "batch_count": 0,
            "session_count": 0,
            "message": "No hay datos para los filtros seleccionados.",
            "rpm_axis": rpm_axis,
        }

    total_operation_us = sum(end_us - start_us for start_us, end_us in session_ranges.values())
    operation_hours = (total_operation_us / 1_000_000.0) / 3600.0

    mean_ax_g = sum_ax_g / sample_count
    mean_ay_g = sum_ay_g / sample_count
    mean_az_g = sum_az_g / sample_count
    residual_gravity_g = math.sqrt(mean_ax_g * mean_ax_g + mean_ay_g * mean_ay_g + mean_az_g * mean_az_g)

    return {
        "sample_count": sample_count,
        "batch_count": len(batch_keys),
        "session_count": len(sessions),
        "first_received_at": first_received_at,
        "last_received_at": last_received_at,
        "operation_hours": operation_hours,
        "rpm_axis": rpm_axis,
        "rpm_mean": sum_rpm / sample_count,
        "rpm_min": min_rpm,
        "rpm_max": max_rpm,
        "angular_speed_dps_mean": sum_gyro_dps / sample_count,
        "angular_speed_dps_min": min_gyro,
        "angular_speed_dps_max": max_gyro,
        "accel_magnitude_g_mean": sum_accel_g / sample_count,
        "accel_magnitude_g_min": min_accel,
        "accel_magnitude_g_max": max_accel,
        "mean_ax_g": mean_ax_g,
        "mean_ay_g": mean_ay_g,
        "mean_az_g": mean_az_g,
        "residual_gravity_g": residual_gravity_g,
        "residual_gravity_percent": residual_gravity_g * 100.0,
        "residual_gravity_g_hours": residual_gravity_g * operation_hours,
        "roll_deg_mean": sum_roll / sample_count,
        "roll_deg_min": min_roll,
        "roll_deg_max": max_roll,
        "pitch_deg_mean": sum_pitch / sample_count,
        "pitch_deg_min": min_pitch,
        "pitch_deg_max": max_pitch,
    }
