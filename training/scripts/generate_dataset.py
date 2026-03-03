#!/usr/bin/env python3
"""Generate realistic water quality datasets based on Indian conditions.

Uses statistical distributions derived from CPCB monitoring station data,
India-WRIS groundwater observations, and IMD meteorological records.
Generates training data for all three JalNetra ML models.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

RNG = np.random.default_rng(42)

# --- Distribution Parameters (derived from CPCB 2020-2024 reports) ---

WATER_SOURCE_PROFILES = {
    "borewell_clean": {
        "tds": {"mean": 350, "std": 120, "min": 50, "max": 900},
        "ph": {"mean": 7.2, "std": 0.4, "min": 6.2, "max": 8.8},
        "turbidity": {"mean": 1.5, "std": 1.0, "min": 0.1, "max": 8},
        "do": {"mean": 6.5, "std": 1.0, "min": 3.0, "max": 9.0},
        "flow_rate": {"mean": 5.0, "std": 2.0, "min": 0.5, "max": 15},
        "water_level_m": {"mean": 12, "std": 4, "min": 3, "max": 35},
    },
    "borewell_contaminated": {
        "tds": {"mean": 1200, "std": 400, "min": 600, "max": 3500},
        "ph": {"mean": 5.8, "std": 0.8, "min": 4.5, "max": 9.8},
        "turbidity": {"mean": 15, "std": 10, "min": 2, "max": 80},
        "do": {"mean": 3.5, "std": 1.5, "min": 0.5, "max": 6.0},
        "flow_rate": {"mean": 3.0, "std": 1.5, "min": 0.2, "max": 10},
        "water_level_m": {"mean": 20, "std": 8, "min": 5, "max": 45},
    },
    "handpump_clean": {
        "tds": {"mean": 280, "std": 90, "min": 30, "max": 600},
        "ph": {"mean": 7.4, "std": 0.3, "min": 6.5, "max": 8.5},
        "turbidity": {"mean": 0.8, "std": 0.5, "min": 0.1, "max": 4},
        "do": {"mean": 7.0, "std": 0.8, "min": 4.0, "max": 9.5},
        "flow_rate": {"mean": 8.0, "std": 3.0, "min": 1.0, "max": 20},
        "water_level_m": {"mean": 8, "std": 3, "min": 2, "max": 20},
    },
    "canal": {
        "tds": {"mean": 450, "std": 200, "min": 100, "max": 1500},
        "ph": {"mean": 7.6, "std": 0.6, "min": 6.0, "max": 9.2},
        "turbidity": {"mean": 8, "std": 6, "min": 0.5, "max": 50},
        "do": {"mean": 5.5, "std": 1.5, "min": 1.5, "max": 8.5},
        "flow_rate": {"mean": 15, "std": 8, "min": 0.0, "max": 30},
        "water_level_m": {"mean": 2, "std": 1, "min": 0.3, "max": 5},
    },
    "reservoir": {
        "tds": {"mean": 200, "std": 80, "min": 50, "max": 500},
        "ph": {"mean": 7.3, "std": 0.3, "min": 6.5, "max": 8.3},
        "turbidity": {"mean": 3, "std": 2, "min": 0.2, "max": 15},
        "do": {"mean": 7.5, "std": 1.0, "min": 4.0, "max": 10.0},
        "flow_rate": {"mean": 0, "std": 0, "min": 0, "max": 0},
        "water_level_m": {"mean": 5, "std": 2, "min": 1, "max": 15},
    },
}

# Seasonal modulation (Indian climate: monsoon Jun-Sep, winter Nov-Feb, summer Mar-May)
SEASONAL_FACTORS = {
    "monsoon": {"tds": 0.7, "turbidity": 2.5, "flow_rate": 1.8, "water_level_m": 0.6},
    "winter": {"tds": 1.1, "turbidity": 0.7, "flow_rate": 0.8, "water_level_m": 1.1},
    "summer": {"tds": 1.3, "turbidity": 0.9, "flow_rate": 0.5, "water_level_m": 1.4},
    "pre_monsoon": {"tds": 1.2, "turbidity": 1.0, "flow_rate": 0.6, "water_level_m": 1.3},
}

CROP_TYPES = [
    {"name": "rice_kharif", "water_need_mm": 1200, "season": "monsoon", "growth_days": 120},
    {"name": "wheat_rabi", "water_need_mm": 450, "season": "winter", "growth_days": 135},
    {"name": "cotton", "water_need_mm": 700, "season": "monsoon", "growth_days": 165},
    {"name": "sugarcane", "water_need_mm": 1500, "season": "all", "growth_days": 330},
    {"name": "mustard", "water_need_mm": 250, "season": "winter", "growth_days": 110},
    {"name": "maize_kharif", "water_need_mm": 500, "season": "monsoon", "growth_days": 95},
    {"name": "groundnut", "water_need_mm": 450, "season": "monsoon", "growth_days": 110},
    {"name": "soybean", "water_need_mm": 400, "season": "monsoon", "growth_days": 95},
]

SOIL_TYPES = ["sandy", "loamy", "clay", "silty", "sandy_loam", "clay_loam"]


def get_season(month: int) -> str:
    if month in (6, 7, 8, 9):
        return "monsoon"
    elif month in (11, 12, 1, 2):
        return "winter"
    elif month in (3, 4, 5):
        return "summer"
    return "pre_monsoon"


def generate_sensor_timeseries(
    n_days: int = 365,
    readings_per_day: int = 48,
    source_type: str = "borewell_clean",
    inject_anomalies: bool = True,
    anomaly_rate: float = 0.03,
    sensor_fault_rate: float = 0.01,
) -> pd.DataFrame:
    """Generate a realistic time series of sensor readings."""
    profile = WATER_SOURCE_PROFILES[source_type]
    n_total = n_days * readings_per_day
    start = datetime(2024, 1, 1)
    timestamps = [start + timedelta(minutes=30 * i) for i in range(n_total)]

    records = []
    prev_values = {k: profile[k]["mean"] for k in profile}

    for i, ts in enumerate(timestamps):
        season = get_season(ts.month)
        s_factors = SEASONAL_FACTORS.get(season, {})

        # Diurnal variation
        hour_factor = 1.0 + 0.05 * np.sin(2 * np.pi * ts.hour / 24)

        row = {"timestamp": ts, "source_type": source_type}

        label = 0  # 0=normal, 1=contamination, 2=sensor_fault
        is_anomaly = inject_anomalies and RNG.random() < anomaly_rate
        is_fault = inject_anomalies and RNG.random() < sensor_fault_rate

        for param, dist in profile.items():
            base = dist["mean"]
            # Apply seasonal factor
            sf = s_factors.get(param, 1.0)
            seasonal_val = base * sf * hour_factor

            # AR(1) process for temporal correlation
            alpha = 0.85  # autocorrelation
            noise = RNG.normal(0, dist["std"] * 0.3)
            value = alpha * prev_values[param] + (1 - alpha) * seasonal_val + noise

            if is_anomaly and param in ("tds", "ph", "turbidity", "do"):
                if param == "tds":
                    value = RNG.uniform(1500, 3500)
                elif param == "ph":
                    value = RNG.choice([RNG.uniform(4.0, 5.5), RNG.uniform(9.5, 11.0)])
                elif param == "turbidity":
                    value = RNG.uniform(30, 200)
                elif param == "do":
                    value = RNG.uniform(0.5, 2.0)
                label = 1

            if is_fault:
                fault_type = RNG.choice(["stuck", "spike", "dropout"])
                if fault_type == "stuck":
                    value = prev_values[param]  # Frozen value
                elif fault_type == "spike":
                    value = dist["max"] * RNG.uniform(1.5, 3.0)
                else:
                    value = 0.0
                label = 2

            value = np.clip(value, dist["min"], dist["max"] * (3.0 if is_fault else 1.2))
            row[param] = round(float(value), 2)
            prev_values[param] = value

        # Derived features
        row["tds_rate"] = 0.0 if i == 0 else round(row["tds"] - records[-1]["tds"], 2)
        row["ph_rate"] = 0.0 if i == 0 else round(row["ph"] - records[-1]["ph"], 4)
        row["hour_sin"] = round(float(np.sin(2 * np.pi * ts.hour / 24)), 4)
        row["hour_cos"] = round(float(np.cos(2 * np.pi * ts.hour / 24)), 4)
        row["label"] = label
        records.append(row)

    return pd.DataFrame(records)


def generate_groundwater_series(
    n_days: int = 365 * 3,
    n_wells: int = 20,
) -> pd.DataFrame:
    """Generate realistic groundwater level time series for depletion prediction."""
    records = []
    start = datetime(2022, 1, 1)

    for well_id in range(n_wells):
        base_depth = RNG.uniform(5, 30)  # meters below ground
        annual_depletion = RNG.uniform(0.2, 1.5)  # meters/year decline
        monsoon_recharge = RNG.uniform(1.0, 4.0)  # meters recovery

        for day in range(n_days):
            ts = start + timedelta(days=day)
            season = get_season(ts.month)

            # Long-term depletion trend
            trend = annual_depletion * (day / 365.0)

            # Seasonal recharge (monsoon brings water table up)
            if season == "monsoon":
                seasonal = -monsoon_recharge * np.sin(np.pi * (ts.month - 6) / 4)
            elif season == "summer":
                seasonal = annual_depletion * 0.4
            else:
                seasonal = annual_depletion * 0.1

            # Random noise
            noise = RNG.normal(0, 0.15)

            # Rainfall (mm/day) — based on IMD district averages
            if season == "monsoon":
                rainfall = max(0, RNG.exponential(12.0))
            elif season == "winter":
                rainfall = max(0, RNG.exponential(1.5))
            else:
                rainfall = max(0, RNG.exponential(0.5))

            # Extraction rate (liters/day) — higher in summer
            base_extraction = RNG.uniform(500, 5000)
            if season == "summer":
                extraction = base_extraction * 1.5
            elif season == "monsoon":
                extraction = base_extraction * 0.6
            else:
                extraction = base_extraction

            depth = base_depth + trend + seasonal + noise
            depth = max(1.0, depth)

            records.append({
                "date": ts.date(),
                "well_id": f"W{well_id:03d}",
                "water_level_m": round(float(depth), 2),
                "rainfall_mm": round(float(rainfall), 1),
                "extraction_liters": round(float(extraction), 0),
                "temperature_c": round(float(25 + 10 * np.sin(2 * np.pi * (ts.timetuple().tm_yday - 120) / 365) + RNG.normal(0, 2)), 1),
                "humidity_pct": round(float(np.clip(60 + 25 * np.sin(2 * np.pi * (ts.timetuple().tm_yday - 180) / 365) + RNG.normal(0, 8), 20, 98)), 1),
            })

    return pd.DataFrame(records)


def generate_irrigation_dataset(n_samples: int = 50000) -> pd.DataFrame:
    """Generate training data for irrigation optimization model."""
    records = []

    for _ in range(n_samples):
        crop = RNG.choice(CROP_TYPES)
        soil = RNG.choice(SOIL_TYPES)
        growth_stage = RNG.uniform(0, 1)  # 0=sowing, 1=harvest

        # Environmental conditions
        temperature = round(float(RNG.normal(28, 6)), 1)
        humidity = round(float(np.clip(RNG.normal(55, 20), 15, 98)), 1)
        rainfall_forecast_mm = round(float(max(0, RNG.exponential(5))), 1)
        wind_speed_kmh = round(float(max(0, RNG.normal(8, 4))), 1)
        solar_radiation = round(float(np.clip(RNG.normal(5.5, 1.5), 1, 9)), 2)

        # Soil & water conditions
        soil_moisture_pct = round(float(np.clip(RNG.normal(35, 15), 5, 80)), 1)
        water_level_m = round(float(max(1, RNG.normal(12, 6))), 1)
        water_quality_score = round(float(np.clip(RNG.normal(75, 15), 10, 100)), 1)

        # Previous irrigation
        previous_irrigation_liters = round(float(max(0, RNG.normal(200, 100))), 0)
        field_area_hectares = round(float(max(0.1, RNG.lognormal(0, 0.8))), 2)

        # Evapotranspiration (Penman-Monteith simplified)
        et0 = 0.0023 * (temperature + 17.8) * ((temperature - RNG.normal(12, 3)) ** 0.5) * solar_radiation
        et0 = round(float(max(1, et0)), 2)

        days_since_rain = int(max(0, RNG.exponential(5)))

        # Target: optimal irrigation
        # Crop coefficient based on growth stage
        kc = 0.3 + 0.7 * np.sin(np.pi * growth_stage)
        crop_et = et0 * kc

        # Soil water holding capacity factor
        soil_factors = {"sandy": 0.6, "loamy": 1.0, "clay": 1.3, "silty": 1.1, "sandy_loam": 0.8, "clay_loam": 1.2}
        soil_f = soil_factors.get(soil, 1.0)

        # Optimal irrigation amount
        deficit = max(0, (crop_et * soil_f - rainfall_forecast_mm) * field_area_hectares * 10)
        moisture_factor = max(0, (50 - soil_moisture_pct) / 50)
        optimal_liters = deficit * moisture_factor * 1000
        optimal_liters = round(float(max(0, optimal_liters + RNG.normal(0, 20))), 0)

        # Duration based on flow rate
        duration_min = round(float(max(0, optimal_liters / max(1, RNG.normal(8, 2) * 60))), 0)

        # Efficiency score (how much better than flood irrigation)
        flood_liters = crop["water_need_mm"] * field_area_hectares * 10 / crop["growth_days"] * 1000
        efficiency = round(float(np.clip(1 - optimal_liters / max(1, flood_liters), 0, 0.6) * 100), 1)

        # Next irrigation (hours)
        next_irrigation_h = round(float(max(4, min(168, 24 * crop_et / max(0.1, soil_moisture_pct / 100 * soil_f)))), 1)

        records.append({
            "soil_moisture_pct": soil_moisture_pct,
            "crop_type": crop["name"],
            "growth_stage": round(float(growth_stage), 3),
            "temperature_c": temperature,
            "humidity_pct": humidity,
            "rainfall_forecast_mm": rainfall_forecast_mm,
            "wind_speed_kmh": wind_speed_kmh,
            "solar_radiation_kwh": solar_radiation,
            "water_level_m": water_level_m,
            "water_quality_score": water_quality_score,
            "previous_irrigation_liters": previous_irrigation_liters,
            "field_area_hectares": field_area_hectares,
            "soil_type": soil,
            "evapotranspiration_mm": et0,
            "days_since_rain": days_since_rain,
            # Targets
            "irrigation_amount_liters": optimal_liters,
            "duration_minutes": duration_min,
            "efficiency_score": efficiency,
            "next_irrigation_hours": next_irrigation_h,
        })

    return pd.DataFrame(records)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate JalNetra training datasets")
    parser.add_argument("--output-dir", type=Path, default=Path("training/data"))
    parser.add_argument("--anomaly-days", type=int, default=365)
    parser.add_argument("--groundwater-days", type=int, default=1095)
    parser.add_argument("--irrigation-samples", type=int, default=50000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    global RNG
    RNG = np.random.default_rng(args.seed)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("JalNetra Dataset Generator")
    print("=" * 60)

    # 1. Anomaly detection dataset
    print("\n[1/3] Generating water quality anomaly dataset...")
    dfs = []
    for source_type in WATER_SOURCE_PROFILES:
        print(f"  - {source_type}: {args.anomaly_days} days, 48 readings/day")
        df = generate_sensor_timeseries(
            n_days=args.anomaly_days,
            readings_per_day=48,
            source_type=source_type,
        )
        dfs.append(df)

    anomaly_df = pd.concat(dfs, ignore_index=True)
    anomaly_path = args.output_dir / "anomaly_detection_train.parquet"
    anomaly_df.to_parquet(anomaly_path, index=False, engine="pyarrow")
    label_counts = anomaly_df["label"].value_counts().to_dict()
    print(f"  Total: {len(anomaly_df):,} readings")
    print(f"  Labels: normal={label_counts.get(0, 0):,}, contamination={label_counts.get(1, 0):,}, sensor_fault={label_counts.get(2, 0):,}")
    print(f"  Saved: {anomaly_path}")

    # 2. Groundwater depletion dataset
    print("\n[2/3] Generating groundwater level dataset...")
    gw_df = generate_groundwater_series(n_days=args.groundwater_days, n_wells=20)
    gw_path = args.output_dir / "groundwater_levels_train.parquet"
    gw_df.to_parquet(gw_path, index=False, engine="pyarrow")
    print(f"  Total: {len(gw_df):,} daily records across 20 wells")
    print(f"  Date range: {gw_df['date'].min()} to {gw_df['date'].max()}")
    print(f"  Saved: {gw_path}")

    # 3. Irrigation optimization dataset
    print("\n[3/3] Generating irrigation optimization dataset...")
    irr_df = generate_irrigation_dataset(n_samples=args.irrigation_samples)
    irr_path = args.output_dir / "irrigation_optimization_train.parquet"
    irr_df.to_parquet(irr_path, index=False, engine="pyarrow")
    print(f"  Total: {len(irr_df):,} samples")
    print(f"  Crop types: {irr_df['crop_type'].nunique()}")
    print(f"  Saved: {irr_path}")

    # Summary
    print("\n" + "=" * 60)
    print("Dataset Generation Complete")
    print(f"  Anomaly detection: {len(anomaly_df):>10,} readings")
    print(f"  Groundwater levels: {len(gw_df):>10,} records")
    print(f"  Irrigation optimization: {len(irr_df):>10,} samples")
    print(f"  Output directory: {args.output_dir.resolve()}")
    print("=" * 60)


if __name__ == "__main__":
    main()
