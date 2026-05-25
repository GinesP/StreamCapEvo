## Exploration: Phase 2 Coexistence with Optional Original StreamCap Import

### Current State

StreamCapEvo currently shares ALL identity and data resources with the original StreamCap:

**Identity collisions (every level):**
- **AppUserModelID**: `streamcap.streamcap.app.1` (hardcoded in `main_qt.py` line 55) — both apps collapse into the same taskbar group
- **Executable name**: `StreamCap.exe` (`build_qt_nuitka.bat` line 67 and `installer/StreamCap.iss` line 3)
- **Installer AppId**: `{{8F9A3E6B-6E7D-4BC8-9F67-5A4B7F91F6C2}` — Windows treats both as the SAME installed application
- **Install directory**: `{localappdata}\Programs\StreamCap` (line 12 of `.iss`)
- **Start Menu group**: `StreamCap` (line 38 of `.iss`, `DefaultGroupName`)
- **Publisher/Company**: `StreamCap` (`MyAppPublisher` line 2 of `.iss`, `--company-name` line 73 of `build_qt_nuitka.bat`)
- **Application name**: `StreamCapEvo` in `QApplication.setApplicationName`/`setApplicationDisplayName` (main_qt.py lines 63-64), but actual `WINDOW_TITLE` in `MainWindow` is also `StreamCapEvo` (line 50 of main_window.py) — window title is differentiated but executable and installer are NOT

**Data directory collision:**
- `ConfigManager.get_default_user_data_path()` returns `%LOCALAPPDATA%\StreamCap` on Windows (line 76 of `config_manager.py`)
- ALL mutable state lives there: `user_settings.json`, `cookies.json`, `accounts.json`, `web_auth.json`, `recordings.db` (+ WAL/shm/journal), `recordings.json`, `recordings.json.bak`
- The `migrate_legacy_config()` method copies from a `config/` directory adjacent to the executable — this is a forward-migration from "unpackaged source" to "packaged user data", NOT designed for cross-app import
- Uninstall script in `.iss` (lines 44-66) prompts to delete `%LOCALAPPDATA%\StreamCap` — which would nuke BOTH apps' data if they share it

**Data structures that would need importing:**
1. `user_settings.json` — user preferences (language, theme, recording paths, etc.)
2. `cookies.json` — session cookies for web platform access
3. `accounts.json` — platform account credentials
4. `web_auth.json` — authentication tokens
5. `recordings.db` — SQLite database with all recording definitions (schema: `recordings(rec_id TEXT PRIMARY KEY, data TEXT)` where `data` is JSON-serialized `Recording` objects)
6. `predictor_metrics.db` — SQLite database for predictor metrics (lives in `config_path/predictor_metrics.db`)

**Environment override already exists:**
- `STREAMCAPEVO_USER_DATA_DIR` and `STREAMCAP_USER_DATA_DIR` env vars can redirect the user data path (line 69 of `config_manager.py`)
- This is a useful escape hatch for coexistence testing but must NOT be the primary solution — users should not need env vars for normal operation

### Affected Areas

- `main_qt.py` — AppUserModelID hardcoded to original StreamCap ID; app name strings
- `installer/StreamCap.iss` — ALL identity fields need separation (AppName, AppId, DefaultDirName, DefaultGroupName, AppPublisher, OutputBaseFilename, icons group)
- `build_qt_nuitka.bat` — `--output-filename`, `--product-name`, `--file-version`, `--company-name` all reference StreamCap not StreamCapEvo
- `app/core/config/config_manager.py` — `get_default_user_data_path()` returns `%LOCALAPPDATA%\StreamCap`; `migrate_legacy_config()` is the closest pattern to what we need for import but it's a COPY-IF-NOT-EXISTS migration, not a user-initiated import
- `app/qt/main_window.py` — `WINDOW_TITLE = "StreamCapEvo"` (already OK but verify consistency)
- `app/__init__.py` — `execute_dir` and `bundle_dir` path resolution (not directly affected but relevant for import source detection)
- `app/core/recording/record_manager.py` — loads recordings from config_manager; import would need to inject imported records
- `app/models/recording/recording_model.py` — data shape that must be compatible between old and new
- `app/utils/logger.py` — log file paths use `script_path/logs/` — collision potential but low risk since they're read-only per-session
- `package_windows_installer.bat` — references to `StreamCap.exe` build output, installer output naming
- `scripts/bump_version.py` — version metadata (not directly affected but identity names appear in version.json announcements)
- `NEW: app/core/data_import/` — new directory for import logic
- `NEW: app/qt/views/import_view.py` — new settings page or dialog for the import flow
- `NEW: tests/test_data_import.py` — strict TDD tests for import logic

### Approaches

1. **Full isolation — rename everything** — Change ALL identity references to `StreamCapEvo` and change `%LOCALAPPDATA%` directory to `StreamCapEvo`
   - Pros: Complete separation, no collisions, clean slate
   - Cons: Breaking change for existing Evo users if they have data in the old path; need to add a forward migration for Evo's own existing data; higher touch count
   - Effort: Medium (15-20 files changed, mostly mechanical)

