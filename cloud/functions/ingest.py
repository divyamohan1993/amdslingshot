"""Cloud Function: Ingest edge gateway data batches into BigQuery.

Triggered by HTTP POST from edge gateways during cloud sync.
Handles gzip-compressed JSON payloads with idempotency via batch_id.
"""

import asyncio
import gzip
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

import functions_framework
from google.cloud import bigquery, storage

logger = logging.getLogger(__name__)

BQ_DATASET = "jalnetra"
BQ_READINGS_TABLE = "sensor_readings"
BQ_ALERTS_TABLE = "alerts"
BQ_PREDICTIONS_TABLE = "predictions"
GCS_BUCKET = "jalnetra-raw-batches"


def get_bq_client() -> bigquery.Client:
    return bigquery.Client()


def get_gcs_client() -> storage.Client:
    return storage.Client()


def verify_batch_idempotency(client: bigquery.Client, batch_id: str) -> bool:
    """Check if this batch was already processed."""
    query = f"""
        SELECT COUNT(*) as cnt
        FROM `{BQ_DATASET}.sync_log`
        WHERE batch_id = @batch_id
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("batch_id", "STRING", batch_id)
        ]
    )
    result = client.query(query, job_config=job_config).result()
    row = next(iter(result))
    return row.cnt > 0


def store_raw_batch(gcs_client: storage.Client, batch_id: str, raw_data: bytes) -> str:
    """Archive raw batch to Cloud Storage for audit trail."""
    bucket = gcs_client.bucket(GCS_BUCKET)
    today = datetime.now(timezone.utc).strftime("%Y/%m/%d")
    blob_path = f"batches/{today}/{batch_id}.json.gz"
    blob = bucket.blob(blob_path)
    blob.upload_from_string(raw_data, content_type="application/gzip")
    return f"gs://{GCS_BUCKET}/{blob_path}"


def insert_readings(client: bigquery.Client, readings: list[dict[str, Any]], gateway_id: str) -> int:
    """Stream-insert sensor readings into BigQuery."""
    if not readings:
        return 0

    rows = []
    for r in readings:
        rows.append({
            "gateway_id": gateway_id,
            "node_id": r.get("node_id"),
            "timestamp": r.get("timestamp"),
            "tds": r.get("tds"),
            "ph": r.get("ph"),
            "turbidity": r.get("turbidity"),
            "dissolved_oxygen": r.get("dissolved_oxygen"),
            "flow_rate": r.get("flow_rate"),
            "water_level": r.get("water_level"),
            "battery_pct": r.get("battery_pct"),
            "rssi_dbm": r.get("rssi_dbm"),
            "anomaly_label": r.get("anomaly_label"),
            "anomaly_confidence": r.get("anomaly_confidence"),
            "ingested_at": datetime.now(timezone.utc).isoformat(),
        })

    table_ref = f"{BQ_DATASET}.{BQ_READINGS_TABLE}"
    errors = client.insert_rows_json(table_ref, rows)
    if errors:
        logger.error("BigQuery insert errors: %s", errors)
    return len(rows)


def insert_alerts(client: bigquery.Client, alerts: list[dict[str, Any]], gateway_id: str) -> int:
    """Insert alerts into BigQuery."""
    if not alerts:
        return 0

    rows = []
    for a in alerts:
        rows.append({
            "gateway_id": gateway_id,
            "alert_id": a.get("alert_id"),
            "node_id": a.get("node_id"),
            "severity": a.get("severity"),
            "alert_type": a.get("alert_type"),
            "message": a.get("message"),
            "parameter": a.get("parameter"),
            "value": a.get("value"),
            "threshold": a.get("threshold"),
            "created_at": a.get("created_at"),
            "acknowledged_at": a.get("acknowledged_at"),
            "ingested_at": datetime.now(timezone.utc).isoformat(),
        })

    table_ref = f"{BQ_DATASET}.{BQ_ALERTS_TABLE}"
    errors = client.insert_rows_json(table_ref, rows)
    if errors:
        logger.error("BigQuery alert insert errors: %s", errors)
    return len(rows)


def log_sync(client: bigquery.Client, batch_id: str, gateway_id: str,
             readings_count: int, alerts_count: int, gcs_path: str) -> None:
    """Record sync event for idempotency and audit."""
    rows = [{
        "batch_id": batch_id,
        "gateway_id": gateway_id,
        "readings_count": readings_count,
        "alerts_count": alerts_count,
        "raw_archive_path": gcs_path,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }]
    table_ref = f"{BQ_DATASET}.sync_log"
    client.insert_rows_json(table_ref, rows)


@functions_framework.http
def ingest_batch(request):
    """HTTP Cloud Function entry point.

    Expects:
        Headers:
            X-Gateway-ID: Edge gateway identifier
            X-Batch-ID: UUID for idempotency
            Content-Encoding: gzip (optional)
            X-API-Key: Authentication token
        Body: JSON with { readings: [...], alerts: [...], predictions: [...] }
    """
    # Validate API key
    api_key = request.headers.get("X-API-Key", "")
    # In production, validate against Secret Manager
    if not api_key:
        return {"error": "Missing API key"}, 401

    gateway_id = request.headers.get("X-Gateway-ID", "unknown")
    batch_id = request.headers.get("X-Batch-ID", "")
    if not batch_id:
        return {"error": "Missing X-Batch-ID header"}, 400

    bq_client = get_bq_client()

    # Idempotency check
    if verify_batch_idempotency(bq_client, batch_id):
        return {"status": "already_processed", "batch_id": batch_id}, 200

    # Decompress if gzipped
    raw_data = request.get_data()
    content_encoding = request.headers.get("Content-Encoding", "")
    if content_encoding == "gzip" or raw_data[:2] == b"\x1f\x8b":
        try:
            raw_data_decompressed = gzip.decompress(raw_data)
        except Exception as e:
            return {"error": f"Decompression failed: {e}"}, 400
    else:
        raw_data_decompressed = raw_data

    try:
        payload = json.loads(raw_data_decompressed)
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON: {e}"}, 400

    # Archive raw batch
    gcs_client = get_gcs_client()
    gcs_path = store_raw_batch(gcs_client, batch_id, raw_data)

    # Insert data
    readings_count = insert_readings(bq_client, payload.get("readings", []), gateway_id)
    alerts_count = insert_alerts(bq_client, payload.get("alerts", []), gateway_id)

    # Log sync event
    log_sync(bq_client, batch_id, gateway_id, readings_count, alerts_count, gcs_path)

    logger.info(
        "Batch %s from gateway %s: %d readings, %d alerts",
        batch_id, gateway_id, readings_count, alerts_count,
    )

    return {
        "status": "ok",
        "batch_id": batch_id,
        "readings_ingested": readings_count,
        "alerts_ingested": alerts_count,
        "archive": gcs_path,
    }, 200
