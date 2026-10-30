from datetime import date, timedelta

from app.services.health import compute_health
from app.services.meetings import get_meeting


def test_carry_over_copies_open_items_and_keeps_chain(client):
    new = client.post("/api/meetings", json={"title": "Atlas Weekly Sync #3", "previous_meeting_id": 2}).json()
    res = client.post(f"/api/meetings/{new['id']}/carry-over", json={}).json()
    titles = {i["title"]: i for i in res["meeting"]["items"]}
    # Only items still live in meeting 2 move: the contract and budget were already carried to the handover.
    assert set(titles) == {"Set up PayFlow sandbox accounts and test cards", "Write regression test plan for checkout"}
    copy = titles["Write regression test plan for checkout"]
    assert copy["carry_count"] == 1 and copy["parent_item_id"] is not None
    history = client.get(f"/api/items/{copy['id']}").json()
    assert [c["id"] for c in history["chain"]] == [copy["parent_item_id"], copy["id"]]
    assert "created" in [e["type"] for e in history["history"]]  # original history kept
    # A second carry finds nothing new
    assert client.post(f"/api/meetings/{new['id']}/carry-over", json={}).json()["carried"] == 0


def test_superseded_item_cannot_be_edited(client):
    res = client.patch("/api/items/1", json={"owner": "Someone"})  # seed item 1 was carried forward
    assert res.status_code == 409 and res.json()["error"] == "item_superseded"


def test_health_score_rules(client, db):
    m = client.post("/api/meetings", json={"title": "Score test", "type": "handover",
                                           "participants": [{"name": "Ana", "attended": "no"}]}).json()
    mid = m["id"]
    late = (date.today() - timedelta(days=3)).isoformat()
    client.post("/api/items", json={"meeting_id": mid, "title": "No owner item"})
    for n in range(3):
        client.post("/api/items", json={"meeting_id": mid, "title": f"Ana task {n}", "owner": "Ana", "due_date": late})
    health = compute_health(db, get_meeting(db, mid))
    codes = {r["code"]: r["penalty"] for r in health["reasons"]}
    # no_owner 10, overdue 3x10=30 (cap 30), missed_no_brief 8, handover_no_kb 15, bus_factor 10 (Ana owns 100%)
    assert codes["no_owner"] == 10 and codes["handover_no_kb"] == 15 and codes["missed_no_brief"] == 8
    assert codes["bus_factor"] == 10
    assert sum(r["penalty"] for r in health["reasons"] if r["code"] == "overdue") == 30
    assert health["score"] == 100 - (10 + 30 + 8 + 15 + 10)
    assert health["band"] == "red"


def test_brief_removes_missed_meeting_penalty(client):
    before = client.get("/api/meetings/2/health").json()
    assert any(r["code"] == "missed_no_brief" and r["recipient"] == "Daniel Okafor" for r in before["reasons"])
    client.post("/api/meetings/2/briefs", json={"person_name": "Daniel Okafor"})
    after = client.get("/api/meetings/2/health").json()
    assert not any(r["code"] == "missed_no_brief" and r["recipient"] == "Daniel Okafor" for r in after["reasons"])
    assert after["score"] > before["score"]


def test_nudges_and_mark_sent(client):
    nudges = client.post("/api/meetings/3/nudges").json()["nudges"]
    assert any("overdue" in n["message"] for n in nudges)
    res = client.post(f"/api/nudges/{nudges[0]['id']}/sent")
    assert res.status_code == 200 and res.json()["sent_at"]
    assert client.post(f"/api/nudges/{nudges[0]['id']}/sent").status_code == 409
