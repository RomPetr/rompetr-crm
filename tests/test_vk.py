from __future__ import annotations

import base64
import hashlib
import json
import urllib.parse
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from webapp.services import vk


@pytest.fixture
def settings(tmp_path, monkeypatch):
    fake = SimpleNamespace(
        vk_oauth_file=str(tmp_path / "secrets" / "vk_oauth.json"),
        vk_client_id="12345678",
        vk_secret_key=SecretStr("sekret-key"),
        vk_service_key=SecretStr("service-key"),
        vk_redirect_uri="https://rompetr.autos/admin/vk/callback",
        vk_oauth_scope="photos",
        app_base_url="https://rompetr.autos",
        app_secret_key=SecretStr("test-signing-key"),
        cookie_secure=False,
        vk_access_token=SecretStr("community-token"),
        vk_group_id="243080370",
    )
    monkeypatch.setattr("webapp.services.vk.get_settings", lambda: fake)
    return fake


def test_pkce_pair_and_authorize_url(settings):
    verifier, challenge = vk.pkce_pair()
    assert 43 <= len(verifier) <= 128
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    assert challenge == expected

    state = "s" * 43
    query = urllib.parse.parse_qs(
        urllib.parse.urlparse(vk.authorize_url(state, challenge)).query
    )
    assert query["client_id"] == ["12345678"]
    assert query["redirect_uri"] == ["https://rompetr.autos/admin/vk/callback"]
    assert query["scope"] == ["photos"]
    assert query["state"] == [state]
    assert query["code_challenge"] == [challenge]
    assert query["code_challenge_method"] == ["S256"]


def test_oauth_cookie_contains_state_and_verifier(settings):
    url, cookie = vk.start_oauth(0)
    assert "state=" in url
    pending = vk.read_oauth_cookie(cookie)
    assert pending is not None
    assert pending["user_id"] == 0
    assert pending["redirect_uri"] == "https://rompetr.autos/admin/vk/callback"
    assert pending["state"] in url
    assert len(pending["verifier"]) >= 43

    tampered = cookie[:-2] + ("aa" if not cookie.endswith("aa") else "bb")
    assert vk.read_oauth_cookie(tampered) is None


def test_exchange_code_saves_tokens_without_client_secret(settings, monkeypatch):
    captured = {}

    def fake_request(payload):
        captured.update(payload)
        return {
            "access_token": "access-1",
            "refresh_token": "refresh-1",
            "expires_in": 3600,
            "user_id": 852659808,
            "state": payload["state"],
            "scope": "photos",
        }

    monkeypatch.setattr("webapp.services.vk._token_request", fake_request)
    tokens = vk.exchange_code("code-1", "device-1", "verifier-1", "state-1")

    assert captured["grant_type"] == "authorization_code"
    assert captured["service_token"] == "service-key"
    assert "client_secret" not in captured
    assert tokens["refresh_token"] == "refresh-1"
    saved = vk._read_tokens()
    assert saved is not None
    assert saved["user_id"] == 852659808
    assert saved["device_id"] == "device-1"
    assert saved["expires_at"] > 0


def test_refresh_rotates_token_and_reuses_valid_access(settings, monkeypatch):
    vk._write_tokens(
        {
            "access_token": "old-access",
            "refresh_token": "old-refresh",
            "device_id": "device-1",
            "user_id": 852659808,
            "expires_at": 1,
        }
    )
    calls = []

    def fake_request(payload):
        calls.append(payload)
        return {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
            "user_id": 852659808,
            "state": payload["state"],
            "scope": "photos",
        }

    monkeypatch.setattr("webapp.services.vk._token_request", fake_request)
    assert vk.refresh_user_token() == "new-access"
    assert calls[0]["grant_type"] == "refresh_token"
    assert calls[0]["refresh_token"] == "old-refresh"
    assert calls[0]["device_id"] == "device-1"
    assert calls[0]["service_token"] == "service-key"
    assert vk._read_tokens()["refresh_token"] == "new-refresh"

    assert vk.refresh_user_token() == "new-access"
    assert len(calls) == 1


