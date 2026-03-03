"""Integration tests for FastAPI endpoints."""

import pytest
import pytest_asyncio
from httpx import AsyncClient


@pytest.mark.asyncio
class TestHealthEndpoint:
    """System health check tests."""

    async def test_health_returns_200(self, async_client: AsyncClient) -> None:
        response = await async_client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "uptime_seconds" in data
        assert "database" in data

    async def test_health_model_status(self, async_client: AsyncClient) -> None:
        response = await async_client.get("/api/v1/health/models")
        assert response.status_code == 200


@pytest.mark.asyncio
class TestReadingsEndpoint:
    """Sensor readings CRUD tests."""

    async def test_list_readings_empty(self, async_client: AsyncClient) -> None:
        response = await async_client.get("/api/v1/readings")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "items" in data or "readings" in data or isinstance(data, list)

    async def test_create_reading(self, async_client: AsyncClient, sample_reading: dict) -> None:
        response = await async_client.post("/api/v1/readings", json=sample_reading)
        assert response.status_code in (200, 201)
        data = response.json()
        assert "id" in data or "reading_id" in data

    async def test_get_latest_readings(self, async_client: AsyncClient) -> None:
        response = await async_client.get("/api/v1/readings/latest")
        assert response.status_code == 200


@pytest.mark.asyncio
class TestNodesEndpoint:
    """Sensor node management tests."""

    async def test_list_nodes(self, async_client: AsyncClient) -> None:
        response = await async_client.get("/api/v1/nodes")
        assert response.status_code == 200

    async def test_register_node(self, async_client: AsyncClient) -> None:
        node_data = {
            "node_id": "N099",
            "name": "Test Borewell",
            "source_type": "borewell",
            "latitude": 28.6139,
            "longitude": 77.2090,
        }
        response = await async_client.post("/api/v1/nodes", json=node_data)
        assert response.status_code in (200, 201)


@pytest.mark.asyncio
class TestAlertsEndpoint:
    """Alert system tests."""

    async def test_list_alerts(self, async_client: AsyncClient) -> None:
        response = await async_client.get("/api/v1/alerts")
        assert response.status_code == 200

    async def test_alert_stats(self, async_client: AsyncClient) -> None:
        response = await async_client.get("/api/v1/alerts/stats")
        assert response.status_code == 200


@pytest.mark.asyncio
class TestPredictionsEndpoint:
    """ML prediction tests."""

    async def test_list_predictions(self, async_client: AsyncClient) -> None:
        response = await async_client.get("/api/v1/predictions")
        assert response.status_code == 200

    async def test_irrigation_schedule(self, async_client: AsyncClient) -> None:
        response = await async_client.get("/api/v1/irrigation")
        assert response.status_code == 200


@pytest.mark.asyncio
class TestReportsEndpoint:
    """JJM compliance report tests."""

    async def test_jjm_report(self, async_client: AsyncClient) -> None:
        response = await async_client.get("/api/v1/reports/jjm")
        assert response.status_code == 200

    async def test_summary_report(self, async_client: AsyncClient) -> None:
        response = await async_client.get("/api/v1/reports/summary")
        assert response.status_code == 200
