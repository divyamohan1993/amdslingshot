"""
JalNetra — Realistic Training Data Generator
=============================================

Generates statistically realistic water quality, groundwater level, and irrigation
training data modeled after real Indian water conditions.

Data distributions are based on:
- CPCB (Central Pollution Control Board) National Water Quality Monitoring Programme
- BIS IS 10500:2012 Drinking Water Specification
- India-WRIS (Water Resources Information System) groundwater records
- ICAR crop water requirement bulletins
- IMD (India Meteorological Department) climate normals

Author: JalNetra / dmj.one
License: MIT
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants — Indian Water Quality Standards (BIS IS 10500:2012)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WaterQualityLimits:
    """BIS IS 10500:2012 acceptable / permissible limits."""
    tds_acceptable: float = 500.0        # mg/L
    tds_permissible: float = 2000.0
    ph_min: float = 6.5
    ph_max: float = 8.5
    turbidity_acceptable: float = 1.0    # NTU
    turbidity_permissible: float = 5.0
    do_min: float = 6.0                  # mg/L dissolved oxygen


BIS_LIMITS = WaterQualityLimits()


class AnomalyLabel(IntEnum):
    """Anomaly classification labels for water quality readings."""
    NORMAL = 0
    CONTAMINATION = 1
    SENSOR_FAULT = 2


# ---------------------------------------------------------------------------
# Crop Database — Indian crop water requirements (ICAR)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CropProfile:
    """Water requirement profile for a crop variety."""
    name: str
    crop_id: int
    stages: int                          # number of growth stages
    total_water_mm: float                # total seasonal water need (mm)
    kc_values: tuple[float, ...]         # crop coefficient per stage
    season: str                          # kharif / rabi / zaid
    root_depth_m: float = 0.6


CROP_DATABASE: dict[str, CropProfile] = {
    "rice_kharif": CropProfile(
        name="Rice (Kharif)", crop_id=0, stages=4,
        total_water_mm=1200.0, kc_values=(1.05, 1.20, 1.15, 0.70),
        season="kharif", root_depth_m=0.3,
    ),
    "wheat_rabi": CropProfile(
        name="Wheat (Rabi)", crop_id=1, stages=4,
        total_water_mm=450.0, kc_values=(0.35, 0.75, 1.15, 0.45),
        season="rabi", root_depth_m=0.9,
    ),
    "sugarcane": CropProfile(
        name="Sugarcane", crop_id=2, stages=4,
        total_water_mm=2000.0, kc_values=(0.40, 0.75, 1.25, 0.75),
        season="kharif", root_depth_m=1.2,
    ),
    "cotton": CropProfile(
        name="Cotton", crop_id=3, stages=4,
        total_water_mm=700.0, kc_values=(0.35, 0.75, 1.20, 0.60),
        season="kharif", root_depth_m=1.0,
    ),
    "mustard_rabi": CropProfile(
        name="Mustard (Rabi)", crop_id=4, stages=4,
        total_water_mm=350.0, kc_values=(0.35, 0.70, 1.05, 0.40),
        season="rabi", root_depth_m=0.8,
    ),
    "maize_kharif": CropProfile(
        name="Maize (Kharif)", crop_id=5, stages=4,
        total_water_mm=500.0, kc_values=(0.30, 0.70, 1.20, 0.50),
        season="kharif", root_depth_m=0.8,
    ),
    "groundnut": CropProfile(
        name="Groundnut", crop_id=6, stages=4,
        total_water_mm=500.0, kc_values=(0.40, 0.75, 1.05, 0.55),
        season="kharif", root_depth_m=0.6,
    ),
    "vegetables_mixed": CropProfile(
        name="Mixed Vegetables", crop_id=7, stages=3,
        total_water_mm=400.0, kc_values=(0.50, 0.90, 0.70),
        season="zaid", root_depth_m=0.4,
    ),
}

# Soil types common in India with field capacity and wilting point
SOIL_TYPES: dict[str, dict[str, float]] = {
    "alluvial":   {"fc": 0.35, "wp": 0.15, "infiltration_mm_hr": 25.0, "soil_id": 0},
    "black":      {"fc": 0.45, "wp": 0.20, "infiltration_mm_hr": 10.0, "soil_id": 1},
    "red":        {"fc": 0.28, "wp": 0.12, "infiltration_mm_hr": 30.0, "soil_id": 2},
    "laterite":   {"fc": 0.25, "wp": 0.10, "infiltration_mm_hr": 35.0, "soil_id": 3},
    "sandy":      {"fc": 0.18, "wp": 0.06, "infiltration_mm_hr": 50.0, "soil_id": 4},
    "clay":       {"fc": 0.42, "wp": 0.22, "infiltration_mm_hr": 5.0,  "soil_id": 5},
}


# ---------------------------------------------------------------------------
# Water Quality Data Generator
# ---------------------------------------------------------------------------

@dataclass
class WaterQualityConfig:
    """Configuration for water quality data generation."""
    n_samples: int = 50_000
    contamination_ratio: float = 0.12    # 12% contamination events
    sensor_fault_ratio: float = 0.05     # 5% sensor faults
    seed: Optional[int] = 42
    # Distribution parameters modeled on CPCB data
    tds_clean_mean: float = 450.0
    tds_clean_std: float = 180.0
    ph_clean_mean: float = 7.2
    ph_clean_std: float = 0.5
    turbidity_clean_mean: float = 3.0
    turbidity_clean_std: float = 2.0
    do_clean_mean: float = 7.5
    do_clean_std: float = 1.2
    flow_mean: float = 12.0
    flow_std: float = 6.0
    level_mean: float = 15.0
    level_std: float = 8.0


def generate_water_quality_data(
    config: Optional[WaterQualityConfig] = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Generate realistic water quality training data for anomaly detection.

    Produces sensor readings that follow real Indian water quality distributions
    from CPCB monitoring stations, with injected contamination events and
    sensor faults.

    Features (10):
        0: tds (mg/L)             — Total Dissolved Solids
        1: ph                     — pH value
        2: turbidity (NTU)        — Nephelometric Turbidity Units
        3: dissolved_oxygen (mg/L)— Dissolved Oxygen
        4: flow_rate (L/min)      — Water flow rate
        5: water_level (m)        — Groundwater depth in meters
        6: tds_rate (mg/L/hr)     — Rate of change of TDS
        7: ph_rate (/hr)          — Rate of change of pH
        8: hour_sin               — sin(2*pi*hour/24) temporal encoding
        9: hour_cos               — cos(2*pi*hour/24) temporal encoding

    Labels (3-class):
        0: normal
        1: contamination
        2: sensor_fault

    Args:
        config: Generation configuration. Uses defaults if None.

    Returns:
        Tuple of (features, labels) with shapes (n_samples, 10) and (n_samples,).
    """
    if config is None:
        config = WaterQualityConfig()

    rng = np.random.default_rng(config.seed)
    n = config.n_samples

    # Allocate arrays
    features = np.zeros((n, 10), dtype=np.float32)
    labels = np.zeros(n, dtype=np.int64)

    # Determine sample counts per class
    n_contamination = int(n * config.contamination_ratio)
    n_sensor_fault = int(n * config.sensor_fault_ratio)
    n_normal = n - n_contamination - n_sensor_fault

    # Assign labels
    labels[:n_normal] = AnomalyLabel.NORMAL
    labels[n_normal:n_normal + n_contamination] = AnomalyLabel.CONTAMINATION
    labels[n_normal + n_contamination:] = AnomalyLabel.SENSOR_FAULT

    # Shuffle for randomness
    shuffle_idx = rng.permutation(n)
    labels = labels[shuffle_idx]

    # --- Generate temporal features for all samples ---
    hours = rng.uniform(0, 24, size=n)
    features[:, 8] = np.sin(2 * np.pi * hours / 24.0)
    features[:, 9] = np.cos(2 * np.pi * hours / 24.0)

    # --- Normal samples ---
    normal_mask = labels == AnomalyLabel.NORMAL
    n_norm = normal_mask.sum()

    # TDS: lognormal distribution centered around clean Indian sources
    # BIS acceptable: <500, permissible: <2000
    features[normal_mask, 0] = np.clip(
        rng.lognormal(np.log(config.tds_clean_mean), 0.5, n_norm), 50, 1500
    )
    # pH: normal distribution around 7.2
    features[normal_mask, 1] = np.clip(
        rng.normal(config.ph_clean_mean, config.ph_clean_std, n_norm), 6.0, 9.0
    )
    # Turbidity: lognormal with most readings below 5 NTU
    features[normal_mask, 2] = np.clip(
        rng.lognormal(np.log(config.turbidity_clean_mean), 0.6, n_norm), 0.1, 20.0
    )
    # Dissolved oxygen: normal around 7.5 mg/L for clean flowing water
    features[normal_mask, 3] = np.clip(
        rng.normal(config.do_clean_mean, config.do_clean_std, n_norm), 3.0, 12.0
    )
    # Flow rate: half-normal distribution (always positive)
    features[normal_mask, 4] = np.clip(
        np.abs(rng.normal(config.flow_mean, config.flow_std, n_norm)), 0.5, 30.0
    )
    # Water level (depth in meters): varies by region
    features[normal_mask, 5] = np.clip(
        np.abs(rng.normal(config.level_mean, config.level_std, n_norm)), 2.0, 50.0
    )
    # Rate of change features: small for normal
    features[normal_mask, 6] = rng.normal(0, 5, n_norm)      # tds_rate
    features[normal_mask, 7] = rng.normal(0, 0.05, n_norm)   # ph_rate

    # --- Contamination events ---
    contam_mask = labels == AnomalyLabel.CONTAMINATION
    n_contam = contam_mask.sum()

    # Contamination subtypes (weighted random)
    contam_type = rng.choice(
        ["industrial", "sewage", "agricultural", "natural"],
        size=n_contam,
        p=[0.25, 0.35, 0.25, 0.15],
    )

    # Base values with contamination shifts
    for i, ct in enumerate(contam_type):
        idx = np.where(contam_mask)[0][i]
        if ct == "industrial":
            # High TDS, very low pH (acidic discharge), high turbidity
            features[idx, 0] = rng.uniform(1200, 2500)     # TDS
            features[idx, 1] = rng.uniform(3.5, 5.5)       # pH acidic
            features[idx, 2] = rng.uniform(15, 50)          # turbidity
            features[idx, 3] = rng.uniform(0.5, 3.0)        # low DO
        elif ct == "sewage":
            # Moderate TDS, slightly acidic, very high turbidity, very low DO
            features[idx, 0] = rng.uniform(800, 1800)
            features[idx, 1] = rng.uniform(5.5, 6.8)
            features[idx, 2] = rng.uniform(20, 50)
            features[idx, 3] = rng.uniform(0.5, 2.5)
        elif ct == "agricultural":
            # High TDS (fertilizer runoff), slightly alkaline, moderate turbidity
            features[idx, 0] = rng.uniform(900, 2000)
            features[idx, 1] = rng.uniform(7.8, 9.5)
            features[idx, 2] = rng.uniform(8, 30)
            features[idx, 3] = rng.uniform(2.0, 5.0)
        else:  # natural (mineral dissolution, seasonal)
            features[idx, 0] = rng.uniform(700, 1500)
            features[idx, 1] = rng.uniform(5.8, 8.8)
            features[idx, 2] = rng.uniform(10, 35)
            features[idx, 3] = rng.uniform(3.0, 5.5)

    # Flow and level for contamination — mostly similar to normal
    features[contam_mask, 4] = np.clip(
        np.abs(rng.normal(config.flow_mean, config.flow_std, n_contam)), 0.5, 30.0
    )
    features[contam_mask, 5] = np.clip(
        np.abs(rng.normal(config.level_mean, config.level_std, n_contam)), 2.0, 50.0
    )
    # Contamination often shows rapid parameter changes
    features[contam_mask, 6] = rng.normal(50, 30, n_contam)     # high tds_rate
    features[contam_mask, 7] = rng.normal(-0.3, 0.2, n_contam)  # negative ph_rate

    # --- Sensor fault samples ---
    fault_mask = labels == AnomalyLabel.SENSOR_FAULT
    n_fault = fault_mask.sum()

    fault_type = rng.choice(
        ["stuck", "drift", "spike", "dropout"],
        size=n_fault,
        p=[0.30, 0.25, 0.25, 0.20],
    )

    for i, ft in enumerate(fault_type):
        idx = np.where(fault_mask)[0][i]
        if ft == "stuck":
            # All readings at a constant value (sensor frozen)
            stuck_val = rng.uniform(100, 800)
            features[idx, 0] = stuck_val
            features[idx, 1] = 7.0          # suspiciously exact
            features[idx, 2] = 0.0           # zero turbidity
            features[idx, 3] = 7.0
            features[idx, 6] = 0.0           # zero rate of change
            features[idx, 7] = 0.0
        elif ft == "drift":
            # Slow drift beyond physical range
            features[idx, 0] = rng.uniform(2500, 5000)   # impossibly high TDS
            features[idx, 1] = rng.uniform(2.0, 3.5)      # impossibly low pH
            features[idx, 2] = rng.uniform(50, 200)
            features[idx, 3] = rng.uniform(15, 25)         # impossibly high DO
            features[idx, 6] = rng.uniform(100, 300)
            features[idx, 7] = rng.uniform(-1, -0.5)
        elif ft == "spike":
            # Random spikes to extreme values
            features[idx, 0] = rng.choice([0.0, 9999.0])
            features[idx, 1] = rng.choice([0.0, 14.0])
            features[idx, 2] = rng.choice([0.0, 999.0])
            features[idx, 3] = rng.choice([0.0, 50.0])
            features[idx, 6] = rng.uniform(-500, 500)
            features[idx, 7] = rng.uniform(-2, 2)
        else:  # dropout
            # Readings drop to zero / NaN-like values
            features[idx, 0] = 0.0
            features[idx, 1] = 0.0
            features[idx, 2] = 0.0
            features[idx, 3] = 0.0
            features[idx, 6] = rng.uniform(-100, 100)
            features[idx, 7] = rng.uniform(-0.5, 0.5)

    # Flow and level for faults — random / erratic
    features[fault_mask, 4] = np.clip(
        rng.uniform(-5, 50, n_fault), 0.0, 50.0
    )
    features[fault_mask, 5] = np.clip(
        rng.uniform(-10, 80, n_fault), 0.0, 80.0
    )

    logger.info(
        "Generated %d water quality samples: %d normal, %d contamination, %d sensor_fault",
        n, n_normal, n_contamination, n_sensor_fault,
    )

    return features, labels


