import httpx
import pytest

from app.config import Settings
from app.keitaro import KeitaroClient, TrackerError


def test_client_url_auth_and_no_redirects():
    def handler(request):
        assert request.url == "https://tracker.example.com/admin_api/v1/groups?type=campaigns"
        assert request.headers["Api-Key"] == "test-key"
        return httpx.Response(200, json=[{"id": 1, "name": "Tests"}])
    client = KeitaroClient(Settings(api_key="test-key"), transport=httpx.MockTransport(handler))
    assert client.request("GET", "groups", params={"type": "campaigns"})[0]["id"] == 1
    client.close()


@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
def test_errors_do_not_leak_key_or_server_body(status):
    client = KeitaroClient(Settings(api_key="secret"), transport=httpx.MockTransport(lambda request: httpx.Response(status, text="sensitive body secret")))
    with pytest.raises(TrackerError) as error:
        client.request("POST", "campaigns", json={"name": "test"})
    assert "secret" not in str(error.value)
    assert "sensitive" not in str(error.value)
    client.close()
