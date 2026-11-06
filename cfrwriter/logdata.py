"""Reading Bonitron CSV exports.

The Bonitron exports everything in its memory, newest first, as::

    Year, Month, Day, Hour, Minute, Second, Type, Result (uF), Volt Final (V),
    Volt Step (V), Time Final (s), Time Step (s), Current (mA)

The time columns are labelled seconds but are minutes (confirmed by the user).
Aborted runs have ``Abort`` in the result column and are ignored.
"""

from __future__ import annotations

import csv
import io
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

REQUIRED_COLUMNS = (
    "year", "month", "day", "hour", "minute", "second", "type",
    "result", "volt final", "volt step", "time final", "time step", "current",
)


class LogFormatError(ValueError):
    """The file is not a Bonitron export we understand."""


@dataclass(frozen=True)
class LogEntry:
    when: datetime
    kind: str            # "Profile" or "Basic"
    capacitance: float   # microfarads
    final_v: int
    step_v: int
    final_min: int
    step_min: int
    current_ma: int

    @property
    def capacitance_text(self) -> str:
        c = self.capacitance
        return str(int(c)) if float(c).is_integer() else f"{c:g}"

    def settings_key(self) -> tuple:
        """Entries sharing a key were formed with identical settings."""
        return (self.kind.lower(), self.final_v, self.step_v,
                self.final_min, self.step_min, self.current_ma)


@dataclass
class ParsedLog:
    entries: list[LogEntry]   # newest first, aborted/invalid runs removed
    skipped: int              # aborted or unreadable rows


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _column_of(header: list[str], name: str) -> int:
    for i, h in enumerate(header):
        if h.strip().lower().startswith(name):
            return i
    raise LogFormatError(f"Column '{name}' not found. Is this a Bonitron export?")


def _number(text: str) -> float:
    return float(text.strip())


def parse_log_text(text: str) -> ParsedLog:
    rows = [r for r in csv.reader(io.StringIO(text), skipinitialspace=True) if any(c.strip() for c in r)]
    if not rows:
        raise LogFormatError("The file is empty.")
    header = rows[0]
    idx = {name: _column_of(header, name) for name in REQUIRED_COLUMNS}

    entries: list[LogEntry] = []
    skipped = 0
    for row in rows[1:]:
        try:
            if len(row) <= max(idx.values()):
                raise ValueError("short row")
            result = row[idx["result"]].strip()
            if not result or result.lower().startswith("abort"):
                skipped += 1
                continue
            when = datetime(*(int(_number(row[idx[k]])) for k in
                              ("year", "month", "day", "hour", "minute", "second")))
            entries.append(LogEntry(
                when=when,
                kind=row[idx["type"]].strip().title(),
                capacitance=_number(result),
                final_v=int(_number(row[idx["volt final"]])),
                step_v=int(_number(row[idx["volt step"]])),
                final_min=int(_number(row[idx["time final"]])),
                step_min=int(_number(row[idx["time step"]])),
                current_ma=int(_number(row[idx["current"]])),
            ))
        except (ValueError, IndexError):
            skipped += 1
    entries.sort(key=lambda e: e.when, reverse=True)
    return ParsedLog(entries, skipped)


def parse_log(path: str | Path) -> ParsedLog:
    return parse_log_text(_decode(Path(path).read_bytes()))


# --- finding the export on a USB drive ---------------------------------------

def removable_roots() -> list[Path]:
    """Mount points of removable drives (USB sticks)."""
    roots: list[Path] = []
    if os.name == "nt":
        import ctypes
        DRIVE_REMOVABLE = 2
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()  # type: ignore[attr-defined]
        for i in range(26):
            if bitmask & (1 << i):
                root = f"{chr(65 + i)}:\\"
                if ctypes.windll.kernel32.GetDriveTypeW(root) == DRIVE_REMOVABLE:  # type: ignore[attr-defined]
                    roots.append(Path(root))
    else:
        import getpass
        user = getpass.getuser()
        for base in (Path("/run/media") / user, Path("/media") / user, Path("/media"), Path("/mnt")):
            if base.is_dir():
                roots.extend(p for p in base.iterdir() if p.is_dir())
    return roots


def find_latest_csv(roots: list[Path], max_depth: int = 2) -> Path | None:
    """Newest-modified .csv under the given roots (shallow search)."""
    best: tuple[float, Path] | None = None
    for root in roots:
        stack = [(root, 0)]
        while stack:
            folder, depth = stack.pop()
            try:
                children = list(folder.iterdir())
            except OSError:
                continue
            for child in children:
                try:
                    if child.is_dir():
                        if depth < max_depth and not child.name.startswith((".", "$")):
                            stack.append((child, depth + 1))
                    elif child.suffix.lower() == ".csv":
                        mtime = child.stat().st_mtime
                        if best is None or mtime > best[0]:
                            best = (mtime, child)
                except OSError:
                    continue
    return best[1] if best else None
