# cfrWriter

Turns a Bonitron capacitor-forming log (.csv) into a customer-ready PDF report: pick the run,
enter part and serial numbers, then save and print.

## Run from source

```
python -m venv .venv
.venv/bin/pip install -r requirements.txt        # Windows: .venv\Scripts\pip
.venv/bin/python main.py                          # Windows: .venv\Scripts\python main.py
.venv/bin/python -m pytest                        # tests
```

## Build the Windows app (one-folder)

On a Windows PC with Python 3.10+, double-click or run `build.bat`. The result is
`dist\cfrWriter\cfrWriter.exe`; zip the whole `dist\cfrWriter` folder to share it.
Nothing is written to the registry or the install folder. Settings live in
`%APPDATA%\cfrWriter\settings.json` (plus `logo.png` if a custom logo is chosen).

## Layout

| Path | Purpose |
|---|---|
| `cfrwriter/logdata.py` | Parse the Bonitron CSV (aborted runs dropped), find the newest CSV on a USB drive |
| `cfrwriter/settings.py` | Settings model, JSON load/save, import/export bundle |
| `cfrwriter/report.py` | Report layout. One drawing routine serves the PDF, the printer and the preview |
| `cfrwriter/colors.py` | Accent color picked from the logo |
| `cfrwriter/formatting.py` | Dates, safe file names and folders (never overwrites) |
| `cfrwriter/ui/` | Main window and settings dialog (PySide6) |
| `cfrwriter/resources/` | Default logo and the bundled Inter font (SIL Open Font License) |
| `tests/` | pytest suite (runs headless) |

## Continuous build

`.github/workflows/build.yml` runs the tests and builds the Windows one-folder app on GitHub's
Windows runners for every push to `main` and every pull request. It starts the built app as a
smoke test, reports the folder size in the run summary, and uploads `cfrWriter-windows.zip`
as a downloadable artifact. You can also start it by hand from the Actions tab.

## License

cfrWriter is free software under the **GNU General Public License v3.0 or later** (see
[LICENSE](LICENSE)). You may use, study, share and modify it, and you may sell copies, but anyone
who distributes it, modified or not, must provide the source under the same license.

Copyright (C) 2026 Aaron Grant

Bundled components keep their own licenses: see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
The Inter font's license is in `cfrwriter/resources/fonts/OFL.txt`. The bundled logo is a generic
placeholder; replace it with your own under Settings.

## Notes

- Time columns in the log are labelled seconds but are minutes; the report treats them as minutes.
- The report font is Inter, bundled with the app, so output looks the same on every PC.
