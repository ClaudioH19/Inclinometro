from __future__ import annotations

import math

from db import iter_samples

ACCEL_LSB_PER_G = 8192.0
GYRO_LSB_PER_DPS = 65.5


def axis_value_dps(axis: str, gx_dps: float, gy_dps: float, gz_dps: float) -> float:
    if axis == "x":
        return abs(gx_dps)
    if axis == "y":
        return abs(gy_dps)
    if axis == "z":
        return abs(gz_dps)
    return math.sqrt(gx_dps * gx_dps + gy_dps * gy_dps + gz_dps * gz_dps)


def analyze_motion(filters: dict, rpm_axis: str = "z") -> dict:
    sample_count = 0
    batch_keys: set[tuple[int, int]] = set()
    trial_ids: set[int] = set()

    sum_ax_g = sum_ay_g = sum_az_g = 0.0
    sum_accel_mag_g = 0.0
    sum_gyro_mag_dps = 0.0
    sum_rpm = 0.0
    sum_roll_deg = 0.0
    sum_pitch_deg = 0.0

    min_accel_mag_g = float("inf")
    max_accel_mag_g = 0.0
    min_gyro_mag_dps = float("inf")
    max_gyro_mag_dps = 0.0
    min_rpm = float("inf")
    max_rpm = 0.0
    min_roll_deg = float("inf")
    max_roll_deg = float("-inf")
    min_pitch_deg = float("inf")
    max_pitch_deg = float("-inf")

    current_trial_id = None
    current_trial_first_us = 0
    current_trial_last_us = 0
    total_operation_us = 0
    first_received_at = None
    last_received_at = None

    for row in iter_samples(filters):
        sample_count += 1
        batch_keys.add((row["trial_id"], row["batch_id"]))
        trial_ids.add(row["trial_id"])

        if first_received_at is None:
            first_received_at = row["received_at"]
        last_received_at = row["received_at"]

        if current_trial_id != row["trial_id"]:
            if current_trial_id is not None:
                total_operation_us += current_trial_last_us - current_trial_first_us
            current_trial_id = row["trial_id"]
            current_trial_first_us = row["sample_time_us"]
        current_trial_last_us = row["sample_time_us"]

        ax_g = row["accel_x_raw"] / ACCEL_LSB_PER_G
        ay_g = row["accel_y_raw"] / ACCEL_LSB_PER_G
        az_g = row["accel_z_raw"] / ACCEL_LSB_PER_G

        gx_dps = row["gyro_x_raw"] / GYRO_LSB_PER_DPS
        gy_dps = row["gyro_y_raw"] / GYRO_LSB_PER_DPS
        gz_dps = row["gyro_z_raw"] / GYRO_LSB_PER_DPS

        accel_mag_g = math.sqrt(ax_g * ax_g + ay_g * ay_g + az_g * az_g)
        gyro_mag_dps = math.sqrt(gx_dps * gx_dps + gy_dps * gy_dps + gz_dps * gz_dps)
        rpm = axis_value_dps(rpm_axis, gx_dps, gy_dps, gz_dps) / 6.0
        roll_deg = math.degrees(math.atan2(ay_g, az_g))
        pitch_deg = math.degrees(math.atan2(-ax_g, math.sqrt(ay_g * ay_g + az_g * az_g)))

        sum_ax_g += ax_g
        sum_ay_g += ay_g
        sum_az_g += az_g
        sum_accel_mag_g += accel_mag_g
        sum_gyro_mag_dps += gyro_mag_dps
        sum_rpm += rpm
        sum_roll_deg += roll_deg
        sum_pitch_deg += pitch_deg

        min_accel_mag_g = min(min_accel_mag_g, accel_mag_g)
        max_accel_mag_g = max(max_accel_mag_g, accel_mag_g)
        min_gyro_mag_dps = min(min_gyro_mag_dps, gyro_mag_dps)
        max_gyro_mag_dps = max(max_gyro_mag_dps, gyro_mag_dps)
        min_rpm = min(min_rpm, rpm)
        max_rpm = max(max_rpm, rpm)
        min_roll_deg = min(min_roll_deg, roll_deg)
        max_roll_deg = max(max_roll_deg, roll_deg)
        min_pitch_deg = min(min_pitch_deg, pitch_deg)
        max_pitch_deg = max(max_pitch_deg, pitch_deg)

    if sample_count == 0:
        return {
            "sample_count": 0,
            "batch_count": 0,
            "trial_count": 0,
            "rpm_axis": rpm_axis,
            "message": "No hay datos para los filtros seleccionados.",
        }

    total_operation_us += current_trial_last_us - current_trial_first_us

    mean_ax_g = sum_ax_g / sample_count
    mean_ay_g = sum_ay_g / sample_count
    mean_az_g = sum_az_g / sample_count
    residual_gravity_g = math.sqrt(
        mean_ax_g * mean_ax_g + mean_ay_g * mean_ay_g + mean_az_g * mean_az_g
    )
    operation_seconds = total_operation_us / 1_000_000.0

    return {
        "sample_count": sample_count,
        "batch_count": len(batch_keys),
        "trial_count": len(trial_ids),
        "first_received_at": first_received_at,
        "last_received_at": last_received_at,
        "operation_seconds": operation_seconds,
        "operation_hours": operation_seconds / 3600.0,
        "rpm_axis": rpm_axis,
        "rpm_mean": sum_rpm / sample_count,
        "rpm_min": min_rpm,
        "rpm_max": max_rpm,
        "angular_speed_dps_mean": sum_gyro_mag_dps / sample_count,
        "angular_speed_dps_min": min_gyro_mag_dps,
        "angular_speed_dps_max": max_gyro_mag_dps,
        "accel_magnitude_g_mean": sum_accel_mag_g / sample_count,
        "accel_magnitude_g_min": min_accel_mag_g,
        "accel_magnitude_g_max": max_accel_mag_g,
        "mean_ax_g": mean_ax_g,
        "mean_ay_g": mean_ay_g,
        "mean_az_g": mean_az_g,
        "residual_gravity_g": residual_gravity_g,
        "residual_gravity_percent": residual_gravity_g * 100.0,
        "residual_gravity_g_hours": residual_gravity_g * (operation_seconds / 3600.0),
        "roll_deg_mean": sum_roll_deg / sample_count,
        "roll_deg_min": min_roll_deg,
        "roll_deg_max": max_roll_deg,
        "pitch_deg_mean": sum_pitch_deg / sample_count,
        "pitch_deg_min": min_pitch_deg,
        "pitch_deg_max": max_pitch_deg,
    }
