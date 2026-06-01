"""
集成测试
运行：pytest tests/ -v
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
import os

os.environ["DATABASE_URL"] = "sqlite:///./test_mask.db"
os.environ["INTERNAL_API_KEY"] = "test-internal-key"
os.environ["GATEWAY_API_KEY"] = "test-gateway-key"
os.environ["GATEWAY_ALLOWED_IPS"] = ""
os.environ["DEBUG"] = "true"

from app.main import app
from app.database import startup, shutdown


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    await startup()
    yield
    await shutdown()
    import os
    try:
        os.remove("./test_mask.db")
    except FileNotFoundError:
        pass


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as c:
        yield c


# ── 健康检查 ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ── /mask ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mask_success(client):
    r = await client.post(
        "/mask",
        json={"phone": "13800138001"},
        headers={"X-Internal-Key": "test-internal-key"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["token"].startswith("tok_")
    assert len(data["token"]) == 36  # tok_ + 32hex
    assert data["expires_at"] is None  # 默认永不过期


@pytest.mark.asyncio
async def test_mask_invalid_phone(client):
    r = await client.post(
        "/mask",
        json={"phone": "12345"},
        headers={"X-Internal-Key": "test-internal-key"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_mask_idempotent(client):
    """同一手机号多次mask，返回同一Token"""
    headers = {"X-Internal-Key": "test-internal-key"}
    r1 = await client.post("/mask", json={"phone": "13800138002"}, headers=headers)
    r2 = await client.post("/mask", json={"phone": "13800138002"}, headers=headers)
    assert r1.json()["token"] == r2.json()["token"]


@pytest.mark.asyncio
async def test_mask_wrong_key(client):
    r = await client.post(
        "/mask",
        json={"phone": "13800138001"},
        headers={"X-Internal-Key": "wrong-key"},
    )
    assert r.status_code == 401


# ── /unmask ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unmask_success(client):
    # 先mask
    mask_r = await client.post(
        "/mask",
        json={"phone": "13800138003"},
        headers={"X-Internal-Key": "test-internal-key"},
    )
    token = mask_r.json()["token"]

    # 再unmask
    r = await client.get(
        f"/unmask?token={token}",
        headers={"X-Gateway-Key": "test-gateway-key"},
    )
    assert r.status_code == 200
    assert r.json()["phone"] == "13800138003"


@pytest.mark.asyncio
async def test_unmask_not_found(client):
    r = await client.get(
        "/unmask?token=tok_nonexistenttoken12345678901234",
        headers={"X-Gateway-Key": "test-gateway-key"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_unmask_wrong_key(client):
    r = await client.get(
        "/unmask?token=tok_anything",
        headers={"X-Gateway-Key": "wrong-key"},
    )
    assert r.status_code == 401


# ── DELETE /mask/:token ───────────────────────────────────

@pytest.mark.asyncio
async def test_revoke_token(client):
    headers = {"X-Internal-Key": "test-internal-key"}
    gw_headers = {"X-Gateway-Key": "test-gateway-key"}

    # 创建
    mask_r = await client.post("/mask", json={"phone": "13800138004"}, headers=headers)
    token = mask_r.json()["token"]

    # 注销
    r = await client.delete(f"/mask/{token}", headers=headers)
    assert r.status_code == 200

    # 注销后unmask应404
    r2 = await client.get(f"/unmask?token={token}", headers=gw_headers)
    assert r2.status_code == 404


@pytest.mark.asyncio
async def test_revoke_nonexistent(client):
    r = await client.delete(
        "/mask/tok_nonexistent",
        headers={"X-Internal-Key": "test-internal-key"},
    )
    assert r.status_code == 404
