from __future__ import annotations

import csv
import io
from datetime import datetime

from flask import Flask, Response, jsonify, render_template, request

from analysis import analyze_motion
from db import (
    DB_PATH,
    clear_database,
    count_samples,
    fetch_samples_page,
    initialize_db,
    list_devices,
    list_trials,
    set_trial_label,
    stream_samples_csv,
)

initialize_db()

app = Flask(__name__)


def active_filters() -> dict:
    filters = {}
    if request.args.get("device_id"):
        filters["device_id"] = request.args["device_id"]
    if request.args.get("trial_id"):
        filters["trial_id"] = int(request.args["trial_id"])
    if request.args.get("trial_number"):
        filters["trial_number"] = int(request.args["trial_number"])
    if request.args.get("received_after"):
        filters["received_after"] = request.args["received_after"]
    if request.args.get("received_before"):
        filters["received_before"] = request.args["received_before"]
    if request.args.get("started_after"):
        filters["started_after"] = request.args["started_after"]
    if request.args.get("started_before"):
        filters["started_before"] = request.args["started_before"]
    return filters


@app.get("/")
def index() -> str:
    return render_template("index.html")


@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "sqlite_path": str(DB_PATH), "time": datetime.utcnow().isoformat()})


@app.get("/api/devices")
def devices():
    return jsonify(list_devices())


@app.get("/api/trials")
def trials():
    return jsonify(list_trials(request.args.get("device_id")))


@app.put("/api/trials/<int:trial_id>/label")
def update_trial_label(trial_id: int):
    payload = request.get_json(silent=True) or {}
    if not set_trial_label(trial_id, payload.get("label")):
        return jsonify({"error": "trial_not_found"}), 404
    return jsonify({"ok": True})


@app.post("/api/admin/reset")
def reset_database():
    clear_database()
    return jsonify({"ok": True})


@app.get("/api/metrics")
def metrics():
    return jsonify(analyze_motion(active_filters(), request.args.get("rpm_axis", "z")))


@app.get("/api/samples")
def samples():
    limit = min(int(request.args.get("limit", "200")), 2000)
    offset = max(int(request.args.get("offset", "0")), 0)
    filters = active_filters()
    return jsonify(
        {
            "items": fetch_samples_page(filters, limit=limit, offset=offset),
            "total": count_samples(filters),
            "limit": limit,
            "offset": offset,
        }
    )


@app.get("/api/download/raw.csv")
def download_raw_csv():
    filename = f"clinostat_raw_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        stream_samples_csv(active_filters()),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/download/metrics.csv")
def download_metrics_csv():
    metrics_data = analyze_motion(active_filters(), request.args.get("rpm_axis", "z"))
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(metrics_data.keys()))
    writer.writeheader()
    writer.writerow(metrics_data)
    filename = f"clinostat_metrics_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
