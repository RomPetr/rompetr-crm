from __future__ import annotations

import logging
import sys

try:
    from pythonjsonlogger.json import JsonFormatter
except ImportError:  # python-json-logger 2.x
    from pythonjsonlogger.jsonlogger import JsonFormatter
from webapp.config import get_settings

REDACT_KEYS = {
    "password",
    "passw",
    "token",
    "secret",
    "authorization",
    "cookie",
    "session",
    "adm_passw",
    "proxyapi_key",
}


class RedactingJsonFormatter(JsonFormatter):
    def process_log_record(self, log_record: dict) -> dict:  # type: ignore[override]
        for key in list(log_record):
            if any(part in key.lower() for part in REDACT_KEYS):
                log_record[key] = "[redacted]"
        return super().process_log_record(log_record)


def configure_logging() -> None:
    settings = get_settings()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        RedactingJsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())
