from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path):
    url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    cfg = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    cfg.attributes["database_url"] = url
    command.upgrade(cfg, "head")
    return Settings(database_url=url)


@pytest.fixture
def client(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        yield client


def create_campaign(client, **overrides):
    payload = {"name": "campaign", "country": "de", "offer_id": 1, "domain_id": 1, "group_id": 1, "traffic_source_id": 1}
    return client.post("/api/campaigns", json={**payload, **overrides})


@pytest.fixture
def campaign(client):
    response = create_campaign(client)
    assert response.status_code == 201, response.text
    return response.json()
