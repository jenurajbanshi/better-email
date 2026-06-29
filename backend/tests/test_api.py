"""API contract + access-control tests."""
from __future__ import annotations


def test_health_is_public(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_protected_routes_require_auth(client):
    no_auth = client.__class__(client.app)  # fresh client, no API key header
    for path in ["/api/inbox", "/api/stats", "/api/suggestions"]:
        assert no_auth.get(path).status_code == 401


def test_invalid_key_rejected(client):
    bad = client.__class__(client.app)
    bad.headers.update({"X-API-Key": "totally-wrong"})
    assert bad.get("/api/inbox").status_code == 401


def test_sync_then_inbox_is_accountability_sorted(client):
    synced = client.post("/api/sync").json()
    assert synced["ingested"] > 0

    inbox = client.get("/api/inbox").json()
    assert len(inbox) >= 5
    # The top customer must be the most accountability-critical (forgotten or
    # needs-response), never a resolved/waiting one.
    top = inbox[0]
    assert top["forgotten_requests"] > 0 or top["needs_response"]


def test_stats_endpoint(client):
    client.post("/api/sync")
    stats = client.get("/api/stats").json()
    assert stats["customers"] >= 5
    assert stats["open_requests"] >= 1
    assert stats["needs_response"] >= 1


def test_draft_reply(client):
    client.post("/api/sync")
    inbox = client.get("/api/inbox").json()
    req_id = inbox[0]["requests"][0]["id"]
    draft = client.post(f"/api/requests/{req_id}/draft").json()
    assert len(draft["draft"]) > 0


def test_reply_flips_status_to_waiting(client):
    client.post("/api/sync")
    # Find a needs_reply request.
    inbox = client.get("/api/inbox").json()
    req_id = None
    for c in inbox:
        for r in c["requests"]:
            if r["status"] == "needs_reply":
                req_id = r["id"]
                break
        if req_id:
            break
    assert req_id is not None
    detail = client.post(f"/api/requests/{req_id}/reply", json={"body": "We are on it!"}).json()
    assert detail["status"] == "waiting"
    assert any(m["direction"] == "outbound" for m in detail["messages"])


def test_resolve_request(client):
    client.post("/api/sync")
    inbox = client.get("/api/inbox").json()
    req_id = inbox[0]["requests"][0]["id"]
    out = client.post(f"/api/requests/{req_id}/resolve").json()
    assert out["status"] == "resolved"
    assert out["needs_response"] is False


def test_tenant_isolation(client, session):
    """A second owner must never see the first owner's data."""
    from app.models import Owner
    from app.security import hash_api_key

    client.post("/api/sync")  # owner 1 has data
    other = Owner(email="intruder@test.local", api_key_hash=hash_api_key("intruder-key"))
    session.add(other)
    session.commit()

    intruder = client.__class__(client.app)
    intruder.headers.update({"X-API-Key": "intruder-key"})
    assert intruder.get("/api/inbox").json() == []
    assert intruder.get("/api/stats").json()["customers"] == 0

    # And cannot read a specific request belonging to owner 1.
    inbox = client.get("/api/inbox").json()
    req_id = inbox[0]["requests"][0]["id"]
    assert intruder.get(f"/api/requests/{req_id}").status_code == 404