2. **Minimal identity separation + optional import** — Change AppUserModelID, installer identity, and executable name only; keep `%LOCALAPPDATA%\StreamCap` as default data directory; add import dialog
   - Pros: Less disruptive, existing Evo data stays in place, simpler forward migration
   - Cons: Still shares data directory by default; `migrate_legacy_config()` already does in-place copy; import flow needs a SEPARATE data directory to target
   - Effort: Low-Medium

3. **Full separation + import both ways** — Change identity AND data directory to `%LOCALAPPDATA%\StreamCapEvo`; add migration for existing Evo data from old path; add optional import from original StreamCap
   - Pros: Complete clean break; the right long-term architecture; import flow is truly optional; natural upgrade path
   - Cons: Higher change volume; must design forward-migration for Evo's own data from old path to new path
   - Effort: High

4. **Hybrid: identity separation + data path separation + import** — Change ALL identity (AppUserModelID, installer, exe name) to `StreamCapEvo` AND change data directory to `%LOCALAPPDATA%\StreamCapEvo`; provide automatic forward-migration for existing Evo user data (copy from old `%LOCALAPPDATA%\StreamCap` if this is a first run of Evo 2.0); provide optional one-time import dialog for importing from the original StreamCap (detected by the presence of a non-Evo `recordings.db` in `%LOCALAPPDATA%\StreamCap`)
   - Pros: Clean architecture, no collisions, smooth upgrade for existing Evo users, true optional import
   - Cons: Need to distinguish "original StreamCap data" from "existing Evo 1.x data" in the shared directory; requires careful detection logic
   - Effort: High

### Recommendation

**Approach 4 (Hybrid with full separation and forward-migration)** is the right choice. Here's why:

- Approach 1 leaves existing Evo 1.x users stranded with no data migration path
- Approach 2 kicks the can down the road — you'll have to change the data directory eventually
- Approach 3 is essentially the same as approach 4 but without the automatic forward-migration for Evo's own existing data, which would be a poor UX
- Approach 4 handles ALL scenarios: clean install (no existing data), upgrade from Evo 1.x (forward-migration), and coexistence with original StreamCap (optional import)

The key insight: `%LOCALAPPDATA%\StreamCap` currently serves double-duty as both "Evo's data directory" AND "original StreamCap's data directory". We need to detect at startup which scenario we're in:

1. **Clean install** (no `%LOCALAPPDATA%\StreamCapEvo` exists, no `%LOCALAPPDATA%\StreamCap` exists) → start fresh
2. **Evo 1.x upgrade** (`%LOCALAPPDATA%\StreamCap` exists, Evo-specific data detected) → auto-migrate to `%LOCALAPPDATA%\StreamCapEvo`
3. **Coexistence** (no `%LOCALAPPDATA%\StreamCapEvo` exists but `%LOCALAPPDATA%\StreamCap` exists with original StreamCap data) → offer optional import
4. **Both apps have existing data** (both directories exist) → import button in settings for StreamCap → StreamCapEvo

Detection strategy: Write a sentinel file (`%LOCALAPPDATA%\StreamCap\.streamcapevo`) when Evo creates data. If `recordings.db` exists without the sentinel at startup, the data belongs to the original StreamCap.

### Risks

1. **Data loss during forward-migration**: MUST COPY, never move; MUST verify checksums or integrity before deleting originals. Actually, per requirement: never delete original data. So forward-migration should copy then leave old data in place.
2. **Detection false positive**: An Evo 1.x user who never upgraded and has no sentinel file could be offered an "import" of their own data. Mitigation: check for Evo-specific config keys in `user_settings.json` as a secondary signal.
3. **Concurrent app access**: User runs both StreamCap and StreamCapEvo simultaneously. The old `%LOCALAPPDATA%\StreamCap` directory could be locked by the running original app during import. Mitigation: import should be attempted only when the original app is detected as not running (check process list), or gracefully handle file-in-use errors.
4. **SQLite WAL files**: Importing `recordings.db` requires handling WAL (`-wal`, `-shm`) files properly. Use `sqlite3.backup()` API or ensure WAL checkpoint runs first.
5. **Test isolation under strict TDD**: Tests for import must never touch real user data directories. Use `tempfile.TemporaryDirectory` patterns as established in `test_config_manager_user_data.py`.
6. **Installer upgrade path**: Existing Evo 1.x users who install the new version will overwrite the old install. The forward-migration must run BEFORE the new version tries to read data from the old path.
7. **AppUserModelID change breaks taskbar pinning**: Changing the AppUserModelID means users who pinned the old app to their taskbar will lose the pinned shortcut. This is unavoidable but should be documented in release notes.

### Ready for Proposal

Yes — exploration is complete with sufficient understanding to proceed to proposal, spec, and design.

The orchestrator should inform the user:
- Change name: `phase-2-coexist-import`
- Recommendation is Approach 4 (full identity separation + new `%LOCALAPPDATA%\StreamCapEvo` directory + forward-migration for Evo 1.x data + optional import from original StreamCap)
- This WILL exceed the 800-line review budget (estimated 25+ files affected with significant new code for import logic, forward-migration, and tests). Recommendation: split into chained PRs.
- Strict TDD is active — all import and migration logic must be test-first.
