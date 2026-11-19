from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("git_guard", ROOT / "scripts" / "git_guard.py")
assert SPEC and SPEC.loader
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


def test_allows_system_paths():
    for path in (
        "webapp/main.py",
        "scripts/git_guard.py",
        "tests/test_health.py",
        "alembic/env.py",
        "docs/CRM-PLAN.md",
        "docs/images/site_main.png",
        ".claude/agents/pixly.md",
        ".claude/plans/crm-web-platform.yaml",
        ".claude/pixly-coin-icons.json",
        ".githooks/pre-commit",
        "README.md",
        ".env.example",
    ):
        allowed, reason = guard.classify(path)
        assert allowed, f"{path}: {reason}"


def test_blocks_data_and_secrets():
    for path in (
        "posts/151126/post.json",
        "posts/cover.png",
        "var/media/a.png",
        "docs/images/private.key",
        ".env",
        ".env.prod",
        ".claude/env.txt",
        ".claude/settings.local.json",
        ".claude/skills/ai-news-to-social/env.txt",
        ".mcp-servers/x-mcp/package.json",
        ".chrome-x-profile/Default/Cookies",
        "__pycache__/bot.pyc",
        "requirements.txt.bak",
    ):
        allowed, _ = guard.classify(path)
        assert not allowed, path


def test_secret_patterns():
    fake_proxy = "sk-" + "ant-oat01-" + "a" * 24
    fake_telegram = "123456789:" + "A" * 35
    findings = guard.scan_text(f"token: {fake_proxy}", "x")
    assert findings and findings[0][0] == guard.EXIT_SECRET
    findings = guard.scan_text(f"bot {fake_telegram}", "x")
    assert findings
    findings = guard.scan_text("обычный текст без секретов", "x")
    assert not findings
