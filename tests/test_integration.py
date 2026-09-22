import os

import httpx
import pytest
from app.core.config import get_settings
from app.services.health import check_dependencies

pytestmark = pytest.mark.skipif(
    os.environ.get("CAREFLOW_INTEGRATION") != "1",
    reason="Set CAREFLOW_INTEGRATION=1 with Compose running to test real services",
)


async def test_real_infrastructure_connections():
    result = await check_dependencies(get_settings())
    assert result.status == "ok", result.model_dump()


def test_running_api():
    response = httpx.get(
        os.environ.get("CAREFLOW_API_URL", "http://localhost:8000") + "/health", timeout=10
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert set(response.json()["dependencies"]) == {"postgresql", "qdrant", "redis"}
