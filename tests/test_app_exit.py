"""The real app must exit cleanly.

A bug once let every test pass while the application crashed on exit (the main window was
destroyed after the QApplication). The crash was intermittent, so this repeats the launch.
"""

import os
import subprocess
import sys
import textwrap

import pytest

from conftest import ROOT

LAUNCH = textwrap.dedent("""
    import sys
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    real_exec = QApplication.exec

    def exec_then_quit(*args):
        QTimer.singleShot(400, QApplication.quit)     # let the window and first-run logic start
        return real_exec(*args)

    QApplication.exec = staticmethod(exec_then_quit)
    sys.path.insert(0, {root!r})
    from cfrwriter.app import main
    sys.exit(main())
""")


@pytest.mark.parametrize("first_run_done", [True, False], ids=["returning-user", "first-run"])
def test_app_starts_and_exits_cleanly(tmp_path, first_run_done):
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "CFRWRITER_HOME": str(tmp_path / "appdata")}
    if first_run_done:
        from cfrwriter import settings as S
        (tmp_path / "appdata").mkdir()
        (tmp_path / "appdata" / S.SETTINGS_FILE).write_text('{"first_run_done": true}')
    for attempt in range(3):
        result = subprocess.run([sys.executable, "-c", LAUNCH.format(root=str(ROOT))],
                                env=env, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, (attempt, result.returncode, result.stderr[-500:])
