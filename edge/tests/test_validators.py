"""Tests for water quality validation and LoRa packet parsing."""

import struct

import pytest

from edge.utils.validators import (
    ValidationResult,
    WaterQualityStatus,
    check_parameter,
    compute_crc16,
    parse_lora_packet,
    validate_reading,
)


class TestWaterQualityValidation:
    """BIS IS 10500:2012 threshold compliance tests."""

    def test_clean_water_passes(self) -> None:
        result = validate_reading(tds=300, ph=7.2, turbidity=0.5, dissolved_oxygen=7.0)
        assert result.valid
        assert result.status == WaterQualityStatus.SAFE
        assert result.overall_score >= 90.0
        assert len(result.violations) == 0

    def test_high_tds_alert(self) -> None:
        result = validate_reading(tds=800, ph=7.2, turbidity=0.5, dissolved_oxygen=7.0)
        assert not result.valid
        assert result.status >= WaterQualityStatus.ALERT

    def test_critical_tds(self) -> None:
        result = validate_reading(tds=2500, ph=7.2, turbidity=0.5, dissolved_oxygen=7.0)
        assert result.status == WaterQualityStatus.CRITICAL

    def test_low_ph_critical(self) -> None:
        result = validate_reading(tds=300, ph=4.5, turbidity=0.5, dissolved_oxygen=7.0)
        assert result.status == WaterQualityStatus.CRITICAL

    def test_high_ph_critical(self) -> None:
        result = validate_reading(tds=300, ph=10.0, turbidity=0.5, dissolved_oxygen=7.0)
        assert result.status == WaterQualityStatus.CRITICAL

    def test_high_turbidity_critical(self) -> None:
        result = validate_reading(tds=300, ph=7.2, turbidity=30.0, dissolved_oxygen=7.0)
        assert result.status == WaterQualityStatus.CRITICAL

    def test_low_do_critical(self) -> None:
        result = validate_reading(tds=300, ph=7.2, turbidity=0.5, dissolved_oxygen=1.5)
        assert result.status == WaterQualityStatus.CRITICAL

    def test_out_of_physical_range_invalid(self) -> None:
        result = validate_reading(tds=-10, ph=7.2, turbidity=0.5)
        assert not result.valid
        assert result.overall_score == 0.0

    def test_multiple_violations(self) -> None:
        result = validate_reading(tds=2500, ph=4.5, turbidity=50, dissolved_oxygen=1.0)
        assert result.status == WaterQualityStatus.CRITICAL
        assert len(result.violations) >= 3

    def test_borderline_acceptable(self) -> None:
        result = validate_reading(tds=500, ph=6.5, turbidity=1.0, dissolved_oxygen=6.0)
        assert result.valid
        assert result.status == WaterQualityStatus.SAFE


class TestCheckParameter:
    """Individual parameter threshold checks."""

    def test_tds_acceptable(self) -> None:
        status, _ = check_parameter("tds", 400)
        assert status == WaterQualityStatus.SAFE

    def test_tds_alert(self) -> None:
        status, violation = check_parameter("tds", 800)
        assert status == WaterQualityStatus.ALERT
        assert violation is not None

    def test_ph_acceptable_range(self) -> None:
        for ph in [6.5, 7.0, 7.5, 8.0, 8.5]:
            status, _ = check_parameter("ph", ph)
            assert status == WaterQualityStatus.SAFE

    def test_unknown_parameter(self) -> None:
        status, violation = check_parameter("unknown_param", 42)
        assert status == WaterQualityStatus.SAFE
        assert violation is None


class TestCRC16:
    """CRC-16/CCITT-FALSE implementation tests."""

    def test_empty_data(self) -> None:
        assert compute_crc16(b"") == 0xFFFF

    def test_known_value(self) -> None:
        # "123456789" should yield 0x29B1 for CRC-16/CCITT-FALSE
        result = compute_crc16(b"123456789")
        assert result == 0x29B1

    def test_consistency(self) -> None:
        data = b"JalNetra sensor data packet"
        assert compute_crc16(data) == compute_crc16(data)

    def test_single_bit_change_detected(self) -> None:
        data1 = b"\x01\x02\x03\x04"
        data2 = b"\x01\x02\x03\x05"
        assert compute_crc16(data1) != compute_crc16(data2)


class TestLoRaPacketParsing:
    """LoRa packet parsing and validation."""

    def test_valid_packet(self, sample_lora_packet: bytes) -> None:
        result = parse_lora_packet(sample_lora_packet)
        assert result is not None
        assert result["node_id"] == 1
        assert result["msg_type"] == 1
        assert result["tds"] == 350.0
        assert result["ph"] == pytest.approx(7.2, abs=0.01)
        assert result["turbidity"] == pytest.approx(1.5, abs=0.01)
        assert result["flow_rate"] == pytest.approx(5.5, abs=0.01)
        assert result["water_level"] == pytest.approx(8.3, abs=0.01)
        assert result["battery_pct"] == 85
        assert result["rssi_dbm"] == -65

    def test_wrong_size_rejected(self) -> None:
        assert parse_lora_packet(b"\x00" * 16) is None
        assert parse_lora_packet(b"\x00" * 64) is None

    def test_corrupted_crc_rejected(self, sample_lora_packet: bytes) -> None:
        corrupted = bytearray(sample_lora_packet)
        corrupted[30] ^= 0xFF  # Flip CRC bits
        assert parse_lora_packet(bytes(corrupted)) is None

    def test_data_corruption_detected(self, sample_lora_packet: bytes) -> None:
        corrupted = bytearray(sample_lora_packet)
        corrupted[5] ^= 0x01  # Flip one data bit
        assert parse_lora_packet(bytes(corrupted)) is None
