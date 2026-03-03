"""Shared test fixtures for JalNetra edge gateway tests."""

import asyncio
import os
import tempfile
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest.fixture(scope="session")
def event_loop():
    """Use a single event loop for all async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def _env_setup(tmp_path: Path) -> None:
    """Set up environment variables for testing."""
    os.environ["JALNETRA_ENV"] = "test"
    os.environ["DATABASE_PATH"] = str(tmp_path / "test.db")
    os.environ["MODEL_DIR"] = str(tmp_path / "models")
    os.environ["LOG_LEVEL"] = "DEBUG"
    os.environ["LORA_SIMULATION_MODE"] = "true"
    os.environ["ALERT_DRY_RUN"] = "true"
    os.environ["CLOUD_SYNC_ENABLED"] = "false"
    Path(os.environ["MODEL_DIR"]).mkdir(parents=True, exist_ok=True)


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """Create an async test client for the FastAPI application."""
    from edge.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def sample_reading() -> dict[str, Any]:
    """A clean water reading within BIS IS 10500:2012 acceptable limits."""
    return {
        "node_id": "N001",
        "tds": 320.5,
        "ph": 7.2,
        "turbidity": 0.8,
        "dissolved_oxygen": 7.1,
        "flow_rate": 5.5,
        "water_level": 8.3,
        "battery_pct": 85,
        "rssi_dbm": -65,
    }


@pytest.fixture
def contaminated_reading() -> dict[str, Any]:
    """A reading indicating contamination."""
    return {
        "node_id": "N001",
        "tds": 2500.0,
        "ph": 5.2,
        "turbidity": 35.0,
        "dissolved_oxygen": 1.5,
        "flow_rate": 3.0,
        "water_level": 15.2,
        "battery_pct": 70,
        "rssi_dbm": -75,
    }


@pytest.fixture
def sensor_fault_reading() -> dict[str, Any]:
    """A reading indicating a sensor fault."""
    return {
        "node_id": "N002",
        "tds": 0.0,
        "ph": 0.0,
        "turbidity": 0.0,
        "dissolved_oxygen": 0.0,
        "flow_rate": 0.0,
        "water_level": 0.0,
        "battery_pct": 15,
        "rssi_dbm": -95,
    }


@pytest.fixture
def sample_lora_packet() -> bytes:
    """A valid 32-byte LoRa packet."""
    import struct
    from edge.utils.validators import compute_crc16

    payload = bytearray(32)
    # Node ID = 0x0001
    struct.pack_into(">H", payload, 0, 0x0001)
    # Msg type = 0x01 (reading)
    payload[2] = 0x01
    # TDS = 350
    struct.pack_into(">H", payload, 3, 350)
    # pH = 720 (7.20 * 100)
    struct.pack_into(">H", payload, 5, 720)
    # Turbidity = 150 (1.50 * 100)
    struct.pack_into(">H", payload, 7, 150)
    # Flow = 550 (5.50 * 100)
    struct.pack_into(">H", payload, 9, 550)
    # Level = 830 cm
    struct.pack_into(">H", payload, 11, 830)
    # Battery = 85%
    payload[13] = 85
    # RSSI = -65 dBm
    struct.pack_into("b", payload, 14, -65)

    # CRC-16 over first 30 bytes
    crc = compute_crc16(bytes(payload[:30]))
    struct.pack_into(">H", payload, 30, crc)

    return bytes(payload)
