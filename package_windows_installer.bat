@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT_DIR=%~dp0"
cd /d "%ROOT_DIR%"

set "INNO_SCRIPT=installer\StreamCap.iss"
set "BUILD_EXE=dist\main_qt.dist\StreamCapEvo.exe"
set "STREAMCAP_SKIP_BUILD_PAUSE=1"
set "STREAMCAPEVO_SKIP_BUILD_PAUSE=1"
set "RELEASE_MODE=0"
set "BUMP_MODE="
set "BUMP_VALUE="
set "RELEASE_VERSION="
set "RELEASE_COMMIT_CREATED=0"

:parse_args
if "%~1"=="" goto :args_done
if /I "%~1"=="--release" (
    set "RELEASE_MODE=1"
    shift
    goto :parse_args
)
if /I "%~1"=="--patch" (
    set "RELEASE_MODE=1"
    set "BUMP_MODE=patch"
    shift
    goto :parse_args
)
if /I "%~1"=="--set" (
    if "%~2"=="" (
        echo [ERROR] --set requires a version like X.Y.Z
        exit /b 1
    )
    set "RELEASE_MODE=1"
    set "BUMP_MODE=set"
    set "BUMP_VALUE=%~2"
    shift
    shift
    goto :parse_args
)

echo [ERROR] Unknown argument: %~1
echo Usage:
echo   package_windows_installer.bat
echo   package_windows_installer.bat --release
echo   package_windows_installer.bat --patch
echo   package_windows_installer.bat --set X.Y.Z
exit /b 1

:args_done

if "%RELEASE_MODE%"=="1" (
    if not exist "venv\Scripts\python.exe" (
        echo [ERROR] Virtual environment not found in "venv".
        exit /b 1
    )

    if not exist "scripts\bump_version.py" (
        echo [ERROR] Version helper not found at "scripts\bump_version.py".
        exit /b 1
    )

    echo ====================================================
    echo Release mode: preparing version and Git metadata
    echo ====================================================

    if defined BUMP_MODE (
        if /I "%BUMP_MODE%"=="patch" (
            echo [release 1/6] Bumping patch version...
            "venv\Scripts\python.exe" "scripts\bump_version.py" --patch
        ) else (
            echo [release 1/6] Setting version to %BUMP_VALUE%...
            "venv\Scripts\python.exe" "scripts\bump_version.py" --set %BUMP_VALUE%
        )
        if errorlevel 1 exit /b 1
    ) else (
        echo [release 1/6] Validating current version metadata...
        "venv\Scripts\python.exe" "scripts\bump_version.py" --check
        if errorlevel 1 exit /b 1
    )

    for /f "delims=" %%V in ('venv\Scripts\python.exe scripts\bump_version.py --current') do set "RELEASE_VERSION=%%V"
    if not defined RELEASE_VERSION (
        echo [ERROR] Could not read application version.
        exit /b 1
    )

    git diff --quiet -- pyproject.toml config/version.json
    if errorlevel 1 (
        echo [release 2/6] Creating release version commit...
        git add pyproject.toml config/version.json
        git commit -m "chore(release): bump version to !RELEASE_VERSION!"
        if errorlevel 1 exit /b 1
        set "RELEASE_COMMIT_CREATED=1"
    ) else (
        echo [release 2/6] Version files unchanged; skipping release bump commit.
    )

    git rev-parse -q --verify "refs/tags/v!RELEASE_VERSION!" >nul 2>nul
    if not errorlevel 1 (
        echo [ERROR] Tag v!RELEASE_VERSION! already exists.
        exit /b 1
    )
)

echo ====================================================
echo Building StreamCapEvo and packaging Windows installer
echo ====================================================

echo [1/3] Running Nuitka build...
call "%ROOT_DIR%build_qt_nuitka.bat"
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Nuitka build failed. Installer will not be compiled.
    exit /b 1
)

if not exist "%BUILD_EXE%" (
    echo.
    echo [ERROR] Expected build output not found: %BUILD_EXE%
    exit /b 1
)

echo.
echo [2/3] Locating Inno Setup compiler...
if defined ISCC_EXE (
    if exist "%ISCC_EXE%" goto :compile_installer
    echo [ERROR] ISCC_EXE is set but the file does not exist: %ISCC_EXE%
    exit /b 1
)

where ISCC.exe >nul 2>nul
if %ERRORLEVEL% equ 0 (
    set "ISCC_EXE=ISCC.exe"
    goto :compile_installer
)

if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" (
    set "ISCC_EXE=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
    goto :compile_installer
)

if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" (
    set "ISCC_EXE=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
    goto :compile_installer
)

if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" (
    set "ISCC_EXE=%ProgramFiles%\Inno Setup 6\ISCC.exe"
    goto :compile_installer
)

echo [ERROR] ISCC.exe was not found.
echo Install Inno Setup 6 or set ISCC_EXE to the full ISCC.exe path.
echo Example:
echo   set "ISCC_EXE=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
exit /b 1

:compile_installer
echo Found Inno Setup compiler: %ISCC_EXE%

if not exist "%INNO_SCRIPT%" (
    echo [ERROR] Installer script not found: %INNO_SCRIPT%
    exit /b 1
)

echo.
echo [3/3] Compiling installer...
"%ISCC_EXE%" "%INNO_SCRIPT%"
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Installer compilation failed.
    exit /b 1
)

echo.
echo ====================================================
echo Windows installer created successfully.
echo Output directory: dist\installer
echo ====================================================

if "%RELEASE_MODE%"=="1" (
    echo.
    echo [release 6/6] Creating git tag v!RELEASE_VERSION!...
    git tag "v!RELEASE_VERSION!"
    if errorlevel 1 (
        echo [ERROR] Failed to create git tag v!RELEASE_VERSION!.
        exit /b 1
    )

    echo.
    echo Release prepared successfully.
    if "%RELEASE_COMMIT_CREATED%"=="1" (
        echo Commit created: chore^(release^): bump version to !RELEASE_VERSION!
    )
    echo Tag created: v!RELEASE_VERSION!
)

exit /b 0
