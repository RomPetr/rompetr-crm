from __future__ import annotations

import importlib.util
import json
import shutil
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("json_to_md", ROOT / "scripts" / "json_to_md.py")
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_md_copy_has_real_newlines():
    folder = ROOT / "posts" / f"_md_test_{uuid.uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        path = folder / "2026-11-16-000000-crypto-ai-social-content.json"
        path.write_text(
            json.dumps(
                {
                    "source": {
                        "title": "Test title",
                        "url": "https://example.com/news",
                        "published_at": "2026-11-16",
                        "publisher": "The Block",
                    },
                    "platforms": {
                        "telegram": {"content": "Первый абзац.\n\nВторой абзац."},
                        "vk": {"content": "VK текст #тег"},
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        assert module.main([str(path)]) == 0
        md_path = path.with_suffix(".md")
        assert md_path.exists()
        text = md_path.read_text(encoding="utf-8")
        assert "\\n" not in text
        assert "## Telegram" in text
        assert "Первый абзац.\n\nВторой абзац." in text
        assert "## ВКонтакте" in text
    finally:
        shutil.rmtree(folder, ignore_errors=True)
