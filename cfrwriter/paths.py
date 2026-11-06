"""Locations of bundled resources and per-user data."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_NAME


def resource_path(*parts: str) -> Path:
    """Path to a bundled resource, in both source and PyInstaller layouts."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "cfrwriter" / "resources"
    else:
        base = Path(__file__).parent / "resources"
    return base.joinpath(*parts)


def app_data_dir() -> Path:
    """Per-user settings folder (%APPDATA%\\cfrWriter on Windows). Created on demand."""
    override = os.environ.get("CFRWRITER_HOME")
    if override:
        path = Path(override)
    elif os.name == "nt":
        path = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / APP_NAME
    else:
        path = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_output_dir() -> Path:
    return Path.home() / "Documents" / "Forming Reports"
