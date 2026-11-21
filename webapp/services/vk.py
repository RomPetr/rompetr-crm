from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from webapp.config import ROOT, get_settings

log = logging.getLogger(__name__)

VK_API_URL = "https://api.vk.com/method/"
VK_ID_AUTHORIZE_URL = "https://id.vk.ru/authorize"
VK_ID_TOKEN_URL = "https://id.vk.ru/oauth2/auth"
VK_API_VERSION = "5.199"
OAUTH_COOKIE = "vk_oauth_state"
OAUTH_STATE_TTL = 600
TOKEN_REFRESH_MARGIN = 60
_token_lock = Lock()


class VKError(RuntimeError):
    def __init__(self, message: str, *, code: int | None = None, unknown: bool = False):
        super().__init__(message)
        self.code = code
        self.unknown = unknown


@dataclass
class PublishResult:
    ok: bool
    external_id: str | None = None
    url: str | None = None
    error: str | None = None
    unknown: bool = False
    warning: str | None = None


def _oauth_path() -> Path:
    path = Path(get_settings().vk_oauth_file)
    return path if path.is_absolute() else ROOT / path


def redirect_uri() -> str:
    settings = get_settings()
    explicit = settings.vk_redirect_uri.strip()
    if explicit:
        return explicit
    return settings.app_base_url.rstrip("/") + "/admin/vk/callback"


def config_problems() -> list[str]:
    settings = get_settings()
    problems: list[str] = []
    if not settings.vk_client_id.strip():
        problems.append("VK_CLIENT_ID не задан")
    if not (
        settings.vk_service_key.get_secret_value()
        or settings.vk_secret_key.get_secret_value()
    ):
        problems.append("VK_SERVICE_KEY не задан")
    return problems


def oauth_configured() -> bool:
    return not config_problems()


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def authorize_url(state: str, challenge: str) -> str:
    settings = get_settings()
    params = {
        "response_type": "code",
        "client_id": settings.vk_client_id.strip(),
        "redirect_uri": redirect_uri(),
        "scope": settings.vk_oauth_scope.strip() or "photos",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "consent",
    }
    return VK_ID_AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)


