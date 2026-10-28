from datetime import timedelta

from test_api import api as api

from tradecase.platform.db import utcnow
from tradecase.platform.knowledge import KnowledgeService


def test_knowledge_versions_scope_and_validity(api):
    client, app, headers, other, viewer = api
    payload = {
        "title": "Widget product",
        "content": "Available material: steel. No certification declared.",
        "valid_until": (utcnow() + timedelta(days=30)).isoformat(),
    }
    assert client.post("/api/knowledge", headers=viewer, json=payload).status_code == 403
    first = client.post("/api/knowledge", headers=headers, json=payload)
    assert first.status_code == 200, first.text
    row = first.json()
    assert client.get("/api/knowledge", headers=other).json() == []
    assert client.get(f"/api/knowledge/{row['id']}/1", headers=other).status_code == 404
    second = client.post(
        "/api/knowledge",
        headers=headers,
        json={**payload, "document_id": row["id"], "expected_version": 1, "content": "Updated steel product notes."},
    ).json()
    assert second["version"] == 2
    assert (
        client.post(
            "/api/knowledge", headers=headers, json={**payload, "document_id": row["id"], "expected_version": 1}
        ).status_code
        == 409
    )
    service = KnowledgeService(app.state.service)
    results = service.search("alpha", "steel")
    assert len(results) == 1 and results[0]["version"] == 2
    assert service.get("alpha", row["id"], 1)["content"] == payload["content"]
    assert (
        client.post(
            "/api/knowledge",
            headers=headers,
            json={**payload, "valid_until": (utcnow() - timedelta(days=1)).isoformat()},
        ).status_code
        == 422
    )
