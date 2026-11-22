# -*- coding: utf-8 -*-
"""Shared helpers for the `scientific-editable-schematic` skill.

Design constraints (frozen in CONTRACT.md):
  * Python 3 standard library only for the core path. Optional third-party
    modules (matplotlib / Pillow / pypdf) are used behind availability probes
    and their absence is reported, never faked.
  * No network access, no author-machine absolute paths, never write into the
    input tree (``/input`` is read-only material).
  * Subprocesses are launched with argument arrays and ``shell=False``.
  * Every stage writes machine-readable evidence; stdout is always JSON.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone

# --------------------------------------------------------------------------
# Exit codes (frozen contract)
# --------------------------------------------------------------------------
OK = 0
CONFIG = 2        # bad arguments / malformed JSON / path escape
ENV_BLOCKED = 3   # required tool or input capability genuinely missing
COMPLIANCE = 4    # produced artifacts fail the export compliance gate

SCHEMA_VERSION = "1.0"
SKILL_NAME = "scientific-editable-schematic"

# Resource limits published by the platform for a skill bundle.
MAX_SKILL_FILES = 50
MAX_FILE_BYTES = 500_000
MAX_TOTAL_BYTES = 2_000_000


class SkillError(Exception):
    """Fatal, expected failure carrying a contract exit code."""

    def __init__(self, message: str, code: int = CONFIG):
        super().__init__(message)
        self.code = code


def die(message: str, code: int = CONFIG):
    raise SkillError(message, code)


def log(message: str) -> None:
    sys.stderr.write(str(message).rstrip() + "\n")
    sys.stderr.flush()


def emit(obj) -> None:
    """Print the single machine-readable result of a stage to stdout."""
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    sys.stdout.flush()


# --------------------------------------------------------------------------
# Time / hashing
# --------------------------------------------------------------------------
def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


# --------------------------------------------------------------------------
# JSON / text IO
# --------------------------------------------------------------------------
def load_json(path, default=None):
    p = str(path)
    if not os.path.isfile(p):
        return default
    try:
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        die("cannot parse JSON %s: %s" % (p, exc), CONFIG)


# Alias kept deliberately: `run.py` imports `read_json`. Both names are the same
# function, so a caller may use whichever reads better in context.
read_json = load_json


def write_json(path, obj, indent: int = 2) -> str:
    p = str(path)
    parent = os.path.dirname(p)
    if parent:
        os.makedirs(parent, exist_ok=True)
    text = json.dumps(obj, ensure_ascii=False, indent=indent)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text + "\n")
    return p


def write_text(path, text: str) -> str:
    p = str(path)
    parent = os.path.dirname(p)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return p


def read_text(path) -> str:
    """Read text with a small encoding ladder; never raises on odd bytes."""
    p = str(path)
    with open(p, "rb") as fh:
        raw = fh.read()
    for enc in ("utf-8", "utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


def write_jsonl(path, rows) -> str:
    p = str(path)
    parent = os.path.dirname(p)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return p


def read_jsonl(path):
    p = str(path)
    rows = []
    if not os.path.isfile(p):
        return rows
    with open(p, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    return rows


# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
def resolve(path, base=None) -> str:
    p = str(path)
    if base and not os.path.isabs(p):
        p = os.path.join(str(base), p)
    return os.path.abspath(p)


def is_within(base, candidate) -> bool:
    """True when `candidate` is inside `base` (both absolute)."""
    base_abs = os.path.abspath(str(base))
    cand_abs = os.path.abspath(str(candidate))
    try:
        return os.path.commonpath([base_abs, cand_abs]) == base_abs
    except ValueError:
        return False


def safe_relpath(base, candidate) -> str:
    """Relative POSIX path of `candidate` under `base`, or raise."""
    base_abs = os.path.abspath(str(base))
    cand_abs = os.path.abspath(str(candidate))
    if not is_within(base_abs, cand_abs):
        die("path escapes its root: %s not under %s" % (cand_abs, base_abs), CONFIG)
    return os.path.relpath(cand_abs, base_abs).replace(os.sep, "/")


def ensure_dir(path) -> str:
    p = str(path)
    os.makedirs(p, exist_ok=True)
    return p


def fresh_dir(path) -> str:
    """Create an empty directory, clearing a previous run of the same name."""
    p = str(path)
    if os.path.isdir(p):
        shutil.rmtree(p)
    os.makedirs(p, exist_ok=True)
    return p


def stem_of(path) -> str:
    return os.path.splitext(os.path.basename(str(path)))[0]


def slug(text: str, fallback: str = "item") -> str:
    s = re.sub(r"[^0-9A-Za-z]+", "-", str(text)).strip("-").lower()
    return s or fallback


# --------------------------------------------------------------------------
# Source discovery / typing
# --------------------------------------------------------------------------
TEXT_EXT = {".md", ".markdown", ".txt", ".json", ".yaml", ".yml", ".csv", ".tsv",
            ".tex", ".bib", ".xml", ".html", ".htm", ".rst", ".srt", ".vtt",
            ".py", ".r", ".m", ".sql", ".dot", ".mmd", ".puml"}
TABLE_EXT = {".csv", ".tsv", ".xlsx", ".xlsm"}
PDF_EXT = {".pdf"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp",
             ".svg", ".eps"}
DOC_EXT = {".docx", ".pptx"}
META_NAMES = {"case.json", "task.md", "resources.yaml", "resources.yml"}


def detect_kind(path) -> str:
    """Coarse material kind used for routing and for `role` in the manifest."""
    name = os.path.basename(str(path)).lower()
    ext = os.path.splitext(name)[1]
    if name in META_NAMES:
        return "metadata"
    if ext in TABLE_EXT:
        return "table"
    if ext in PDF_EXT:
        return "pdf"
    if ext in IMAGE_EXT:
        return "image"
    if ext in DOC_EXT:
        return "office"
    if ext in TEXT_EXT:
        return "text"
    return "binary"


SKIP_DIRS = {".git", ".svn", ".hg", "node_modules", "__pycache__", ".venv",
             "venv", ".idea", ".vscode", ".mypy_cache", ".pytest_cache"}


def iter_files(root):
    """Deterministic recursive file walk, skipping VCS/cache directories."""
    root = str(root)
    if os.path.isfile(root):
        yield root
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            yield os.path.join(dirpath, name)


def utf8_text_files(root):
    """Yield (abs_path, rel_path) for files that decode as plausible text."""
    for path in iter_files(root):
        kind = detect_kind(path)
        if kind in ("text", "table", "metadata"):
            yield path


# --------------------------------------------------------------------------
# Units / geometry
# --------------------------------------------------------------------------
MM_PER_INCH = 25.4
PT_PER_INCH = 72.0


def mm_to_pt(value) -> float:
    return float(value) * PT_PER_INCH / MM_PER_INCH


def mm_to_px(value, dpi) -> float:
    return float(value) * float(dpi) / MM_PER_INCH


def pt_to_mm(value) -> float:
    return float(value) * MM_PER_INCH / PT_PER_INCH


def xml_escape(text) -> str:
    s = "" if text is None else str(text)
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


# --------------------------------------------------------------------------
# Optional dependency probes (result recorded, never assumed)
# --------------------------------------------------------------------------
def have(module: str) -> bool:
    try:
        __import__(module)
        return True
    except Exception:  # noqa: BLE001 - any import failure means "not usable"
        return False


def module_version(module: str):
    try:
        mod = __import__(module)
        return getattr(mod, "__version__", "unknown")
    except Exception:  # noqa: BLE001
        return None


def tool_version(argv, timeout: int = 20):
    """Best-effort version string for an external tool; None when unusable."""
    import subprocess
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           shell=False)
    except (OSError, ValueError, Exception):  # noqa: BLE001
        return None
    if r.returncode != 0:
        return None
    out = (r.stdout or "").strip() or (r.stderr or "").strip()
    return out.splitlines()[0][:200] if out else "ok"


def which(name: str):
    return shutil.which(name)


def make_temp_dir(prefix: str, parent=None):
    """Temp dir under `parent` (default: platform temp) usable in sandboxes."""
    base = parent if parent else tempfile.gettempdir()
    os.makedirs(base, exist_ok=True)
    for i in range(1000):
        cand = os.path.join(base, "%s-%d" % (prefix, i))
        if not os.path.exists(cand):
            os.makedirs(cand)
            return cand
    die("cannot allocate a temp directory under %s" % base, ENV_BLOCKED)
