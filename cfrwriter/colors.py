"""Picking a report accent color from the logo."""

from __future__ import annotations

import colorsys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage

DEFAULT_ACCENT = QColor("#1f4e79")


def dominant_color(image: QImage) -> QColor | None:
    """Most prominent *colorful* hue in the image.

    Transparent, near-white, near-black and grey pixels are ignored, so a logo on a
    white background still yields its brand color. Returns None if nothing qualifies.
    """
    if image.isNull():
        return None
    small = image.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio)
    bins = 24
    weight = [0.0] * bins
    sums = [[0.0, 0.0, 0.0] for _ in range(bins)]
    for y in range(small.height()):
        for x in range(small.width()):
            c = small.pixelColor(x, y)
            if c.alpha() < 160:
                continue
            h, s, v = colorsys.rgb_to_hsv(c.redF(), c.greenF(), c.blueF())
            if s < 0.30 or v < 0.20 or (v > 0.97 and s < 0.5):
                continue
            b = min(int(h * bins), bins - 1)
            weight[b] += s
            for i, ch in enumerate((c.redF(), c.greenF(), c.blueF())):
                sums[b][i] += ch * s
    best = max(range(bins), key=lambda i: weight[i])
    if weight[best] <= 0:
        return None
    r, g, b = (ch / weight[best] for ch in sums[best])
    return QColor.fromRgbF(r, g, b)


def _luminance(c: QColor) -> float:
    def lin(v: float) -> float:
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(c.redF()) + 0.7152 * lin(c.greenF()) + 0.0722 * lin(c.blueF())


def contrast_with_white(c: QColor) -> float:
    return 1.05 / (_luminance(c) + 0.05)


def readable_on_white(c: QColor, minimum: float = 4.5) -> QColor:
    """Darken a color until text in it is comfortably legible on white paper."""
    out = QColor(c)
    for _ in range(40):
        if contrast_with_white(out) >= minimum:
            break
        out = out.darker(108)
    return out