def _cookie_signature(value: str) -> str:
    key = get_settings().app_secret_key.get_secret_value().encode("utf-8")
    digest = hmac.new(key, value.encode("ascii"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def pack_oauth_cookie(payload: dict) -> str:
    body = dict(payload)
    body["exp"] = int(time.time()) + OAUTH_STATE_TTL
    encoded = base64.urlsafe_b64encode(
        json.dumps(body, separators=(",", ":")).encode("utf-8")
    ).rstrip(b"=").decode("ascii")
    return f"{encoded}.{_cookie_signature(encoded)}"


def read_oauth_cookie(value: str | None) -> dict | None:
    if not value or "." not in value:
        return None
    encoded, signature = value.rsplit(".", 1)
    if not hmac.compare_digest(signature, _cookie_signature(encoded)):
        return None
    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload


def start_oauth(admin_id: int) -> tuple[str, str]:
    if not oauth_configured():
        raise VKError("VK ID не настроен: " + ", ".join(config_problems()))
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(32)
    redirect = redirect_uri()
    cookie = pack_oauth_cookie(
        {
            "state": state,
            "verifier": verifier,
            "redirect_uri": redirect,
            "user_id": admin_id,
        }
    )
    return authorize_url(state, challenge), cookie


def _read_tokens() -> dict | None:
    path = _oauth_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        log.warning("vk token file is unreadable: %s", exc)
        return None
    if not isinstance(data, dict) or not data.get("access_token"):
        return None
    return data


def _write_tokens(data: dict) -> None:
    path = _oauth_path()
    parent = path.parent
    parent_created = not parent.exists()
    parent.mkdir(parents=True, exist_ok=True)
    if parent_created:
        try:
            os.chmod(parent, 0o700)
        except OSError:
            pass

    fd, temp_name = tempfile.mkstemp(prefix=".vk_oauth.", dir=parent)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        os.chmod(path, 0o600)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _save_token_response(
    payload: dict,
    *,
    device_id: str,
    user_id: int | None,
    fallback: dict | None = None,
) -> dict:
    access_token = str(payload.get("access_token") or "")
    if not access_token:
        raise VKError("VK ID не вернул access token")
    previous = fallback or {}
    try:
        expires_in = int(payload.get("expires_in") or 3600)
    except (TypeError, ValueError):
        expires_in = 3600
    now = int(time.time())
    tokens = {
        "access_token": access_token,
        "refresh_token": str(payload.get("refresh_token") or previous.get("refresh_token") or ""),
        "device_id": str(device_id or previous.get("device_id") or ""),
        "user_id": payload.get("user_id") or previous.get("user_id") or user_id,
        "scope": str(payload.get("scope") or previous.get("scope") or ""),
        "token_type": str(payload.get("token_type") or "Bearer"),
        "expires_at": now + expires_in,
        "updated_at": now,
    }
    _write_tokens(tokens)
    return tokens


def _token_request(payload: dict) -> dict:
    body = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(
        VK_ID_TOKEN_URL,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            data = json.loads(exc.read().decode("utf-8"))
        except (ValueError, OSError):
            raise VKError(f"VK ID HTTP {exc.code}", unknown=exc.code >= 500) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise VKError(f"VK ID недоступен: {exc}", unknown=True) from None

    if not isinstance(data, dict):
        raise VKError("VK ID вернул неожиданный ответ")
    if data.get("error"):
        code = data.get("error")
        description = data.get("error_description") or ""
        raise VKError(f"VK ID {code}: {description}".strip())
    return data


def _confidential_params() -> dict:
    settings = get_settings()
    service_token = settings.vk_service_key.get_secret_value()
    if service_token:
        return {"service_token": service_token}
    secret = settings.vk_secret_key.get_secret_value()
    if secret:
        return {"client_secret": secret}
    return {}


def exchange_code(code: str, device_id: str, verifier: str, state: str) -> dict:
    settings = get_settings()
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": redirect_uri(),
        "client_id": settings.vk_client_id.strip(),
        "device_id": device_id,
        "state": state,
    }
    payload.update(_confidential_params())
    data = _token_request(payload)
    if data.get("state") and not hmac.compare_digest(str(data["state"]), state):
        raise VKError("VK ID вернул несовпадающий state")
    return _save_token_response(data, device_id=device_id, user_id=None)


def complete_oauth(
    *, code: str, device_id: str, state: str, cookie_value: str | None, admin_id: int
) -> dict:
    pending = read_oauth_cookie(cookie_value)
    if pending is None:
        raise VKError("Сессия авторизации VK ID истекла, начните подключение заново")
    if int(pending.get("user_id", -1)) != admin_id:
        raise VKError("Авторизацию VK ID завершил другой пользователь")
    expected = str(pending.get("state") or "")
    if not expected or not hmac.compare_digest(expected, state):
        raise VKError("Параметр state не совпал")
    if not code or not device_id:
        raise VKError("VK ID не передал code/device_id")
    return exchange_code(code, device_id, str(pending.get("verifier") or ""), state)


def refresh_user_token() -> str:
    with _token_lock:
        current = _read_tokens()
        if current is None:
            raise VKError("VK ID не подключён")

        access_token = str(current.get("access_token") or "")
        expires_at = int(current.get("expires_at") or 0)
        if access_token and expires_at > int(time.time()) + TOKEN_REFRESH_MARGIN:
            return access_token

        refresh_token = str(current.get("refresh_token") or "")
        device_id = str(current.get("device_id") or "")
        if not refresh_token:
            raise VKError("VK ID: нет refresh token, подключите заново")
        if not device_id:
            raise VKError("VK ID: нет device_id, подключите заново")

        settings = get_settings()
        state = secrets.token_urlsafe(32)
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": settings.vk_client_id.strip(),
            "device_id": device_id,
            "state": state,
        }
        payload.update(_confidential_params())
        data = _token_request(payload)
        if data.get("state") and not hmac.compare_digest(str(data["state"]), state):
            raise VKError("VK ID вернул несовпадающий state при обновлении токена")
        tokens = _save_token_response(
            data,
            device_id=device_id,
            user_id=current.get("user_id"),
            fallback=current,
        )
        return str(tokens["access_token"])


def user_access_token() -> tuple[str | None, str | None]:
    current = _read_tokens()
    if current is None:
        return None, "VK ID не подключён"
    access_token = str(current.get("access_token") or "")
    expires_at = int(current.get("expires_at") or 0)
    if access_token and expires_at > int(time.time()) + TOKEN_REFRESH_MARGIN:
        return access_token, None
    try:
        return refresh_user_token(), None
    except VKError as exc:
        log.warning("vk token refresh failed: %s", exc)
        return None, f"токен VK ID не обновлён: {exc}"


def token_status() -> dict:
    path = _oauth_path()
    tokens = _read_tokens()
    if tokens is None:
        return {
            "connected": False,
            "file_exists": path.exists(),
            "file": str(path),
        }
    expires_at = int(tokens.get("expires_at") or 0)
    expires = datetime.fromtimestamp(expires_at, tz=timezone.utc) if expires_at else None
    return {
        "connected": True,
        "file_exists": True,
        "file": str(path),
        "user_id": tokens.get("user_id"),
        "scope": tokens.get("scope") or "",
        "expires_at": expires,
        "access_valid": expires_at > int(time.time()) + TOKEN_REFRESH_MARGIN,
        "refresh_available": bool(tokens.get("refresh_token")),
        "updated_at": tokens.get("updated_at"),
    }


def _group_id() -> str:
    group = re.sub(r"\D", "", get_settings().vk_group_id)
    if not group:
        raise VKError("VK_GROUP_ID не задан")
    return group


def _api(method: str, token: str, fields: dict) -> dict:
    payload = dict(fields)
    payload["access_token"] = token
    payload["v"] = VK_API_VERSION
    request = urllib.request.Request(
        VK_API_URL + method,
        data=urllib.parse.urlencode(payload).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            result = json.loads(exc.read().decode("utf-8"))
        except (ValueError, OSError):
            raise VKError(f"VK HTTP {exc.code}", unknown=exc.code >= 500) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise VKError(f"VK недоступен: {exc}", unknown=True) from None

    if not isinstance(result, dict):
        raise VKError("VK вернул неожиданный ответ")
    if "error" in result:
        error = result.get("error") or {}
        code = error.get("error_code")
        message = str(error.get("error_msg") or "unknown VK error")
        suffix = " (метод недоступен с этим типом токена)" if code == 27 else ""
        raise VKError(f"VK {code}: {message}{suffix}", code=code)
    return result.get("response", result)


def _multipart(fields: dict, files: dict) -> tuple[bytes, str]:
    boundary = "----crmvk" + uuid.uuid4().hex
    body = bytearray()
    for name, value in fields.items():
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        body += str(value).encode() + b"\r\n"
    for name, (filename, data, ctype) in files.items():
        body += f"--{boundary}\r\n".encode()
        body += (
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
        ).encode()
        body += f"Content-Type: {ctype}\r\n\r\n".encode()
        body += data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def _upload_photo(upload_url: str, image_path: Path) -> dict:
    raw = image_path.read_bytes()
    if not raw:
        raise VKError("файл изображения пуст")
    ctype = "image/jpeg" if image_path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    body, content_type = _multipart({}, {"photo": (image_path.name, raw, ctype)})
    request = urllib.request.Request(
        upload_url, data=body, headers={"Content-Type": content_type}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            data = json.loads(exc.read().decode("utf-8"))
        except (ValueError, OSError):
            raise VKError(f"загрузка фото: HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise VKError(f"загрузка фото недоступна: {exc}") from None

    if not isinstance(data, dict):
        raise VKError("VK upload server вернул неожиданный ответ")
    if data.get("error"):
        raise VKError(f"VK upload: {data['error']}")
    if not data.get("photo") or data.get("photo") == "[]":
        raise VKError("VK upload не вернул photo")
    if data.get("server") is None or data.get("hash") is None:
        raise VKError("VK upload не вернул server/hash")
    return data


def upload_wall_photo(image_path: Path | str) -> str:
    path = Path(image_path)
    if not path.exists():
        raise VKError("файл изображения не найден")
    token, warning = user_access_token()
    if not token:
        raise VKError(warning or "VK ID не подключён")
    group = _group_id()

    server_data = _api("photos.getWallUploadServer", token, {"group_id": group})
    upload_url = str(server_data.get("upload_url") or "")
    if not upload_url:
        raise VKError("VK не вернул upload_url")

    uploaded = _upload_photo(upload_url, path)
    saved = _api(
        "photos.saveWallPhoto",
        token,
        {
            "group_id": group,
            "server": uploaded["server"],
            "photo": uploaded["photo"],
            "hash": uploaded["hash"],
        },
    )
    items = saved if isinstance(saved, list) else [saved]
    if not items or not isinstance(items[0], dict) or not items[0].get("id"):
        raise VKError("VK не вернул сохранённое фото")
    item = items[0]
    owner_id = item.get("owner_id") or ("-" + group)
    return f"photo{owner_id}_{item['id']}"


def publish(text: str, image_path: Path | str | None = None) -> PublishResult:
    settings = get_settings()
    token = settings.vk_access_token.get_secret_value()
    group = re.sub(r"\D", "", settings.vk_group_id)
    if not token or not group:
        return PublishResult(ok=False, error="VK_ACCESS_TOKEN/VK_GROUP_ID не заданы")
    owner_id = "-" + group

    attachment: str | None = None
    warning: str | None = None
    if image_path:
        path = Path(image_path)
        if not path.exists():
            warning = "Фото не прикреплено: файл изображения не найден"
        else:
            try:
                attachment = upload_wall_photo(path)
            except VKError as exc:
                warning = f"Фото не прикреплено: {exc}"
                log.warning("vk photo upload failed: %s", exc)

    fields = {
        "owner_id": owner_id,
        "from_group": 1,
        "message": text,
    }
    if attachment:
        fields["attachments"] = attachment

    last_error = "unknown"
    for attempt in (1, 2):
        try:
            result = _api("wall.post", token, fields)
        except VKError as exc:
            last_error = str(exc)
            if exc.unknown:
                log.warning("vk publish attempt %s failed: %s", attempt, exc)
                if attempt == 1:
                    time.sleep(2)
                    continue
                return PublishResult(ok=False, error=last_error, unknown=True)
            return PublishResult(ok=False, error=last_error)

        post_id = result.get("post_id")
        return PublishResult(
            ok=True,
            external_id=str(post_id),
            url=f"https://vk.com/wall{owner_id}_{post_id}",
            warning=warning,
        )

    return PublishResult(ok=False, error=last_error, unknown=True)
