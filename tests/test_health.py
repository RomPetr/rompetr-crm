from __future__ import annotations


def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_landing(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Разум DEX" in response.text
    assert response.headers["content-security-policy"].startswith("default-src 'self'")


def test_security_headers(client):
    response = client.get("/")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