def test_refresh_failure_falls_back_to_no_photo(settings, monkeypatch):
    vk._write_tokens(
        {
            "access_token": "old-access",
            "refresh_token": "old-refresh",
            "device_id": "device-1",
            "expires_at": 1,
        }
    )

    def fail(payload):
        raise vk.VKError("VK ID invalid_token: expired")

    monkeypatch.setattr("webapp.services.vk._token_request", fail)
    token, warning = vk.user_access_token()
    assert token is None
    assert warning and "не обновлён" in warning


def test_upload_wall_photo_builds_attachment(settings, monkeypatch, tmp_path):
    image = tmp_path / "post.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    monkeypatch.setattr("webapp.services.vk.user_access_token", lambda: ("user-token", None))
    uploads = {}
    calls = []

    def fake_api(method, token, fields):
        calls.append((method, token, fields))
        if method == "photos.getWallUploadServer":
            return {"upload_url": "https://upload.vk.test/photo"}
        if method == "photos.saveWallPhoto":
            return [{"id": 55, "owner_id": -243080370}]
        raise AssertionError(method)

    def fake_upload(url, path):
        uploads["url"] = url
        uploads["path"] = path
        return {"server": "10", "photo": '[{"photo":"x"}]', "hash": "abc"}

    monkeypatch.setattr("webapp.services.vk._api", fake_api)
    monkeypatch.setattr("webapp.services.vk._upload_photo", fake_upload)

    attachment = vk.upload_wall_photo(image)
    assert attachment == "photo-243080370_55"
    assert uploads["url"] == "https://upload.vk.test/photo"
    assert uploads["path"] == image
    assert calls[1][2] == {
        "group_id": "243080370",
        "server": "10",
        "photo": '[{"photo":"x"}]',
        "hash": "abc",
    }


def test_publish_attaches_photo(settings, monkeypatch, tmp_path):
    image = tmp_path / "post.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    monkeypatch.setattr(
        "webapp.services.vk.upload_wall_photo", lambda path: "photo-243080370_55"
    )
    captured = {}

    def fake_api(method, token, fields):
        captured.update(fields)
        return {"post_id": 77}

    monkeypatch.setattr("webapp.services.vk._api", fake_api)
    result = vk.publish("Текст", image)
    assert result.ok
    assert result.url == "https://vk.com/wall-243080370_77"
    assert result.warning is None
    assert captured["attachments"] == "photo-243080370_55"
    assert captured["owner_id"] == "-243080370"


def test_publish_error_27_falls_back_to_text(settings, monkeypatch):
    def reject(path):
        raise vk.VKError("VK 27: method is unavailable with this token", code=27)

    monkeypatch.setattr("webapp.services.vk.upload_wall_photo", reject)
    captured = {}

    def fake_api(method, token, fields):
        captured.update(fields)
        return {"post_id": 78}

    monkeypatch.setattr("webapp.services.vk._api", fake_api)
    result = vk.publish("Текст", Path("missing.png"))
    assert result.ok
    assert result.warning and "не найден" in result.warning
    assert "attachments" not in captured

    real = Path(__file__)
    result = vk.publish("Текст", real)
    assert result.ok
    assert result.warning and "27" in result.warning
    assert "attachments" not in captured


def test_token_status_does_not_expose_tokens(settings):
    vk._write_tokens(
        {
            "access_token": "secret-access",
            "refresh_token": "secret-refresh",
            "device_id": "device-1",
            "user_id": 852659808,
            "scope": "photos",
            "expires_at": 4102444800,
        }
    )
    status = vk.token_status()
    assert status["connected"] is True
    assert status["user_id"] == 852659808
    assert status["scope"] == "photos"
    rendered = json.dumps(status, default=str)
    assert "secret-access" not in rendered
    assert "secret-refresh" not in rendered