# ---------------------------------------------------------------------------
# Groundwater Level Time-Series Generator
# ---------------------------------------------------------------------------

@dataclass
class GroundwaterConfig:
    """Configuration for groundwater time-series generation."""
    n_sequences: int = 5_000
    lookback_days: int = 90
    forecast_days: int = 30
    seed: Optional[int] = 42
    # Indian groundwater statistics (India-WRIS, CGWB)
    base_level_range: tuple[float, float] = (5.0, 35.0)    # meters below ground
    annual_decline_rate: float = 0.3                         # m/year average
    monsoon_recharge_m: float = 3.0                          # meters recharge
    extraction_rate_range: tuple[float, float] = (0.5, 5.0)  # m3/day


def generate_groundwater_data(
    config: Optional[GroundwaterConfig] = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Generate realistic groundwater level time-series for depletion prediction.

    Creates sequences of daily observations with seasonal monsoon patterns,
    extraction effects, and long-term depletion trends typical of Indian
    groundwater systems.

    Input features per timestep (7):
        0: water_level (m)          — Depth to water table below ground level
        1: rainfall (mm)            — Daily rainfall
        2: extraction_rate (m3/day) — Pumping rate
        3: temperature (C)          — Daily mean temperature
        4: humidity (%)             — Relative humidity
        5: day_sin                  — sin(2*pi*day/365) seasonal encoding
        6: day_cos                  — cos(2*pi*day/365) seasonal encoding

    Target: Next 30 days of water_level (forecast_days,)

    Args:
        config: Generation configuration. Uses defaults if None.

    Returns:
        Tuple of (inputs, targets) with shapes:
            inputs:  (n_sequences, lookback_days, 7)
            targets: (n_sequences, forecast_days)
    """
    if config is None:
        config = GroundwaterConfig()

    rng = np.random.default_rng(config.seed)
    total_days = config.lookback_days + config.forecast_days
    n = config.n_sequences

    inputs = np.zeros((n, config.lookback_days, 7), dtype=np.float32)
    targets = np.zeros((n, config.forecast_days), dtype=np.float32)

    for seq_idx in range(n):
        # --- Generate a full time series for one location ---

        # Random starting conditions
        base_level = rng.uniform(*config.base_level_range)
        annual_decline = rng.uniform(0.05, 0.8)  # m/year depletion
        extraction = rng.uniform(*config.extraction_rate_range)

        # Random start day-of-year (1-365) for seasonal phase
        start_doy = rng.integers(1, 366)

        # Generate daily rainfall with monsoon pattern (June-September peak)
        # Indian monsoon: ~80% of annual rainfall in 4 months (JJAS)
        doys = (np.arange(total_days) + start_doy) % 365

        # Monsoon probability: peaked around day 180-270 (July-Sept)
        monsoon_prob = np.exp(-0.5 * ((doys - 210) / 40) ** 2) * 0.7 + 0.05
        rain_occurs = rng.random(total_days) < monsoon_prob
        # Rainfall amount when it rains (gamma distribution — realistic)
        rain_amount = rng.gamma(shape=2.0, scale=12.0, size=total_days)
        rainfall = np.where(rain_occurs, rain_amount, 0.0)

        # Temperature: seasonal pattern for Indo-Gangetic plain
        # Summer peak ~42C (May), winter trough ~12C (January)
        temp_base = 27.0 + 12.0 * np.sin(2 * np.pi * (doys - 120) / 365)
        temperature = temp_base + rng.normal(0, 2.5, total_days)
        temperature = np.clip(temperature, 5, 48)

        # Humidity: correlated with monsoon
        humidity_base = 45 + 35 * np.exp(-0.5 * ((doys - 220) / 50) ** 2)
        humidity = humidity_base + rng.normal(0, 8, total_days)
        humidity = np.clip(humidity, 15, 98)

        # --- Simulate water level dynamics ---
        levels = np.zeros(total_days)
        levels[0] = base_level

        for d in range(1, total_days):
            # Extraction effect: increases depth (level goes up = deeper)
            extraction_effect = extraction * 0.002 * (1 + 0.3 * rng.random())

            # Recharge from rainfall (lagged 3-7 days for percolation)
            recharge = 0.0
            if d >= 5:
                # Only a fraction of rain reaches groundwater
                recharge_rain = np.mean(rainfall[max(0, d - 7):d]) * 0.08
                recharge = recharge_rain * 0.001  # convert to meters equivalent

            # Seasonal evapotranspiration loss (higher in summer)
            et_factor = 0.001 * (1 + 0.5 * np.sin(2 * np.pi * (doys[d] - 120) / 365))

            # Long-term depletion trend
            trend_decline = annual_decline / 365.0

            # Net change
            delta = extraction_effect - recharge + et_factor + trend_decline
            delta += rng.normal(0, 0.02)  # daily noise

            levels[d] = levels[d - 1] + delta
            levels[d] = np.clip(levels[d], 1.0, 60.0)

        # Extraction rate with some daily variation
        extraction_series = extraction * (1 + 0.2 * rng.normal(0, 1, total_days))
        extraction_series = np.clip(extraction_series, 0, 10)

        # Temporal encodings
        day_sin = np.sin(2 * np.pi * doys / 365.0)
        day_cos = np.cos(2 * np.pi * doys / 365.0)

        # Assemble input sequences (7 features, no trend)
        lb = config.lookback_days
        inputs[seq_idx, :, 0] = levels[:lb]
        inputs[seq_idx, :, 1] = rainfall[:lb]
        inputs[seq_idx, :, 2] = extraction_series[:lb]
        inputs[seq_idx, :, 3] = temperature[:lb]
        inputs[seq_idx, :, 4] = humidity[:lb]
        inputs[seq_idx, :, 5] = day_sin[:lb]
        inputs[seq_idx, :, 6] = day_cos[:lb]

        # Target: water levels for next 30 days
        targets[seq_idx] = levels[lb:lb + config.forecast_days]

    logger.info(
        "Generated %d groundwater sequences: %d lookback, %d forecast days",
        n, config.lookback_days, config.forecast_days,
    )

    return inputs, targets


# ---------------------------------------------------------------------------
# Irrigation Training Data Generator
# ---------------------------------------------------------------------------

@dataclass
class IrrigationConfig:
    """Configuration for irrigation training data generation."""
    n_samples: int = 30_000
    seed: Optional[int] = 42


def generate_irrigation_data(
    config: Optional[IrrigationConfig] = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Generate realistic irrigation scheduling training data.

    Models crop-specific water requirements, soil properties, weather conditions,
    and optimal irrigation decisions based on FAO-56 Penman-Monteith methodology
    adapted for Indian conditions.

    Input features (15):
        0:  soil_moisture (0-1)           — Volumetric water content fraction
        1:  crop_type (0-7)               — Encoded crop ID
        2:  growth_stage (0-3)            — Current crop growth stage
        3:  temperature (C)               — Air temperature
        4:  humidity (%)                  — Relative humidity
        5:  rainfall_forecast (mm)        — 7-day cumulative forecast
        6:  wind_speed (m/s)              — Wind speed at 2m height
        7:  solar_radiation (MJ/m2/day)   — Daily solar radiation
        8:  water_level (m)               — Groundwater depth
        9:  water_quality_score (0-1)     — Composite quality index
        10: previous_irrigation (L)       — Last irrigation amount
        11: field_area (hectares)         — Field area
        12: soil_type (0-5)               — Encoded soil type
        13: evapotranspiration (mm/day)   — Reference ET0
        14: days_since_last_rain          — Days since last rainfall

    Output targets (4):
        0: irrigation_amount_liters       — Optimal irrigation volume
        1: duration_minutes               — Irrigation duration
        2: efficiency_score (0-1)         — Water use efficiency
        3: next_irrigation_hours          — Hours until next irrigation needed

    Args:
        config: Generation configuration. Uses defaults if None.

    Returns:
        Tuple of (features, targets) with shapes (n_samples, 15) and (n_samples, 4).
    """
    if config is None:
        config = IrrigationConfig()

    rng = np.random.default_rng(config.seed)
    n = config.n_samples

    features = np.zeros((n, 15), dtype=np.float32)
    targets = np.zeros((n, 4), dtype=np.float32)

    crop_names = list(CROP_DATABASE.keys())
    soil_names = list(SOIL_TYPES.keys())

    for i in range(n):
        # Select random crop and soil
        crop_key = rng.choice(crop_names)
        crop = CROP_DATABASE[crop_key]
        soil_key = rng.choice(soil_names)
        soil = SOIL_TYPES[soil_key]

        # Growth stage
        stage = int(rng.integers(0, crop.stages))
        kc = crop.kc_values[stage]

        # Soil moisture: beta distribution skewed by recent conditions
        fc = soil["fc"]
        wp = soil["wp"]
        # Moisture typically ranges from wilting point to field capacity
        soil_moisture = rng.beta(2.5, 3.0) * (fc - wp) + wp

        # Weather conditions (seasonal variation)
        month = rng.integers(1, 13)
        # Temperature: Indo-Gangetic plain monthly averages
        temp_monthly = {
            1: 14, 2: 17, 3: 23, 4: 30, 5: 35, 6: 34,
            7: 31, 8: 30, 9: 30, 10: 27, 11: 21, 12: 15,
        }
        temperature = temp_monthly[int(month)] + rng.normal(0, 3)
        temperature = np.clip(temperature, 5, 48)

        humidity = rng.uniform(25, 95)
        wind_speed = np.clip(rng.lognormal(0.8, 0.5), 0.5, 12.0)

        # Solar radiation: higher in summer (15-25 MJ/m2/day in India)
        sr_monthly = {
            1: 14, 2: 17, 3: 20, 4: 23, 5: 25, 6: 20,
            7: 16, 8: 16, 9: 18, 10: 19, 11: 16, 12: 13,
        }
        solar_radiation = sr_monthly[int(month)] + rng.normal(0, 2)
        solar_radiation = np.clip(solar_radiation, 5, 30)

        # Reference evapotranspiration (simplified Penman-Monteith)
        # ET0 = 0.0023 * (T + 17.8) * (Tmax - Tmin)^0.5 * Ra
        # Simplified for synthetic data:
        et0 = 0.0023 * (temperature + 17.8) * np.sqrt(max(temperature * 0.3, 1)) * solar_radiation * 0.1
        et0 = np.clip(et0, 1.0, 12.0)
        etc = et0 * kc  # crop ET

        # Rainfall forecast (7-day cumulative)
        if month in [6, 7, 8, 9]:  # monsoon
            rainfall_forecast = rng.exponential(30)
        elif month in [10, 11, 12, 1, 2]:  # dry season
            rainfall_forecast = rng.exponential(3) if rng.random() < 0.2 else 0.0
        else:  # transition
            rainfall_forecast = rng.exponential(10) if rng.random() < 0.3 else 0.0

        days_since_rain = int(rng.exponential(5)) if rainfall_forecast < 5 else 0

        # Water availability
        water_level = rng.uniform(2, 40)
        water_quality = np.clip(rng.beta(5, 2), 0.3, 1.0)

        # Field characteristics
        field_area = np.clip(rng.lognormal(np.log(0.5), 0.8), 0.1, 10.0)  # hectares

        # Previous irrigation
        previous_irrigation = rng.uniform(0, field_area * 5000)

        # --- Compute optimal irrigation targets ---

        # Soil moisture deficit
        deficit_fraction = max(0, fc - soil_moisture) / (fc - wp)

        # Crop water need (L/ha/day)
        crop_need_mm = etc  # mm/day
        crop_need_liters = crop_need_mm * field_area * 10_000 / 1000  # mm * m2 / 1000 = m3 -> liters

        # Adjust for rainfall forecast (reduce irrigation)
        effective_rain = min(rainfall_forecast * 0.7, crop_need_mm * 7)  # 70% efficiency
        net_need_mm = max(0, crop_need_mm * 7 - effective_rain) / 7

        # Irrigation amount (liters)
        irrigation_amount = net_need_mm * field_area * 10  # mm * ha * 10 = liters
        irrigation_amount = max(0, irrigation_amount * deficit_fraction * 1.1)

        # If soil is wet enough or heavy rain coming, no irrigation needed
        if soil_moisture > fc * 0.85 or rainfall_forecast > crop_need_mm * 5:
            irrigation_amount = 0.0

        # Duration based on drip/sprinkler application rate
        application_rate = soil["infiltration_mm_hr"] * field_area * 10  # L/hr
        duration_minutes = (irrigation_amount / max(application_rate, 1)) * 60
        duration_minutes = np.clip(duration_minutes, 0, 480)  # max 8 hours

        # Efficiency: drip > sprinkler > flood
        # Model assumes smart scheduling = high baseline efficiency
        efficiency = np.clip(
            0.85 - 0.1 * (soil_moisture / fc) + 0.05 * water_quality,
            0.5, 0.98,
        )

        # Next irrigation timing (hours)
        # Based on ET rate and soil storage
        available_water_mm = (soil_moisture - wp) * crop.root_depth_m * 1000
        if etc > 0:
            days_until_dry = available_water_mm / etc
        else:
            days_until_dry = 14.0
        next_irrigation_hours = np.clip(days_until_dry * 24, 4, 336)  # 4h to 14 days

        # Assemble features
        features[i] = [
            soil_moisture,
            float(crop.crop_id),
            float(stage),
            temperature,
            humidity,
            rainfall_forecast,
            wind_speed,
            solar_radiation,
            water_level,
            water_quality,
            previous_irrigation,
            field_area,
            float(soil["soil_id"]),
            et0,
            float(days_since_rain),
        ]

        targets[i] = [
            irrigation_amount,
            duration_minutes,
            efficiency,
            next_irrigation_hours,
        ]

    logger.info("Generated %d irrigation training samples", n)

    return features, targets


# ---------------------------------------------------------------------------
# Normalization Statistics
# ---------------------------------------------------------------------------

@dataclass
class NormalizationStats:
    """Feature-wise normalization statistics computed from training data."""
    mean: np.ndarray
    std: np.ndarray

    def normalize(self, data: np.ndarray) -> np.ndarray:
        """Apply z-score normalization."""
        std_safe = np.where(self.std < 1e-7, 1.0, self.std)
        return (data - self.mean) / std_safe

    def denormalize(self, data: np.ndarray) -> np.ndarray:
        """Reverse z-score normalization."""
        return data * self.std + self.mean

    def save(self, path: str) -> None:
        """Save stats to .npz file."""
        np.savez(path, mean=self.mean, std=self.std)

    @classmethod
    def load(cls, path: str) -> "NormalizationStats":
        """Load stats from .npz file."""
        data = np.load(path)
        return cls(mean=data["mean"], std=data["std"])


def compute_normalization_stats(data: np.ndarray) -> NormalizationStats:
    """Compute per-feature mean and standard deviation.

    Args:
        data: Array of shape (n_samples, n_features) or (n_samples, seq_len, n_features).

    Returns:
        NormalizationStats with computed mean and std.
    """
    if data.ndim == 3:
        # Flatten sequence dimension for stats
        flat = data.reshape(-1, data.shape[-1])
    else:
        flat = data
    return NormalizationStats(
        mean=flat.mean(axis=0).astype(np.float32),
        std=flat.std(axis=0).astype(np.float32),
    )


# ---------------------------------------------------------------------------
# Convenience: generate all datasets at once
# ---------------------------------------------------------------------------

def generate_all_datasets(
    wq_config: Optional[WaterQualityConfig] = None,
    gw_config: Optional[GroundwaterConfig] = None,
    irr_config: Optional[IrrigationConfig] = None,
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Generate all three training datasets.

    Returns:
        Dictionary with keys 'anomaly', 'depletion', 'irrigation', each mapping
        to a (features, targets) tuple.
    """
    logger.info("Generating all JalNetra training datasets...")
    return {
        "anomaly": generate_water_quality_data(wq_config),
        "depletion": generate_groundwater_data(gw_config),
        "irrigation": generate_irrigation_data(irr_config),
    }
