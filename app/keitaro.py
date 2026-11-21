from copy import deepcopy

import httpx

from app.db import DemoState


class TrackerError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


class KeitaroClient:
    def __init__(self, settings, transport=None):
        self.http = httpx.Client(
            base_url=settings.keitaro_url + "/admin_api/v1/",
            headers={"Api-Key": settings.api_key, "Accept": "application/json"},
            timeout=httpx.Timeout(20, connect=5),
            follow_redirects=False,
            transport=transport,
        )

    def close(self):
        self.http.close()

    def request(self, method, path, *, json=None, params=None):
        try:
            response = self.http.request(method, path.lstrip("/"), json=json, params=params)
        except httpx.TimeoutException as exc:
            raise TrackerError("Keitaro не ответил вовремя. Перед повтором обновите кампанию: запрос мог быть применён.", 504) from exc
        except httpx.RequestError as exc:
            raise TrackerError("Не удалось связаться с Keitaro. Обновите данные перед повтором операции.") from exc
        if response.status_code >= 300:
            messages = {
                401: "Keitaro: неверный API-ключ.",
                402: "Admin API недоступен в текущей лицензии Keitaro.",
                403: "Keitaro: недостаточно прав.",
                404: "Объект не найден в Keitaro.",
                429: "Keitaro ограничил частоту запросов. Повторите позже.",
            }
            raise TrackerError(messages.get(response.status_code, f"Keitaro вернул HTTP {response.status_code}."))
        try:
            return response.json()
        except ValueError as exc:
            raise TrackerError("Keitaro вернул ответ в неожиданном формате.") from exc


class DemoClient:
    """Persistent local substitute for the API; production service logic is unchanged."""
    def __init__(self, sessions):
        self.sessions = sessions
        with sessions() as db:
            row = db.get(DemoState, 1)
            self.data = deepcopy(row.payload) if row else {
                "campaigns": [], "streams": [], "next_id": 100,
                "offers": [{"id": i, "name": name, "state": "active"} for i, name in enumerate(
                    ["Demo · Travel", "Demo · Education", "Demo · Health", "Demo · Finance", "Demo · Retail"], 1)],
            }

    def close(self):
        pass

    def _save(self):
        with self.sessions() as db:
            row = db.get(DemoState, 1)
            if row:
                row.payload = deepcopy(self.data)
            else:
                db.add(DemoState(id=1, payload=deepcopy(self.data)))
            db.commit()

    def request(self, method, path, *, json=None, params=None):
        parts = path.strip("/").split("/")
        resource = parts[0]
        if method == "GET":
            if resource in ("domains", "groups", "traffic_sources"):
                return [{"id": 1, "name": {"domains": "https://demo.example.com", "groups": "Demo group", "traffic_sources": "Demo source"}[resource], "state": "active"}]
            if resource == "offers":
                rows = self.data["offers"]
            elif resource == "campaigns" and len(parts) == 3:
                return deepcopy([s for s in self.data["streams"] if s["campaign_id"] == int(parts[1])])
            else:
                rows = self.data.get(resource, [])
            if len(parts) == 1:
                offset, limit = int((params or {}).get("offset", 0)), int((params or {}).get("limit", 10000))
                return deepcopy(rows[offset:offset + limit])
            row = next((r for r in rows if r["id"] == int(parts[1])), None)
            if not row:
                raise TrackerError("Объект не найден.", 404)
            return deepcopy(row)
        if resource == "report":
            return {"rows": [], "total": {"clicks": 0, "revenue": 0, "conversions": 0}}
        if method == "POST" and len(parts) == 1 and resource in ("campaigns", "streams"):
            self.data["next_id"] += 1
            row = {"id": self.data["next_id"], **deepcopy(json)}
            self.data[resource].append(row)
        elif method == "PUT" and resource in ("campaigns", "streams"):
            row = next((r for r in self.data[resource] if r["id"] == int(parts[1])), None)
            if not row:
                raise TrackerError("Объект не найден.", 404)
            row.update(deepcopy(json))
        else:
            raise TrackerError("Неподдерживаемая операция деморежима.")
        self._save()
        return deepcopy(row)
