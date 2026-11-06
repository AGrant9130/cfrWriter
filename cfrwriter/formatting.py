"""Text formatting: dates, durations, and safe file names."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
_TOKEN = re.compile(r"\{(\w+)\}")


def format_date(d: date, style: str) -> str:
    return {
        "MM/DD/YYYY": f"{d.month:02d}/{d.day:02d}/{d.year}",
        "M/D/YYYY": f"{d.month}/{d.day}/{d.year}",
        "DD/MM/YYYY": f"{d.day:02d}/{d.month:02d}/{d.year}",
        "YYYY-MM-DD": d.isoformat(),
    }.get(style, d.isoformat())


def minutes_text(n: int) -> str:
    return f"{n} Minute" if n == 1 else f"{n} Minutes"


def sanitize_component(text: str, fallback: str = "Unknown") -> str:
    """Make text safe as one Windows file or folder name."""
    text = _INVALID.sub("_", text).strip().rstrip(". ")
    text = re.sub(r"\s+", " ", text)[:80].rstrip(". ")
    if not text or text.lower().split(".")[0] in _RESERVED:
        return fallback
    return text


def fill_pattern(pattern: str, values: dict[str, str]) -> str:
    """Replace {tokens} with values; unknown tokens become empty."""
    return _TOKEN.sub(lambda m: values.get(m.group(1).lower(), ""), pattern)


def build_output_path(output_dir: str, subfolder_pattern: str, filename_pattern: str,
                      values: dict[str, str]) -> Path:
    """Folder/filename for a report. Never overwrites: adds ' (2)', ' (3)', ... instead."""
    path = Path(output_dir)
    values = {k: _INVALID.sub("_", v) for k, v in values.items()}   # a "/" in a name must not make a folder
    for part in fill_pattern(subfolder_pattern, values).replace("\\", "/").split("/"):
        if part.strip():
            path /= sanitize_component(part)
    name = sanitize_component(fill_pattern(filename_pattern, values), "report")
    candidate, n = path / f"{name}.pdf", 2
    while candidate.exists():
        candidate = path / f"{name} ({n}).pdf"
        n += 1
    return candidate
