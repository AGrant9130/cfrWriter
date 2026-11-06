"""User settings, stored as JSON in the per-user app-data folder."""

from __future__ import annotations

import base64
import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .paths import app_data_dir, default_output_dir

SETTINGS_FILE = "settings.json"
LOGO_FILE = "logo.png"
BUNDLE_KEY = "cfrwriter_settings"

DEFAULT_DISCLAIMER = "Reform capacitors if line power not applied within 1yr from above date"
DATE_FORMATS = ("MM/DD/YYYY", "M/D/YYYY", "DD/MM/YYYY", "YYYY-MM-DD")
PAPER_SIZES = ("Letter", "A4")


@dataclass
class InfoField:
    value: str = ""
    show: bool = True


@dataclass
class Contact:
    name: str = ""
    phone: str = ""
    email: str = ""
    role: str = ""
    include: bool = True


@dataclass
class Settings:
    # User info
    user_name: InfoField = field(default_factory=InfoField)
    user_phone: InfoField = field(default_factory=InfoField)
    user_email: InfoField = field(default_factory=InfoField)
    default_performed_by: str = ""          # falls back to user_name

    # Company info
    company_name: InfoField = field(default_factory=InfoField)
    company_phone: InfoField = field(default_factory=InfoField)
    company_website: InfoField = field(default_factory=InfoField)
    company_address: InfoField = field(default_factory=InfoField)
    company_hours: InfoField = field(default_factory=InfoField)

    # Technical support
    support_general: InfoField = field(default_factory=InfoField)
    contacts: list[Contact] = field(default_factory=list)

    # Report appearance
    logo_file: str = ""                     # file in app-data folder; "" = bundled default
    accent_override: str = ""               # "#rrggbb"; "" = pick from logo
    disclaimer: InfoField = field(default_factory=lambda: InfoField(DEFAULT_DISCLAIMER, True))
    footer_note: InfoField = field(default_factory=InfoField)
    date_format: str = "MM/DD/YYYY"
    paper: str = "Letter"

    # Output
    output_dir: str = field(default_factory=lambda: str(default_output_dir()))
    subfolder_pattern: str = "{customer}/{date}"
    filename_pattern: str = "{customer}_{date}_{serial}"
    print_immediately: bool = False
    last_printer: str = ""
    last_log_dir: str = ""
    first_run_done: bool = False

    # -- helpers ---------------------------------------------------------
    def performed_by_default(self) -> str:
        return self.default_performed_by.strip() or self.user_name.value.strip()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        """Tolerant load: unknown keys are ignored, wrong types fall back to defaults."""
        s = cls()
        if not isinstance(data, dict):
            return s
        for f in fields(cls):
            if f.name not in data:
                continue
            raw, default = data[f.name], getattr(s, f.name)
            if isinstance(default, InfoField) and isinstance(raw, dict):
                setattr(s, f.name, InfoField(str(raw.get("value", default.value)),
                                             bool(raw.get("show", default.show))))
            elif f.name == "contacts" and isinstance(raw, list):
                contacts = []
                for c in raw:
                    if isinstance(c, dict):
                        contacts.append(Contact(
                            name=str(c.get("name", "")), phone=str(c.get("phone", "")),
                            email=str(c.get("email", "")), role=str(c.get("role", "")),
                            include=bool(c.get("include", True))))
                s.contacts = contacts
            elif isinstance(default, (str, bool)) and isinstance(raw, type(default)):
                setattr(s, f.name, raw)
        if s.date_format not in DATE_FORMATS:
            s.date_format = DATE_FORMATS[0]
        if s.paper not in PAPER_SIZES:
            s.paper = PAPER_SIZES[0]
        return s


def settings_path() -> Path:
    return app_data_dir() / SETTINGS_FILE


def load_settings() -> Settings:
    try:
        return Settings.from_dict(json.loads(settings_path().read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return Settings()


def save_settings(settings: Settings) -> None:
    path = settings_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings.to_dict(), indent=2), encoding="utf-8")
    os.replace(tmp, path)


# -- import / export bundle (settings + logo in one file) ------------------

def export_bundle(settings: Settings, logo_png: bytes | None, path: str | Path) -> None:
    bundle: dict = {BUNDLE_KEY: 1, "settings": settings.to_dict()}
    if logo_png:
        bundle["logo_png_base64"] = base64.b64encode(logo_png).decode("ascii")
    Path(path).write_text(json.dumps(bundle, indent=2), encoding="utf-8")


def import_bundle(path: str | Path) -> tuple[Settings, bytes | None]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or BUNDLE_KEY not in data:
        raise ValueError("This is not a cfrWriter settings file.")
    logo = data.get("logo_png_base64")
    return Settings.from_dict(data.get("settings", {})), (base64.b64decode(logo) if logo else None)
