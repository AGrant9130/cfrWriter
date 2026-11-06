"""Bundled fonts and the logo."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QFontDatabase, QImage

from .paths import app_data_dir, resource_path
from .settings import LOGO_FILE, Settings

MAX_LOGO_WIDTH = 900   # keeps PDFs small; far more than print needs at ~2in wide


def load_fonts() -> str:
    """Register the bundled Inter fonts and return the family name to use."""
    family = "Inter"
    for ttf in sorted(resource_path("fonts").glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(ttf))
    return family


def _shrink(image: QImage) -> QImage:
    if image.width() > MAX_LOGO_WIDTH:
        image = image.scaledToWidth(MAX_LOGO_WIDTH, Qt.TransformationMode.SmoothTransformation)
    return image


def default_logo() -> QImage:
    return _shrink(QImage(str(resource_path("default_logo.png"))))


def load_logo(settings: Settings) -> QImage:
    """The user's logo if they chose one and it is readable, else the bundled default."""
    if settings.logo_file:
        img = QImage(str(app_data_dir() / settings.logo_file))
        if not img.isNull():
            return _shrink(img)
    return default_logo()


def save_logo(image: QImage) -> str:
    """Store a user-chosen logo in the app-data folder; returns the file name to remember."""
    if not _shrink(image).save(str(app_data_dir() / LOGO_FILE), "PNG"):
        raise OSError("Could not save the logo.")
    return LOGO_FILE


def image_to_png_bytes(image: QImage) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    _shrink(image).save(buf, "PNG")
    return bytes(data.data())


def image_from_png_bytes(data: bytes) -> QImage:
    img = QImage()
    img.loadFromData(data)
    return img


def remove_user_logo() -> None:
    try:
        Path(app_data_dir() / LOGO_FILE).unlink()
    except OSError:
        pass
