REM SPDX-FileCopyrightText: 2026 Anna Caellas-Camprubi
REM SPDX-License-Identifier: EUPL-1.2
@echo off
setlocal
pushd "%~dp0"

echo ==========================================
echo Data Footprints - startup
echo ==========================================
echo.

if not exist "app.py" (
    echo ERROR: app.py was not found in:
    echo %CD%
    echo.
    echo Put this run_app.bat in the main application folder.
    goto :error
)

if not exist "requirements.txt" (
    echo ERROR: requirements.txt was not found in:
    echo %CD%
    goto :error
)

if not exist ".venv\Scripts\python.exe" (
    echo Python environment .venv was not found.
    echo Creating it now...
    echo.

    where py >nul 2>&1
    if not errorlevel 1 (
        py -m venv .venv
    ) else (
        where python >nul 2>&1
        if errorlevel 1 (
            echo ERROR: Python was not found.
            echo Install Python and enable "Add Python to PATH".
            goto :error
        )
        python -m venv .venv
    )

    if errorlevel 1 (
        echo ERROR: The Python environment could not be created.
        goto :error
    )

    echo.
    echo Installing dependencies...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    if errorlevel 1 goto :error

    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :error
)

echo.
echo Starting Data Footprints...
echo The browser should open at http://localhost:8501
echo To stop the application, return to this window and press Ctrl+C.
echo.

".venv\Scripts\python.exe" -m streamlit run app.py

if errorlevel 1 goto :error

popd
endlocal
exit /b 0

:error
echo.
echo ==========================================
echo Startup failed. Read the message above.
echo ==========================================
pause
popd
endlocal
exit /b 1
