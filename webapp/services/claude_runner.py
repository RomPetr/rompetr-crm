from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from webapp.config import ROOT, get_settings

log = logging.getLogger(__name__)
LOG_LIMIT = 1024 * 1024


@dataclass
class RunResult:
    exit_code: int
    stdout: str
    stderr: str
    parsed: dict | None
    timed_out: bool = False
    log_path: str | None = None


def _write_log(path: Path, text: str) -> None:
    data = text.encode("utf-8", "replace")[:LOG_LIMIT]
    path.write_bytes(data)


def _kill_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
        )
    else:
        try:
            os.killpg(proc.pid, 9)
        except ProcessLookupError:
            pass


def run(
    prompt: str,
    job_id: str,
    timeout_sec: int | None = None,
    allowed_tools: tuple[str, ...] | None = None,
) -> RunResult:
    settings = get_settings()
    timeout = timeout_sec or settings.claude_timeout_sec
    log_dir = ROOT / "var" / "jobs"
    log_dir.mkdir(parents=True, exist_ok=True)
    out_log = log_dir / f"{job_id}.out.log"
    err_log = log_dir / f"{job_id}.err.log"

    command = [
        settings.claude_bin,
        "-p",
        prompt,
        "--output-format",
        "json",
        "--permission-mode",
        "dontAsk",
        "--allowedTools",
        *(allowed_tools or ("Read", "Edit", "Write", "Grep", "Glob")),
        "--disallowedTools",
        "Bash(curl *)",
        "Bash(wget *)",
        "Bash(git push *)",
        "--max-turns",
        str(settings.claude_max_turns),
        "--max-budget-usd",
        str(settings.claude_max_budget_usd),
    ]
    if settings.claude_model:
        command += ["--model", settings.claude_model]
        if settings.claude_fallback_model:
            command += ["--fallback-model", settings.claude_fallback_model]
    command.append("--no-session-persistence")

    allowed_env = {
        "PATH",
        "PATHEXT",
        "HOME",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "LANG",
        "TMPDIR",
        "TEMP",
        "TMP",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_DEFAULT_SONNET_MODEL",
        "ANTHROPIC_DEFAULT_OPUS_MODEL",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    }
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed_env}
    token = settings.claude_code_oauth_token.get_secret_value()
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
    else:
        local_token = settings.anthropic_auth_token.get_secret_value()
        if local_token:
            env["ANTHROPIC_AUTH_TOKEN"] = local_token
            if settings.anthropic_base_url:
                env["ANTHROPIC_BASE_URL"] = settings.anthropic_base_url
    if settings.claude_config_dir:
        env["CLAUDE_CONFIG_DIR"] = settings.claude_config_dir
    proxy = settings.claude_http_proxy.strip()
    if proxy:
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            env[key] = proxy
        env["NO_PROXY"] = env["no_proxy"] = "127.0.0.1,localhost,::1"
    env["CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"] = "0"
    env.pop("ANTHROPIC_API_KEY", None)

    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            command,
            cwd=str(ROOT),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=os.name != "nt",
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"CLI claude не найден: {settings.claude_bin}") from exc

    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(proc)
        stdout, stderr = proc.communicate(timeout=30)

    _write_log(out_log, stdout or "")
    _write_log(err_log, stderr or "")
    duration = int((time.monotonic() - started) * 1000)
    log.info("claude job=%s exit=%s timeout=%s ms=%s", job_id, proc.returncode, timed_out, duration)

    parsed = None
    text = (stdout or "").strip()
    if text:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    parsed = None

    return RunResult(
        exit_code=proc.returncode if proc.returncode is not None else -1,
        stdout=stdout or "",
        stderr=stderr or "",
        parsed=parsed,
        timed_out=timed_out,
        log_path=str(out_log),
    )
