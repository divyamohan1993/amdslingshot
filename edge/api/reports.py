"""JalNetra Edge Gateway — JJM compliance reports API endpoints.

Routes:
    GET /api/v1/reports/jjm     — Jal Jeevan Mission compliance report
    GET /api/v1/reports/summary — Daily / weekly / monthly water quality summary
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from edge.config import BIS_THRESHOLDS, settings
from edge.database import Database, db

logger = logging.getLogger("jalnetra.api.reports")

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ParameterCompliance(BaseModel):
    parameter: str
    unit: str
    avg_value: float | None = None
    min_value: float | None = None
    max_value: float | None = None
    acceptable_limit: float | str | None = None
    compliant: bool = True
    breach_count: int = 0


class NodeCompliance(BaseModel):
    node_id: str
    location_name: str
    source_type: str | None = None
    total_readings: int = 0
    parameters: list[ParameterCompliance]
    overall_compliant: bool = True


class JJMReportResponse(BaseModel):
    """Jal Jeevan Mission compliance report."""

    report_title: str
    gateway_id: str
    village_id: str
    period_start: str
    period_end: str
    generated_at: str
    total_nodes: int
    compliant_nodes: int
    non_compliant_nodes: int
    node_reports: list[NodeCompliance]
    summary: str


class SummaryPeriod(BaseModel):
    period: str  # "daily", "weekly", "monthly"
    start: str
    end: str


class ReadingSummaryStats(BaseModel):
    reading_count: int = 0
    avg_tds: float | None = None
    min_tds: float | None = None
    max_tds: float | None = None
    avg_ph: float | None = None
    min_ph: float | None = None
    max_ph: float | None = None
    avg_turbidity: float | None = None
    min_turbidity: float | None = None
    max_turbidity: float | None = None
    avg_flow_rate: float | None = None
    avg_water_level: float | None = None
    min_water_level: float | None = None
    max_water_level: float | None = None


class SummaryReportResponse(BaseModel):
    gateway_id: str
    village_id: str
    period: SummaryPeriod
    generated_at: str
    node_id: str | None = None
    stats: ReadingSummaryStats
    alert_count: int = 0
    critical_alerts: int = 0


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


async def _get_db() -> Database:
    return db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PERIOD_DELTAS: dict[str, timedelta] = {
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
    "monthly": timedelta(days=30),
}


def _compute_period(period: str) -> tuple[str, str]:
    """Return (start_iso, end_iso) for a named period ending now."""
    now = datetime.now(timezone.utc)
    delta = _PERIOD_DELTAS.get(period, timedelta(days=1))
    start = (now - delta).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    end = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return start, end


async def _evaluate_node_compliance(
    database: Database,
    node: dict[str, Any],
    since: str,
    until: str,
) -> NodeCompliance:
    """Check a node's readings against BIS thresholds for the given period."""
    node_id = node["id"]
    readings = await database.list_readings(
        node_id=node_id, since=since, until=until, limit=100_000
    )
    total = len(readings)
    th = BIS_THRESHOLDS

    # Aggregate per parameter
    def _agg(key: str) -> tuple[float | None, float | None, float | None]:
        vals = [r[key] for r in readings if r.get(key) is not None]
        if not vals:
            return None, None, None
        return round(sum(vals) / len(vals), 2), round(min(vals), 2), round(max(vals), 2)

    avg_tds, min_tds, max_tds = _agg("tds")
    avg_ph, min_ph, max_ph = _agg("ph")
    avg_turb, min_turb, max_turb = _agg("turbidity")

    params: list[ParameterCompliance] = []

    # TDS
    tds_breaches = sum(1 for r in readings if r.get("tds") is not None and r["tds"] > (th.tds.acceptable_max or float("inf")))
    tds_compliant = tds_breaches == 0
    params.append(ParameterCompliance(
        parameter="TDS",
        unit=th.tds.unit,
        avg_value=avg_tds,
        min_value=min_tds,
        max_value=max_tds,
        acceptable_limit=th.tds.acceptable_max,
        compliant=tds_compliant,
        breach_count=tds_breaches,
    ))

    # pH
    ph_breaches = sum(
        1 for r in readings
        if r.get("ph") is not None and (
            r["ph"] < (th.ph.acceptable_min or 0) or r["ph"] > (th.ph.acceptable_max or 14)
        )
    )
    ph_compliant = ph_breaches == 0
    params.append(ParameterCompliance(
        parameter="pH",
        unit=th.ph.unit,
        avg_value=avg_ph,
        min_value=min_ph,
        max_value=max_ph,
        acceptable_limit=f"{th.ph.acceptable_min}-{th.ph.acceptable_max}",
        compliant=ph_compliant,
        breach_count=ph_breaches,
    ))

    # Turbidity
    turb_breaches = sum(
        1 for r in readings
        if r.get("turbidity") is not None and r["turbidity"] > (th.turbidity.acceptable_max or float("inf"))
    )
    turb_compliant = turb_breaches == 0
    params.append(ParameterCompliance(
        parameter="Turbidity",
        unit=th.turbidity.unit,
        avg_value=avg_turb,
        min_value=min_turb,
        max_value=max_turb,
        acceptable_limit=th.turbidity.acceptable_max,
        compliant=turb_compliant,
        breach_count=turb_breaches,
    ))

    overall = tds_compliant and ph_compliant and turb_compliant

    return NodeCompliance(
        node_id=node_id,
        location_name=node.get("location_name", ""),
        source_type=node.get("source_type"),
        total_readings=total,
        parameters=params,
        overall_compliant=overall,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/jjm", response_model=JJMReportResponse)
async def jjm_compliance_report(
    month: str | None = Query(
        None,
        description="Report month in YYYY-MM format (defaults to current month)",
    ),
    database: Database = Depends(_get_db),
) -> JJMReportResponse:
    """Generate a Jal Jeevan Mission compliance report.

    Evaluates all nodes against BIS IS 10500:2012 thresholds for the
    specified month and produces a structured compliance summary.
    """
    now = datetime.now(timezone.utc)
    if month:
        try:
            year, mon = month.split("-")
            period_start = datetime(int(year), int(mon), 1, tzinfo=timezone.utc)
        except (ValueError, IndexError):
            period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # End of the month (or now if current month)
    if period_start.month == 12:
        period_end = period_start.replace(year=period_start.year + 1, month=1)
    else:
        period_end = period_start.replace(month=period_start.month + 1)
    if period_end > now:
        period_end = now

    since = period_start.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    until = period_end.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    nodes = await database.list_nodes()
    node_reports: list[NodeCompliance] = []
    for node in nodes:
        report = await _evaluate_node_compliance(database, node, since, until)
        node_reports.append(report)

    compliant = sum(1 for nr in node_reports if nr.overall_compliant)
    non_compliant = len(node_reports) - compliant

    summary_parts: list[str] = [
        f"JJM Compliance Report for village {settings.jalnetra_village_id}.",
        f"Period: {since[:10]} to {until[:10]}.",
        f"Nodes monitored: {len(nodes)}.",
        f"Compliant: {compliant}, Non-compliant: {non_compliant}.",
    ]
    if non_compliant:
        bad_nodes = [nr.node_id for nr in node_reports if not nr.overall_compliant]
        summary_parts.append(
            f"Non-compliant sources: {', '.join(bad_nodes)}. Remediation recommended."
        )

    return JJMReportResponse(
        report_title="Jal Jeevan Mission — Water Quality Compliance Report",
        gateway_id=settings.jalnetra_node_id,
        village_id=settings.jalnetra_village_id,
        period_start=since,
        period_end=until,
        generated_at=now.isoformat(),
        total_nodes=len(nodes),
        compliant_nodes=compliant,
        non_compliant_nodes=non_compliant,
        node_reports=node_reports,
        summary=" ".join(summary_parts),
    )


@router.get("/summary", response_model=SummaryReportResponse)
async def summary_report(
    period: str = Query(
        "daily",
        description="Summary period: daily, weekly, or monthly",
        pattern="^(daily|weekly|monthly)$",
    ),
    node_id: str | None = Query(None, description="Optional node filter"),
    database: Database = Depends(_get_db),
) -> SummaryReportResponse:
    """Generate a water quality summary for a given period.

    Aggregates average, min, and max values across all parameters.
    """
    since, until = _compute_period(period)
    raw = await database.get_readings_summary(
        node_id=node_id, since=since, until=until
    )

    alert_stats = await database.get_alert_stats(node_id=node_id, since=since)

    return SummaryReportResponse(
        gateway_id=settings.jalnetra_node_id,
        village_id=settings.jalnetra_village_id,
        period=SummaryPeriod(period=period, start=since, end=until),
        generated_at=datetime.now(timezone.utc).isoformat(),
        node_id=node_id,
        stats=ReadingSummaryStats(
            reading_count=raw.get("reading_count", 0) or 0,
            avg_tds=_safe_round(raw.get("avg_tds")),
            min_tds=_safe_round(raw.get("min_tds")),
            max_tds=_safe_round(raw.get("max_tds")),
            avg_ph=_safe_round(raw.get("avg_ph")),
            min_ph=_safe_round(raw.get("min_ph")),
            max_ph=_safe_round(raw.get("max_ph")),
            avg_turbidity=_safe_round(raw.get("avg_turbidity")),
            min_turbidity=_safe_round(raw.get("min_turbidity")),
            max_turbidity=_safe_round(raw.get("max_turbidity")),
            avg_flow_rate=_safe_round(raw.get("avg_flow_rate")),
            avg_water_level=_safe_round(raw.get("avg_water_level")),
            min_water_level=_safe_round(raw.get("min_water_level")),
            max_water_level=_safe_round(raw.get("max_water_level")),
        ),
        alert_count=alert_stats.get("total", 0) or 0,
        critical_alerts=alert_stats.get("critical", 0) or 0,
    )


def _safe_round(val: Any, digits: int = 2) -> float | None:
    if val is None:
        return None
    try:
        return round(float(val), digits)
    except (TypeError, ValueError):
        return None
