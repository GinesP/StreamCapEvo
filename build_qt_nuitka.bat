@echo off
setlocal

if not defined STREAMCAPEVO_SKIP_BUILD_PAUSE set "STREAMCAPEVO_SKIP_BUILD_PAUSE=%STREAMCAP_SKIP_BUILD_PAUSE%"

echo ====================================================
echo Building StreamCapEvo (Qt) with Nuitka
echo ====================================================

if not exist "venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found in "venv".
    if not "%STREAMCAPEVO_SKIP_BUILD_PAUSE%"=="1" pause
    exit /b 1
)

if not exist "scripts\bump_version.py" (
    echo [ERROR] Version helper not found at "scripts\bump_version.py".
    if not "%STREAMCAPEVO_SKIP_BUILD_PAUSE%"=="1" pause
    exit /b 1
)

echo [1/3] Validating version metadata...
"venv\Scripts\python.exe" "scripts\bump_version.py" --check
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Version metadata validation failed.
    if not "%STREAMCAPEVO_SKIP_BUILD_PAUSE%"=="1" pause
    exit /b 1
)

for /f "delims=" %%V in ('venv\Scripts\python.exe scripts\bump_version.py --current') do set "APP_VERSION=%%V"
if not defined APP_VERSION (
    echo [ERROR] Could not read application version.
    if not "%STREAMCAPEVO_SKIP_BUILD_PAUSE%"=="1" pause
    exit /b 1
)

echo Building StreamCapEvo version %APP_VERSION%

echo [2/3] Cleaning old build files...
if exist "dist\main_qt.build" rd /s /q "dist\main_qt.build"
if exist "dist\main_qt.dist" rd /s /q "dist\main_qt.dist"

echo [3/3] Compiling with Nuitka...
"venv\Scripts\python.exe" -m nuitka ^
    --standalone ^
    --msvc=latest ^
    --enable-plugin=pyside6 ^
    --windows-console-mode=disable ^
    --include-package=app.qt ^
    --include-module=app.qt_app_manager ^
    --include-module=app.event_bus ^
    --include-package=app.core ^
    --include-package=app.initialization ^
    --include-package=app.scripts ^
    --include-package=app.utils ^
    --include-package=app.models ^
    --include-package=streamget ^
    --include-qt-plugins=multimedia ^
    --windows-icon-from-ico="assets/icon.ico" ^
    --include-data-dir="assets=assets" ^
    --include-data-dir="locales=locales" ^
    --include-data-files="config\default_settings.json=config\default_settings.json" ^
    --include-data-files="config\language.json=config\language.json" ^
    --include-data-files="config\version.json=config\version.json" ^
    --output-dir="dist" ^
    --output-filename="StreamCapEvo.exe" ^
    --report="dist\nuitka-report.xml" ^
    --report-diffable ^
    --product-name="StreamCapEvo" ^
    --file-version="%APP_VERSION%" ^
    --product-version="%APP_VERSION%" ^
    --company-name="StreamCapEvo" ^
    main_qt.py

if %ERRORLEVEL% equ 0 (
    echo ====================================================
    echo Build Successful!
echo Executable located at: dist\main_qt.dist\StreamCapEvo.exe
    echo Nuitka report located at: dist\nuitka-report.xml
    echo ====================================================
    if not "%STREAMCAPEVO_SKIP_BUILD_PAUSE%"=="1" pause
    exit /b 0
) else (
    echo.
    echo [ERROR] Build failed. Check the Nuitka logs above.
    if not "%STREAMCAPEVO_SKIP_BUILD_PAUSE%"=="1" pause
    exit /b 1
)
