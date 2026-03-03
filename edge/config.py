"""JalNetra Edge Gateway — Configuration via Pydantic Settings.

Loads all configuration from environment variables with sensible defaults.
Includes BIS IS 10500:2012 water quality thresholds as frozen constants.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# BIS IS 10500:2012 Water Quality Thresholds (immutable constants)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class _ThresholdRange:
    """A single water quality parameter threshold band."""
    acceptable_min: float | None = None
    acceptable_max: float | None = None
    alert_min: float | None = None
    alert_max: float | None = None
    critical_min: float | None = None
    critical_max: float | None = None
    unit: str = ""


@dataclass(frozen=True, slots=True)
class _BISThresholds:
    """BIS IS 10500:2012 Drinking Water Quality Thresholds."""

    tds: _ThresholdRange = _ThresholdRange(
        acceptable_max=500.0,
        alert_max=500.0,
        critical_max=2000.0,
        unit="ppm",
    )
    ph: _ThresholdRange = _ThresholdRange(
        acceptable_min=6.5,
        acceptable_max=8.5,
        alert_min=6.0,
        alert_max=9.0,
        critical_min=5.5,
        critical_max=9.5,
        unit="pH",
    )
    turbidity: _ThresholdRange = _ThresholdRange(
        acceptable_max=1.0,
        alert_max=5.0,
        critical_max=25.0,
        unit="NTU",
    )
    dissolved_oxygen: _ThresholdRange = _ThresholdRange(
        acceptable_min=6.0,
        alert_min=4.0,
        critical_min=2.0,
        unit="mg/L",
    )


BIS_THRESHOLDS: Final[_BISThresholds] = _BISThresholds()


# ---------------------------------------------------------------------------
# Severity enum used across alert evaluation
# ---------------------------------------------------------------------------

class AlertSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Source type enum for sensor nodes
# ---------------------------------------------------------------------------

class SourceType(StrEnum):
    BOREWELL = "borewell"
    HANDPUMP = "handpump"
    CANAL = "canal"
    RESERVOIR = "reservoir"
    TAP = "tap"


# ---------------------------------------------------------------------------
# Main application settings
# ---------------------------------------------------------------------------

class Settings(BaseSettings):
    """Central configuration loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -- Edge Gateway Identity ------------------------------------------------
    jalnetra_node_id: str = Field(
        default="JN-DL-001",
        description="Unique identifier for this edge gateway",
    )
    jalnetra_village_id: str = Field(
        default="110001",
        description="Village ID this gateway serves",
    )

    # -- Database -------------------------------------------------------------
    jalnetra_db_path: Path = Field(
        default=Path("/opt/jalnetra/data/jalnetra.db"),
        description="Path to the local SQLite database",
    )

    # -- AI / ML Models -------------------------------------------------------
    jalnetra_model_dir: Path = Field(
        default=Path("/opt/jalnetra/edge/models_onnx/"),
        description="Directory containing ONNX model files",
    )
    anomaly_model_file: str = "anomaly_detector_int8.onnx"
    depletion_model_file: str = "depletion_predictor_bf16.onnx"
    irrigation_model_file: str = "irrigation_optimizer_int8.onnx"

    # -- LoRa Receiver --------------------------------------------------------
    jalnetra_lora_port: str = Field(
        default="/dev/ttyUSB0",
        description="Serial port for LoRa receiver dongle",
    )
    jalnetra_lora_baud: int = Field(
        default=115200,
        description="Baud rate for LoRa serial communication",
    )
    lora_frequency_mhz: float = Field(
        default=866.0,
        description="LoRa frequency in MHz (India ISM 865-867)",
    )
    lora_spreading_factor: int = Field(default=7, ge=7, le=12)
    lora_bandwidth_khz: int = Field(default=125)
    lora_tx_power_dbm: int = Field(default=20, le=20)

    # -- Alert Service Credentials -------------------------------------------
    msg91_auth_key: str = Field(default="", description="MSG91 SMS auth key")
    msg91_sender_id: str = Field(default="JALNET", description="MSG91 sender ID")
    msg91_template_id: str = Field(default="", description="MSG91 template ID")

    whatsapp_token: str = Field(default="", description="WhatsApp Business API token")
    whatsapp_phone_id: str = Field(default="", description="WhatsApp phone number ID")

    twilio_account_sid: str = Field(default="", description="Twilio account SID")
    twilio_auth_token: str = Field(default="", description="Twilio auth token")
    twilio_from_number: str = Field(
        default="",
        description="Twilio source phone number (E.164)",
    )

    bhashini_api_key: str = Field(
        default="",
        description="Bhashini API key for TTS / ASR / translation",
    )
    bhashini_api_url: str = Field(
        default="https://dhruva-api.bhashini.gov.in/services/inference/pipeline",
    )

    # -- Cloud Sync -----------------------------------------------------------
    cloud_sync_url: str = Field(
        default="https://api.jalnetra.dmj.one/v1/sync",
        description="Cloud ingestion endpoint",
    )
    cloud_sync_api_key: str = Field(default="", description="Cloud sync API key")
    cloud_sync_interval_hours: int = Field(
        default=6,
        ge=1,
        description="Hours between batch cloud syncs",
    )

    # -- Security / Dashboard ------------------------------------------------
    jalnetra_secret_key: str = Field(
        default="change-me-in-production",
        min_length=8,
        description="Secret key for JWT signing & session cookies",
    )
    jalnetra_jwt_expiry: int = Field(
        default=3600,
        ge=60,
        description="JWT token expiry in seconds",
    )

    # -- Server ---------------------------------------------------------------
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000, ge=1, le=65535)
    debug: bool = Field(default=False)
    log_level: str = Field(default="info")
    cors_origins: list[str] = Field(default=["*"])

    # -- Sensor Sampling ------------------------------------------------------
    sensor_read_interval_s: int = Field(
        default=30,
        ge=1,
        description="Default sensor sampling interval in seconds",
    )
    groundwater_critical_level_m: float = Field(
        default=5.0,
        description="Below this level (metres), borewell is at risk",
    )

    # -- Validators -----------------------------------------------------------

    @field_validator("jalnetra_db_path", mode="before")
    @classmethod
    def _coerce_db_path(cls, v: str | Path) -> Path:
        return Path(v)

    @field_validator("jalnetra_model_dir", mode="before")
    @classmethod
    def _coerce_model_dir(cls, v: str | Path) -> Path:
        return Path(v)

    # -- Convenience helpers --------------------------------------------------

    @property
    def anomaly_model_path(self) -> Path:
        return self.jalnetra_model_dir / self.anomaly_model_file

    @property
    def depletion_model_path(self) -> Path:
        return self.jalnetra_model_dir / self.depletion_model_file

    @property
    def irrigation_model_path(self) -> Path:
        return self.jalnetra_model_dir / self.irrigation_model_file

    @property
    def version(self) -> str:
        return "1.0.0"


# Module-level singleton — import `settings` anywhere.
settings = Settings()
