@echo off
REM Builds the one-folder Windows app. Run from the project folder on a Windows PC with Python 3.10+.
python -m venv .venv || exit /b 1
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip || exit /b 1
python -m pip install -r requirements.txt || exit /b 1
python -m pytest -q || exit /b 1
pyinstaller --noconfirm cfrWriter.spec || exit /b 1
echo.
echo Built: dist\cfrWriter\cfrWriter.exe   (zip the whole dist\cfrWriter folder to share it)
