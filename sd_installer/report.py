"""
StreamDiffusionTD Installer Error Report

Builds a self-contained, human-readable diagnostic report (schema v1) when an
installation phase fails, and backs the manual `report` CLI subcommand.

Best-effort by design: report generation must never raise past write_error_report's
own try/except, so a bug in the reporter never masks the real installation error.
"""

import datetime
import os
import platform
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Optional

from .verifier import Verifier, match_known_error

SCHEMA_VERSION = "v1"
# Only these env-var prefixes are dumped -- never the full os.environ (avoids leaking secrets).
ENV_ALLOWLIST_PREFIXES = ("CUDALINK_", "HF_", "SD_", "SDTD_")
# Even an allowlisted-prefix var is dropped if its name contains one of these substrings --
# a prefix match alone isn't enough (e.g. HF_TOKEN matches "HF_" but must never be dumped).
ENV_DENYLIST_SUBSTRINGS = ("TOKEN", "KEY", "SECRET", "PASSWORD", "PASSWD", "CRED")


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _nvidia_smi_driver() -> str:
    """Query the NVIDIA driver version via nvidia-smi. Best-effort."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().splitlines()[0]
    except Exception:
        pass
    return "unknown"


def _collect_env_allowlist() -> dict:
    """Collect only allow-listed env vars -- never dump full os.environ (secrets)."""
    return {
        k: v
        for k, v in sorted(os.environ.items())
        if k.startswith(ENV_ALLOWLIST_PREFIXES) and not any(bad in k.upper() for bad in ENV_DENYLIST_SUBSTRINGS)
    }


def _format_section(title: str, lines: list) -> str:
    body = "\n".join(lines) if lines else "(none)"
    return f"== {title} ==\n{body}\n"


def build_report_text(context: dict) -> str:
    """
    Build the schema-v1 diagnostic report text.

    Expected context keys (all optional unless noted):
        stage (str, required): "installation"
        exc (BaseException): the caught exception -- feeds SUMMARY + TRACEBACK
        exc_text (str): pre-formatted traceback text, used when `exc` is absent
        phase (str): name of the failing (or current, for manual reports) phase
        python_exe (str | Path): venv python -- used to run Verifier.diagnose()
        base_folder, cuda_version, pytorch_config, venv_path: installer config
        pip_stderr (str): captured stderr tail from the failing pip invocation

    Returns:
        Full report text, ready to write to disk.
    """
    stage = context.get("stage", "installation")
    lines = [
        "StreamDiffusionTD Error Report   (schema v1)",
        f"Generated: {_utc_now().isoformat()}",
        f"Stage: {stage}",
        "-" * 50,
        "",
    ]

    # == SUMMARY ==
    exc = context.get("exc")
    if exc is not None:
        error_line = f"{type(exc).__name__}: {exc}"
    elif context.get("exc_text"):
        error_line = context["exc_text"].strip().splitlines()[-1]
    else:
        error_line = "unknown"
    summary_lines = [f"Error: {error_line}", f"Context: {context.get('phase', 'unknown')}"]

    pip_stderr = context.get("pip_stderr")
    match_text = pip_stderr or (str(exc) if exc is not None else "")
    known = None
    if match_text:
        try:
            known = match_known_error(match_text)
        except Exception:
            known = None
    if known:
        summary_lines.append(f"Known-cause match: {known['cause']} -- fix: {known['fix']}")
    lines.append(_format_section("SUMMARY", summary_lines))

    # == TRACEBACK ==
    if exc is not None:
        tb_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    else:
        tb_text = context.get("exc_text") or "(no traceback available)"
    lines.append(_format_section("TRACEBACK", [tb_text.rstrip("\n")]))

    # == SYSTEM == / == VERSIONS ==
    system_lines = [
        f"OS: {platform.platform()}",
        f"Python (host): {sys.version.replace(chr(10), ' ')}",
        f"NVIDIA driver: {_nvidia_smi_driver()}",
    ]
    versions_lines = []
    python_exe = context.get("python_exe")
    if python_exe:
        try:
            info = Verifier(str(python_exe)).diagnose()
            gpu = info.get("gpu", {})
            if gpu:
                system_lines.append(f"GPU: {gpu.get('name', 'unknown')}")
                if "vram_mb" in gpu:
                    system_lines.append(f"VRAM total: {gpu['vram_mb']} MB")
                if "compute_capability" in gpu:
                    system_lines.append(f"Compute capability: {gpu['compute_capability']}")
            for pkg, version in info.get("versions", {}).items():
                versions_lines.append(f"{pkg}: {version}")
        except Exception as diag_exc:
            versions_lines.append(f"(Verifier.diagnose() failed: {diag_exc})")
    else:
        versions_lines.append("(no python_exe provided -- venv package versions unavailable)")
    lines.append(_format_section("SYSTEM", system_lines))
    lines.append(_format_section("VERSIONS", versions_lines))

    # == CONFIG ==
    config_keys = ("base_folder", "cuda_version", "pytorch_config", "venv_path")
    config_lines = [f"{key}: {context[key]}" for key in config_keys if key in context]
    lines.append(_format_section("CONFIG", config_lines))

    # == ENV ==
    env_lines = [f"{k}={v}" for k, v in _collect_env_allowlist().items()]
    lines.append(_format_section("ENV", env_lines))

    # == LOG TAIL ==
    log_lines = pip_stderr.strip().splitlines()[-50:] if pip_stderr else []
    lines.append(_format_section("LOG TAIL", log_lines))

    return "\n".join(lines)


def write_error_report(out_dir, context: dict) -> Optional[Path]:
    """
    Build and write a diagnostic report to disk.

    Best-effort -- any failure here is caught, printed, and swallowed rather than
    raised, so a reporting bug never masks the original installation error.

    Args:
        out_dir: Directory to write the report into (created if missing).
        context: See build_report_text() for expected keys.

    Returns:
        Path to the written report, or None if writing failed.
    """
    try:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        timestamp = _utc_now().strftime("%Y%m%d_%H%M%S")
        report_path = out_dir / f"install_error_report_{timestamp}.txt"
        report_path.write_text(build_report_text(context), encoding="utf-8")
        return report_path
    except Exception as write_exc:
        print(f"  WARNING: Failed to write error report: {write_exc}")
        return None
