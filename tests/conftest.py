import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

EXAMPLE_LOG = ROOT / "tests" / "data" / "example_log.csv"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Never touch the real settings folder."""
    monkeypatch.setenv("CFRWRITER_HOME", str(tmp_path / "appdata"))
    return tmp_path


@pytest.fixture(scope="session")
def qapp():
    import gc

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from cfrwriter import assets
    assets.load_fonts()
    yield app
    # A test that copied something (the share button) leaves a QMimeData on the system clipboard; on
    # Windows that OLE object outliving the QApplication also crashes the process at exit.
    from PySide6.QtGui import QGuiApplication
    QGuiApplication.clipboard().clear()
    # Destroy every window while the QApplication still exists. If widgets outlive it, Python
    # tears them down afterwards and the process crashes at exit (a non-zero exit code that
    # fails CI even though every test passed).
    for widget in app.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    app.processEvents()
    gc.collect()
