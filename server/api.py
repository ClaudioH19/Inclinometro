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
    fetch_samples,
    initialize_db,
    list_sessions,
    stream_samples_csv,
)

initialize_db()
app = Flask(__name__)


def filters_from_query() -> dict:
    filters = {}
    if request.args.get("session_id"):
        filters["session_id"] = request.args["session_id"]
    if request.args.get("received_after"):
        filters["received_after"] = request.args["received_after"]
    if request.args.get("received_before"):
        filters["received_before"] = request.args["received_before"]
    return filters


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "sqlite_path": str(DB_PATH), "time": datetime.utcnow().isoformat()})


@app.get("/api/sessions")
def sessions():
    return jsonify(list_sessions())


@app.post("/api/admin/reset")
def reset_database():
    clear_database()
    return jsonify({"ok": True})


@app.get("/api/metrics")
def metrics():
    return jsonify(analyze_motion(filters_from_query()))


@app.get("/api/samples")
def samples():
    limit = min(int(request.args.get("limit", "200")), 2000)
    offset = max(int(request.args.get("offset", "0")), 0)
    filters = filters_from_query()
    return jsonify(
        {
            "items": fetch_samples(filters, limit, offset),
            "total": count_samples(filters),
            "limit": limit,
            "offset": offset,
        }
    )


@app.get("/api/download/raw.csv")
def download_raw_csv():
    filename = f"clinostat_raw_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        stream_samples_csv(filters_from_query()),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/download/metrics.csv")
def download_metrics_csv():
    metrics_data = analyze_motion(filters_from_query())
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
