from __future__ import annotations

import urllib.parse


def intent_url(text: str) -> str:
    return "https://x.com/intent/post?text=" + urllib.parse.quote(text, safe="")
