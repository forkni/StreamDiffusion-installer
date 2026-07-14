---
applyTo: "**/*.py"
---

# Python review guidance — StreamDiffusion-installer (Windows CLI installer)

This is a Windows CLI (`sd-installer`) that drives a multi-phase install of CUDA/torch/ModelOpt/
ONNX/TensorRT dependencies by shelling out to `pip`, `nvidia-smi`, and related tools. There is no
ruff/pyrefly config in this repo (unlike the sibling `StreamDiffusion` library repo) — don't assume
its style conventions apply here.

## Flag these

- **`subprocess` calls with `shell=True`** where any part of the command is not a fixed literal —
  string-built commands incorporating a version string, path, or other variable input are a command
  injection risk. Prefer an argument list with `shell=False` (the existing pattern in
  `sd_installer/report.py`'s `_nvidia_smi_driver()`).
- **Secret-shaped values leaking into logs or error reports.** `sd_installer/report.py` defines
  `ENV_ALLOWLIST_PREFIXES` (`CUDALINK_`, `HF_`, `SD_`, `SDTD_`) and
  `ENV_DENYLIST_SUBSTRINGS` (`TOKEN`, `KEY`, `SECRET`, `PASSWORD`, `PASSWD`, `CRED`) as the one
  intentional pattern for env-var capture — new code that dumps environment/config state should
  reuse or extend this, not add a parallel allowlist/denylist.
- **Install phases that leave the environment partially modified without being resumable or
  clearly reported.** `installer.py`'s `install()` runs a `phases` list wrapped in try/finally —
  a new phase should fail loudly (write an error report, re-raise) rather than silently continuing
  past a failed step.
- **Error-reporting code that can raise.** `report.py` / `installer.py`'s
  `_write_install_error_report()` must stay best-effort — any exception inside report generation
  must be caught internally so it never masks or replaces the real installation error being
  reported.
- **Windows-path assumptions that break on other separators/drives** — this installer targets
  Windows specifically (see `pyproject.toml` classifiers), but avoid hardcoded backslash-joined
  paths where `pathlib.Path` composition already works portably.

## Do NOT flag

- Missing type hints beyond what's already present — this repo doesn't enforce a strict typing
  policy like the sibling library repo.
- Style nits (import order, line length) — there's no ruff/black config in this repo to violate.
