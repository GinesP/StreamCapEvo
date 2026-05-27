# Code Review Rules

## General
- Keep changes minimal and focused.
- Prefer shared utilities over duplicated logic.
- Preserve existing project structure and conventions.
- Update translations when UI labels change.
- Do not run release builds unless explicitly requested.

## Common Commands
- Qt app entry point: `python main_qt.py`.
- CI currently declares lint as `ruff check main.py app --config .ruff.toml`.
- TODO: Verify whether CI lint should target `main_qt.py`; this checkout does not include `main.py`.
- Test command used by CI: `python -m unittest discover`.
- Version metadata check: `.\venv\Scripts\python.exe scripts\bump_version.py --check`.
- Version helpers: `.\venv\Scripts\python.exe scripts\bump_version.py --current`, `--patch`, or `--set X.Y.Z`.
- Windows packaging entry point: `.\package_windows_installer.bat` (release variants: `--release`, `--patch`, `--set X.Y.Z`).
- Manual Windows installer compile: `ISCC.exe .\installer\StreamCap.iss`.
- Predictor metrics report: `python scripts/predictor_metrics_report.py` (add `--human` for the readable summary or `--metrics-file <path>` for a backup/legacy file).

## Release Workflow
- `pyproject.toml` is the technical version source of truth.
- Keep `config/version.json` synchronized with `pyproject.toml` via `scripts/bump_version.py`.
- The Windows Qt release build uses `build_qt_nuitka.bat`, which validates version metadata before compiling `main_qt.py`.
- `package_windows_installer.bat` is the current packaging entry point; in release mode it can validate/bump version metadata, create the release version commit, and create the git tag after a successful installer build.
- `package_windows_installer.bat` uses `ISCC.exe` from `PATH` when available, otherwise checks common Inno Setup 6 install paths or an explicit `ISCC_EXE` override.
- The build output is `dist\main_qt.dist\StreamCap.exe`; the Nuitka report is `dist\nuitka-report.xml`.
- The Windows installer output is `dist\installer`.

## Python
- Follow existing style and naming conventions.
- Avoid unnecessary comments.
- Reuse shared filters and state helpers for UI status logic.

## Qt UI
- Keep labels localized through `locales/*.json`.
- Prefer consistent status semantics across Home and Recordings views.
