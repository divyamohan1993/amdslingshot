"""Tests for ML model training, export, and inference."""

import tempfile
from pathlib import Path

import numpy as np
import pytest


class TestAnomalyDetector:
    """Anomaly detection model tests."""

    def test_model_architecture(self) -> None:
        """Verify model input/output shapes."""
        from edge.models.anomaly_detector import AnomalyDetectorCNN

        model = AnomalyDetectorCNN(input_features=10, num_classes=3)
        # Batch of 4, 10 features
        x = __import__("torch").randn(4, 10)
        out = model(x)
        assert out.shape == (4, 3)
        # Outputs should be log-probabilities or logits
        assert out.requires_grad

    def test_training_produces_valid_onnx(self, tmp_path: Path) -> None:
        """Verify ONNX export produces valid model file."""
        from edge.models.anomaly_detector import AnomalyDetectorCNN, export_to_onnx

        model = AnomalyDetectorCNN(input_features=10, num_classes=3)
        onnx_path = tmp_path / "anomaly.onnx"
        export_to_onnx(model, onnx_path, input_features=10)
        assert onnx_path.exists()
        assert onnx_path.stat().st_size > 1000  # Not empty

    def test_onnx_inference(self, tmp_path: Path) -> None:
        """Verify ONNX model produces correct output shape."""
        import onnxruntime as ort

        from edge.models.anomaly_detector import AnomalyDetectorCNN, export_to_onnx

        model = AnomalyDetectorCNN(input_features=10, num_classes=3)
        onnx_path = tmp_path / "anomaly.onnx"
        export_to_onnx(model, onnx_path, input_features=10)

        session = ort.InferenceSession(str(onnx_path))
        input_data = np.random.randn(1, 10).astype(np.float32)
        outputs = session.run(None, {"input": input_data})
        assert outputs[0].shape == (1, 3)


class TestDepletionPredictor:
    """Groundwater depletion LSTM model tests."""

    def test_model_architecture(self) -> None:
        from edge.models.depletion_predictor import DepletionLSTM

        model = DepletionLSTM(input_features=7, hidden_size=64, num_layers=2, forecast_days=30)
        # Batch=2, sequence=90 days, features=7
        x = __import__("torch").randn(2, 90, 7)
        out = model(x)
        assert out.shape == (2, 30)

    def test_export_and_inference(self, tmp_path: Path) -> None:
        import onnxruntime as ort

        from edge.models.depletion_predictor import DepletionLSTM, export_to_onnx

        model = DepletionLSTM(input_features=7, hidden_size=64, num_layers=2, forecast_days=30)
        onnx_path = tmp_path / "depletion.onnx"
        export_to_onnx(model, onnx_path, input_features=7, seq_length=90)
        assert onnx_path.exists()

        session = ort.InferenceSession(str(onnx_path))
        input_data = np.random.randn(1, 90, 7).astype(np.float32)
        outputs = session.run(None, {"input": input_data})
        assert outputs[0].shape == (1, 30)


class TestIrrigationOptimizer:
    """Irrigation scheduling model tests."""

    def test_training_and_export(self, tmp_path: Path) -> None:
        from edge.models.irrigation_optimizer import train_irrigation_model

        # Small dataset for testing
        n = 500
        rng = np.random.default_rng(42)
        X = rng.random((n, 15)).astype(np.float32)
        y = rng.random((n, 4)).astype(np.float32) * 100

        onnx_path = tmp_path / "irrigation.onnx"
        train_irrigation_model(X, y, onnx_path, n_estimators=10)
        assert onnx_path.exists()

    def test_onnx_inference(self, tmp_path: Path) -> None:
        import onnxruntime as ort

        from edge.models.irrigation_optimizer import train_irrigation_model

        n = 500
        rng = np.random.default_rng(42)
        X = rng.random((n, 15)).astype(np.float32)
        y = rng.random((n, 4)).astype(np.float32) * 100

        onnx_path = tmp_path / "irrigation.onnx"
        train_irrigation_model(X, y, onnx_path, n_estimators=10)

        session = ort.InferenceSession(str(onnx_path))
        input_data = rng.random((1, 15)).astype(np.float32)
        outputs = session.run(None, {"X": input_data})
        assert outputs[0].shape[0] == 1


class TestDataGenerator:
    """Training data generation tests."""

    def test_anomaly_data_shape(self) -> None:
        from training.scripts.generate_dataset import generate_sensor_timeseries

        df = generate_sensor_timeseries(n_days=7, readings_per_day=48, source_type="borewell_clean")
        assert len(df) == 7 * 48
        assert "tds" in df.columns
        assert "ph" in df.columns
        assert "label" in df.columns
        assert set(df["label"].unique()).issubset({0, 1, 2})

    def test_groundwater_data_shape(self) -> None:
        from training.scripts.generate_dataset import generate_groundwater_series

        df = generate_groundwater_series(n_days=30, n_wells=3)
        assert len(df) == 30 * 3
        assert "water_level_m" in df.columns
        assert "rainfall_mm" in df.columns

    def test_irrigation_data_shape(self) -> None:
        from training.scripts.generate_dataset import generate_irrigation_dataset

        df = generate_irrigation_dataset(n_samples=100)
        assert len(df) == 100
        assert "irrigation_amount_liters" in df.columns
        assert "efficiency_score" in df.columns

    def test_data_distributions_realistic(self) -> None:
        """Verify generated data matches expected Indian water quality ranges."""
        from training.scripts.generate_dataset import generate_sensor_timeseries

        df = generate_sensor_timeseries(n_days=30, readings_per_day=48, source_type="borewell_clean")
        normal = df[df["label"] == 0]

        # BIS IS 10500 acceptable limits — most clean readings should be within
        assert normal["tds"].median() < 600
        assert 6.0 < normal["ph"].median() < 9.0
        assert normal["turbidity"].median() < 10
