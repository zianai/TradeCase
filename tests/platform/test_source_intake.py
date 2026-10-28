from datetime import timedelta

from test_api import api as api

from tradecase.platform.db import utcnow


def test_manual_public_snapshot_has_honest_origin_and_exact_quote(api):
    client, app, headers, other, viewer = api
    case = client.post(
        "/api/cases", headers=headers, json={"title": "Actual inquiry", "raw_content": "Please quote components."}
    ).json()
    payload = {
        "case_version": case["version"],
        "url": "https://official.example.org/company",
        "title": "User-supplied copy",
        "captured_at": (utcnow() - timedelta(minutes=1)).isoformat(),
        "text": "Acme Company makes components.",
        "excerpt": "Acme Company makes components.",
        "claim": "The page describes components.",
    }
    path = "/api/cases/" + case["id"] + "/sources"
    assert client.post(path, headers={**viewer, "Idempotency-Key": "source"}, json=payload).status_code == 403
    response = client.post(path, headers={**headers, "Idempotency-Key": "source"}, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["tested_live"] is False
    evidence = client.get("/api/cases/" + case["id"] + "/evidence", headers=headers).json()
    assert evidence["claims"][0]["classification"] == "UNKNOWN"
    assert evidence["sources"][0]["data"]["retrieval_method"] == "human_uploaded_snapshot"
    assert (
        client.post(path, headers={**headers, "Idempotency-Key": "source"}, json=payload).json()["source_id"]
        == response.json()["source_id"]
    )
    assert (
        client.post(
            path, headers={**headers, "Idempotency-Key": "bad"}, json={**payload, "excerpt": "invented"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            path, headers={**headers, "Idempotency-Key": "ssrf"}, json={**payload, "url": "http://127.0.0.1/"}
        ).status_code
        == 422
    )
    assert client.get("/api/cases/" + case["id"] + "/evidence", headers=other).status_code == 404
