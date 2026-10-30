def test_invalid_meeting_returns_consistent_error_shape(client):
    res = client.post("/api/meetings", json={"title": "x", "type": "party"})
    assert res.status_code == 422
    body = res.json()
    assert set(body) == {"error", "detail", "request_id"}
    assert {d["field"] for d in body["detail"]} == {"title", "type"}
    assert body["request_id"] == res.headers["X-Request-ID"]


def test_request_id_header_is_echoed(client):
    res = client.get("/api/meetings", headers={"X-Request-ID": "demo-123"})
    assert res.headers["X-Request-ID"] == "demo-123"


def test_lifecycle_rejects_invalid_transition(client):
    meeting = client.post("/api/meetings", json={"title": "Planning"}).json()
    assert meeting["status"] == "draft"
    res = client.post(f"/api/meetings/{meeting['id']}/status", json={"status": "completed"})
    assert res.status_code == 409
    assert "Allowed next steps" in res.json()["detail"]
    for step in ("scheduled", "completed", "archived"):
        assert client.post(f"/api/meetings/{meeting['id']}/status", json={"status": step}).status_code == 200
    assert client.post(f"/api/meetings/{meeting['id']}/status", json={"status": "draft"}).status_code == 409


def test_closing_item_requires_outcome_and_is_logged_in_history(client):
    meeting = client.post("/api/meetings", json={"title": "Planning"}).json()
    item = client.post("/api/items", json={"meeting_id": meeting["id"], "title": "Write plan", "owner": "Ana"}).json()
    assert client.patch(f"/api/items/{item['id']}", json={"status": "done"}).status_code == 422
    client.patch(f"/api/items/{item['id']}", json={"owner": "Ben"})
    res = client.patch(f"/api/items/{item['id']}", json={"status": "done", "outcome": "Shipped"})
    assert res.status_code == 200 and res.json()["outcome"] == "Shipped"
    types = [e["type"] for e in client.get(f"/api/items/{item['id']}").json()["history"]]
    assert types == ["created", "reassigned", "closed"]


def test_soft_delete_hides_meeting(client):
    meeting = client.post("/api/meetings", json={"title": "Temp meeting"}).json()
    assert client.delete(f"/api/meetings/{meeting['id']}").status_code == 204
    assert client.get(f"/api/meetings/{meeting['id']}").status_code == 404
    assert meeting["id"] not in [m["id"] for m in client.get("/api/meetings").json()]
