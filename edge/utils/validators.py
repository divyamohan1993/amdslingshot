"""Data validation utilities for JalNetra sensor readings."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import NamedTuple


class WaterQualityStatus(IntEnum):
    """Water quality status levels per BIS IS 10500:2012."""
    SAFE = 0
    ACCEPTABLE = 1
    ALERT = 2
    CRITICAL = 3


class ThresholdRange(NamedTuple):
    """Min/max bounds for a threshold check."""
    low: float | None
    high: float | None


# BIS IS 10500:2012 thresholds
THRESHOLDS: dict[str, dict[str, ThresholdRange]] = {
    "tds": {
        "acceptable": ThresholdRange(None, 500.0),
        "alert": ThresholdRange(500.0, 2000.0),
        "critical": ThresholdRange(2000.0, None),
    },
    "ph": {
        "acceptable": ThresholdRange(6.5, 8.5),
        "alert_low": ThresholdRange(5.5, 6.5),
        "alert_high": ThresholdRange(8.5, 9.5),
        "critical_low": ThresholdRange(None, 5.5),
        "critical_high": ThresholdRange(9.5, None),
    },
    "turbidity": {
        "acceptable": ThresholdRange(None, 1.0),
        "alert": ThresholdRange(1.0, 25.0),
        "critical": ThresholdRange(25.0, None),
    },
    "dissolved_oxygen": {
        "acceptable": ThresholdRange(6.0, None),
        "alert": ThresholdRange(2.0, 6.0),
        "critical": ThresholdRange(None, 2.0),
    },
}


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Result of validating a sensor reading."""
    valid: bool
    status: WaterQualityStatus
    violations: list[str]
    overall_score: float  # 0-100, 100 = perfect


def check_parameter(name: str, value: float) -> tuple[WaterQualityStatus, str | None]:
    """Check a single parameter against BIS thresholds."""
    if name not in THRESHOLDS:
        return WaterQualityStatus.SAFE, None

    thresholds = THRESHOLDS[name]

    if name == "ph":
        if thresholds["critical_low"].high is not None and value < thresholds["critical_low"].high:
            return WaterQualityStatus.CRITICAL, f"pH {value:.1f} critically low (<5.5)"
        if thresholds["critical_high"].low is not None and value > thresholds["critical_high"].low:
            return WaterQualityStatus.CRITICAL, f"pH {value:.1f} critically high (>9.5)"
        if thresholds["alert_low"].low is not None and value < thresholds["alert_low"].high:
            return WaterQualityStatus.ALERT, f"pH {value:.1f} below acceptable (6.5)"
        if thresholds["alert_high"].low is not None and value > thresholds["alert_high"].low:
            return WaterQualityStatus.ALERT, f"pH {value:.1f} above acceptable (8.5)"
        return WaterQualityStatus.SAFE, None

    if name == "dissolved_oxygen":
        if thresholds["critical"].high is not None and value < thresholds["critical"].high:
            return WaterQualityStatus.CRITICAL, f"DO {value:.1f} mg/L critically low (<2)"
        if thresholds["alert"].low is not None and value < thresholds["alert"].low:
            return WaterQualityStatus.ALERT, f"DO {value:.1f} mg/L below acceptable (<6)"
        return WaterQualityStatus.SAFE, None

    # Standard threshold check (TDS, turbidity)
    acceptable = thresholds.get("acceptable")
    if acceptable and acceptable.high is not None and value <= acceptable.high:
        return WaterQualityStatus.SAFE, None

    critical = thresholds.get("critical")
    if critical and critical.low is not None and value >= critical.low:
        return WaterQualityStatus.CRITICAL, f"{name} {value:.1f} critical (>={critical.low})"

    alert = thresholds.get("alert")
    if alert:
        return WaterQualityStatus.ALERT, f"{name} {value:.1f} elevated"

    return WaterQualityStatus.SAFE, None


def validate_reading(
    tds: float,
    ph: float,
    turbidity: float,
    dissolved_oxygen: float = 7.0,
    flow_rate: float = 0.0,
    water_level: float = 0.0,
) -> ValidationResult:
    """Validate a complete sensor reading against BIS IS 10500:2012."""
    violations: list[str] = []
    worst_status = WaterQualityStatus.SAFE

    # Physical range checks
    range_checks = [
        ("tds", tds, 0.0, 10000.0),
        ("ph", ph, 0.0, 14.0),
        ("turbidity", turbidity, 0.0, 5000.0),
        ("dissolved_oxygen", dissolved_oxygen, 0.0, 20.0),
        ("flow_rate", flow_rate, 0.0, 100.0),
        ("water_level", water_level, 0.0, 200.0),
    ]

    for name, value, lo, hi in range_checks:
        if not (lo <= value <= hi):
            violations.append(f"{name}={value} out of physical range [{lo}, {hi}]")
            return ValidationResult(
                valid=False,
                status=WaterQualityStatus.CRITICAL,
                violations=violations,
                overall_score=0.0,
            )

    # BIS threshold checks
    params = {
        "tds": tds,
        "ph": ph,
        "turbidity": turbidity,
        "dissolved_oxygen": dissolved_oxygen,
    }
    scores: list[float] = []
    for name, value in params.items():
        status, violation = check_parameter(name, value)
        if status > worst_status:
            worst_status = status
        if violation:
            violations.append(violation)
        # Score each parameter 0-100
        if status == WaterQualityStatus.SAFE:
            scores.append(100.0)
        elif status == WaterQualityStatus.ALERT:
            scores.append(50.0)
        else:
            scores.append(10.0)

    overall = sum(scores) / len(scores) if scores else 0.0

    return ValidationResult(
        valid=len(violations) == 0,
        status=worst_status,
        violations=violations,
        overall_score=round(overall, 1),
    )


def compute_crc16(data: bytes) -> int:
    """Compute CRC-16/CCITT-FALSE for LoRa packet validation."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc


def parse_lora_packet(raw: bytes) -> dict | None:
    """Parse a 32-byte LoRa sensor packet.

    Packet format:
        node_id:   2 bytes (uint16, big-endian)
        msg_type:  1 byte  (uint8: 0x01=reading, 0x02=heartbeat, 0x03=alert)
        tds:       2 bytes (uint16, value in ppm)
        ph:        2 bytes (uint16, value * 100)
        turbidity: 2 bytes (uint16, value * 100 NTU)
        flow:      2 bytes (uint16, value * 100 L/min)
        level:     2 bytes (uint16, value in cm)
        battery:   1 byte  (uint8, percentage 0-100)
        rssi:      1 byte  (int8, dBm)
        reserved:  15 bytes
        crc16:     2 bytes (uint16, big-endian, over first 30 bytes)
    """
    if len(raw) != 32:
        return None

    payload = raw[:30]
    received_crc = struct.unpack(">H", raw[30:32])[0]
    if compute_crc16(payload) != received_crc:
        return None

    node_id, msg_type = struct.unpack(">HB", raw[0:3])
    tds, ph_raw, turb_raw, flow_raw, level_cm = struct.unpack(">HHHHH", raw[3:13])
    battery = raw[13]
    rssi = struct.unpack("b", raw[14:15])[0]

    return {
        "node_id": node_id,
        "msg_type": msg_type,
        "tds": float(tds),
        "ph": ph_raw / 100.0,
        "turbidity": turb_raw / 100.0,
        "flow_rate": flow_raw / 100.0,
        "water_level": level_cm / 100.0,
        "battery_pct": battery,
        "rssi_dbm": rssi,
    }
