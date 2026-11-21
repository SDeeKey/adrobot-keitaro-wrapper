from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from threading import RLock
from uuid import uuid4

from fastapi import HTTPException

from app.db import Campaign
from app.keitaro import TrackerError
from app.shares import ShareError, distribute


def fingerprint(streams):
    # Detect edits outside the wrapper without depending on volatile timestamps.
    return hashlib.sha256(json.dumps(streams, sort_keys=True).encode()).hexdigest()


class CampaignService:
    def __init__(self, settings, client, sessions):
        self.settings, self.client, self.sessions = settings, client, sessions
        self.lock = RLock()

    def _allowed(self, campaign):
        if not campaign["name"].startswith(self.settings.prefix):
            raise HTTPException(403, "Можно изменять только кампании со своим тестовым префиксом.")

    def references(self):
        return {
            key: [row for row in self.client.request("GET", endpoint, params=params) if row.get("state") != "deleted"]
            for key, endpoint, params in [
                ("domains", "domains", None), ("groups", "groups", {"type": "campaigns"}),
                ("sources", "traffic_sources", None), ("offers", "offers", None),
            ]
        }

    def list_campaigns(self):
        result, offset = [], 0
        while True:
            batch = self.client.request("GET", "campaigns", params={"offset": offset, "limit": 100})
            if not isinstance(batch, list):
                raise TrackerError("Keitaro вернул неожиданный список кампаний.")
            result.extend(c for c in batch if c["name"].startswith(self.settings.prefix) and c.get("state") != "deleted")
            if len(batch) < 100:
                return result
            offset += len(batch)
            if offset > 100_000:
                raise TrackerError("Превышен лимит страниц списка кампаний.")

    def create(self, data):
        with self.lock:
            refs = self.references()
            for key, value in [("offers", data.offer_id), ("domains", data.domain_id), ("groups", data.group_id), ("sources", data.traffic_source_id)]:
                if not any(int(row["id"]) == value and row.get("state", "active") == "active" for row in refs[key]):
                    raise HTTPException(422, f"Выбранный объект ({key}, ID {value}) недоступен.")
            name = data.name if data.name.startswith(self.settings.prefix) else self.settings.prefix + data.name
            campaign = self.client.request("POST", "campaigns", json={
                "name": name, "alias": "test-" + uuid4().hex[:16], "type": "position", "state": "disabled",
                "domain_id": data.domain_id, "group_id": str(data.group_id), "traffic_source_id": data.traffic_source_id,
            })
            campaign_id = int(campaign["id"])
            try:
                self.client.request("POST", "streams", json={
                    "campaign_id": campaign_id, "name": f"GEO {data.country} → Google", "type": "regular", "position": 1,
                    "schema": "redirect", "action_type": "http", "action_payload": "https://www.google.com/",
                    "collect_clicks": True, "state": "active", "filter_or": False,
                    "filters": [{"name": "country", "mode": "accept", "payload": [data.country]}],
                })
                self.client.request("POST", "streams", json={
                    "campaign_id": campaign_id, "name": "Offers", "type": "regular", "position": 2,
                    "schema": "landings", "action_type": "http", "collect_clicks": True, "state": "active",
                    "filters": [], "landings": [], "offers": [{"offer_id": data.offer_id, "share": 100, "state": "active"}],
                })
                self.client.request("PUT", f"campaigns/{campaign_id}", json={"state": "active"})
            except TrackerError as exc:
                raise TrackerError(f"Кампания ID {campaign_id} создана, но настройка не завершена. Проверьте её в Keitaro перед повтором. {exc}") from exc
            return self.refresh(campaign_id)

    def refresh(self, campaign_id):
        with self.lock, self.sessions() as db:
            campaign = self.client.request("GET", f"campaigns/{campaign_id}")
            self._allowed(campaign)
            streams = self.client.request("GET", f"campaigns/{campaign_id}/streams")
            catalog = {int(o["id"]): o for o in self.client.request("GET", "offers")}
            row = db.get(Campaign, campaign_id)
            previous = row.snapshot if row else {}
            previous_streams = {s["id"]: s for s in previous.get("streams", [])}
            view = []
            for stream in streams:
                old_offers = {o["offer_id"]: o for o in previous_streams.get(stream["id"], {}).get("offers", [])}
                offers = []
                for offer in stream.get("offers", []):
                    offer_id = int(offer["offer_id"])
                    old = old_offers.get(offer_id, {})
                    removed = offer.get("state", "active") != "active"
                    share = int(offer.get("share", 0)) if not removed else 0
                    offers.append({"offer_id": offer_id, "name": catalog.get(offer_id, {}).get("name", f"Offer #{offer_id}"),
                                   "share": share, "removed": removed,
                                   "pinned": old.get("pinned", False) and old.get("share") == share and not removed})
                known = {o["offer_id"] for o in offers}
                offers.extend({**o, "share": 0, "removed": True, "pinned": False} for o in old_offers.values() if o["offer_id"] not in known)
                view.append({"id": stream["id"], "name": stream.get("name", ""), "position": stream.get("position", 0),
                             "filters": stream.get("filters", []), "schema": stream.get("schema"),
                             "target": stream.get("action_payload", ""), "offers": offers})
            snapshot = {"campaign": campaign, "streams": view, "remote_hash": fingerprint(streams)}
            if row:
                row.revision += 1
                row.name, row.snapshot, row.updated_at = campaign["name"], snapshot, datetime.now(timezone.utc)
            else:
                row = Campaign(id=campaign_id, name=campaign["name"], snapshot=snapshot, revision=1)
                db.add(row)
            db.commit()
            return {"id": row.id, "name": row.name, "revision": row.revision, **snapshot}

    def change_offer(self, campaign_id, stream_id, action):
        with self.lock, self.sessions() as db:
            row = db.get(Campaign, campaign_id)
            if not row:
                raise HTTPException(409, "Сначала загрузите кампанию.")
            if row.revision != action.revision:
                raise HTTPException(409, "Данные изменились. Обновите кампанию и повторите действие.")
            campaign = self.client.request("GET", f"campaigns/{campaign_id}")
            self._allowed(campaign)
            remote = self.client.request("GET", f"campaigns/{campaign_id}/streams")
            if fingerprint(remote) != row.snapshot["remote_hash"]:
                raise HTTPException(409, "Кампания изменена в Keitaro. Сначала обновите данные.")
            snapshot = deepcopy(row.snapshot)
            stream = next((s for s in snapshot["streams"] if s["id"] == stream_id), None)
            if not stream or stream["schema"] != "landings":
                raise HTTPException(422, "Этот поток не поддерживает редактирование офферов.")
            offers = stream["offers"]
            offer = next((o for o in offers if o["offer_id"] == action.offer_id), None)
            if action.action == "add":
                if offer:
                    raise HTTPException(409, "Оффер уже есть в потоке; удалённый можно восстановить.")
                available = self.client.request("GET", "offers")
                item = next((o for o in available if int(o["id"]) == action.offer_id and o.get("state", "active") == "active"), None)
                if not item:
                    raise HTTPException(422, "Оффер недоступен.")
                offer = {"offer_id": action.offer_id, "name": item["name"], "share": 0, "pinned": False, "removed": False}
                offers.append(offer)
            elif not offer:
                raise HTTPException(404, "Оффера нет в потоке.")
            elif action.action == "remove":
                if offer["removed"]:
                    raise HTTPException(409, "Оффер уже удалён из потока.")
                offer.update(removed=True, pinned=False, share=0)
            elif action.action == "restore":
                if not offer["removed"]:
                    raise HTTPException(409, "Оффер уже активен.")
                available = self.client.request("GET", "offers")
                if not any(int(o["id"]) == action.offer_id and o.get("state", "active") == "active" for o in available):
                    raise HTTPException(422, "Оффер больше недоступен в Keitaro.")
                offer.update(removed=False, pinned=False)
            else:
                if offer["removed"]:
                    raise HTTPException(422, "Сначала восстановите оффер.")
                if action.action in ("share", "pin"):
                    if action.action == "share" and action.share is None:
                        raise HTTPException(422, "Укажите процент.")
                    offer.update(share=action.share if action.share is not None else offer["share"], pinned=True)
                else:
                    offer["pinned"] = False
            try:
                stream["offers"] = distribute(offers)
            except ShareError as exc:
                raise HTTPException(422, str(exc)) from exc
            payload = [{"offer_id": o["offer_id"], "share": o["share"], "state": "active"} for o in stream["offers"] if not o["removed"]]
            self.client.request("PUT", f"streams/{stream_id}", json={"offers": payload})
            # Persist UI-only pin/removal metadata after the API accepted the change.
            row.snapshot = snapshot
            row.revision += 1
            db.commit()
            result = self.refresh(campaign_id)
            actual = next(s for s in result["streams"] if s["id"] == stream_id)
            expected = {o["offer_id"]: o["share"] for o in payload}
            received = {o["offer_id"]: o["share"] for o in actual["offers"] if not o["removed"]}
            if expected != received:
                raise HTTPException(409, "Keitaro сохранил другие доли. Данные перечитаны; обновите интерфейс.")
            return result

    def stats(self, campaign_id):
        self._allowed(self.client.request("GET", f"campaigns/{campaign_id}"))
        return self.client.request("POST", "report/build", json={
            "range": {"interval": "today", "timezone": "UTC"}, "dimensions": ["stream_id", "offer_id"],
            "metrics": ["clicks", "conversions", "revenue"],
            "filters": [{"name": "campaign_id", "operator": "EQUALS", "expression": campaign_id}],
        })
