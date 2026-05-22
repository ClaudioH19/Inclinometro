from __future__ import annotations

from datetime import datetime

from flask import Flask, Response, jsonify, request

from db import DB_PATH, count_samples, fetch_samples, initialize_db, list_sessions, stream_samples_csv

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


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.get("/api/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "service": "data-api",
            "sqlite_path": str(DB_PATH),
            "time": datetime.utcnow().isoformat(),
        }
    )


@app.get("/api/sessions")
def sessions():
    return jsonify(list_sessions())


@app.get("/api/samples")
def samples():
    limit = min(int(request.args.get("limit", "200")), 5000)
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8001, debug=False)
