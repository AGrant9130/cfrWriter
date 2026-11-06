# PyInstaller spec: one-folder Windows build.   Build with:  pyinstaller --noconfirm cfrWriter.spec
# Output: dist/cfrWriter/cfrWriter.exe  (zip the whole dist/cfrWriter folder to distribute)
import re

# Only QtCore/QtGui/QtWidgets/QtPrintSupport are used. Excluding the rest keeps the folder small.
EXCLUDES = [
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuickControls2",
    "PySide6.QtNetwork", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtXml", "PySide6.QtSvg",
    "PySide6.QtSvgWidgets", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtPdf",
    "PySide6.QtPdfWidgets", "PySide6.QtDBus", "PySide6.QtConcurrent", "PySide6.QtDesigner",
    "PySide6.QtHelp", "PySide6.QtUiTools", "PySide6.QtWebChannel", "PySide6.QtWebSockets",
    "tkinter", "unittest", "pydoc", "test", "sqlite3", "pytest",
]

a = Analysis(
    ["main.py"],
    pathex=["."],
    datas=[("cfrwriter/resources", "cfrwriter/resources"), ("LICENSE", "."), ("THIRD_PARTY_NOTICES.md", ".")],
    excludes=EXCLUDES,
    noarchive=False,
)

# Drop Qt pieces this app never uses (software OpenGL, DirectX compiler, translations, unused
# image-format and icon plugins, and the SVG/PDF libraries only those plugins need). Anything
# removed that turns out to be needed shows up as a startup failure in the CI smoke test.
_DROP = re.compile(
    r"opengl32sw|d3dcompiler_\d+|/translations/"
    r"|imageformats/(lib)?q(gif|icns|ico|svg|tga|tiff|wbmp|webp|pdf)"
    r"|/iconengines/"
    r"|(lib)?qt6(svg|pdf)\.",
    re.IGNORECASE,
)


def _keep(entry):
    return not _DROP.search(entry[0].replace("\\", "/"))


a.binaries = [e for e in a.binaries if _keep(e)]
a.datas = [e for e in a.datas if _keep(e)]

pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="cfrWriter",
    console=False,          # no terminal window
    upx=False,              # UPX-packed binaries trip antivirus more often
)
coll = COLLECT(exe, a.binaries, a.datas, name="cfrWriter", upx=False)
