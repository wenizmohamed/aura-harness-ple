"""Repository configuration, schema, compile, and secret-hygiene validation script."""

from __future__ import annotations

import pathlib
import py_compile
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aura_harness.config import ConfigError, load_config  # noqa: E402


SECRET_PATTERNS = (
    re.compile(r"hf_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"AIza[A-Za-z0-9_-]{25,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


def main() -> int:
  errors: list[str] = []

  try:
    load_config(ROOT / "harness_config.json", env={})
  except ConfigError as exc:
    errors.append(f"harness_config.json invalid: {exc}")

  if not (ROOT / ".env.example").exists():
    errors.append("missing .env.example")

  if not (ROOT / "submission.yaml").exists():
    errors.append("missing submission.yaml")

  for py_file in sorted(ROOT.rglob("*.py")):
    rel = py_file.relative_to(ROOT)
    if any(part.startswith(".") or part == "__pycache__" for part in rel.parts):
      continue
    try:
      py_compile.compile(str(py_file), doraise=True)
    except py_compile.PyCompileError as exc:
      errors.append(f"syntax error in {rel}: {exc}")

  for path in sorted(ROOT.rglob("*")):
    if not path.is_file():
      continue
    rel = path.relative_to(ROOT)
    if any(part in (".git", "__pycache__", ".pytest_cache") for part in rel.parts):
      continue
    if path.suffix in (".png", ".jpg", ".pyc"):
      continue
    text = path.read_text(encoding="utf-8", errors="ignore")
    for pat in SECRET_PATTERNS:
      if pat.search(text):
        errors.append(f"potential secret pattern {pat.pattern} found in {rel}")

  if errors:
    for err in errors:
      print(f"FAIL: {err}", file=sys.stderr)
    return 1
  print("OK: config, Python syntax, required manifests, and secret hygiene validated")
  return 0


if __name__ == "__main__":
  sys.exit(main())
