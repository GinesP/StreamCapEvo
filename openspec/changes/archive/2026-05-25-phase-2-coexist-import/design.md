# Design: Phase 2 — Coexistence & Optional Import

## Technical Approach

Full identity separation (all Windows fields → `StreamCapEvo`) + new data directory `%LOCALAPPDATA%\StreamCapEvo` + automatic forward-migration for Evo 1.x at first run + optional user-initiated import from original StreamCap. Sentinel file (`.streamcapevo`) plus Evo-specific config keys distinguish Evo data from original StreamCap data in the shared old directory.

Maps to **Approach 4** from exploration. The three specs (app-identity, data-migration, data-import) are each addressed in sequence.

## Architecture Decisions

| Decision | Choice | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| Identity fields | ALL → `StreamCapEvo` | Partial rename | Full separation prevents any future collision (AppUserModelID, AppId, exe name, install dir, Start Menu, publisher) |
| Data directory | `%LOCALAPPDATA%\StreamCapEvo` | Keep `StreamCap`, env-var override | Override exists for testing; primary path must be unique to prevent data loss on uninstall |
| Forward-migration | Auto, first-run, copy-only | Manual migration, move semantics | Zero-touch UX for existing Evo 1.x users; copy-never-move protects originals |
| Import | Copy-only, never move/delete | Move-or-merge | Original StreamCap data must be byte-identical post-import per spec |
| Sentinel | `.streamcapevo` file + config keys | Registry key, env var | File-based sentinel survives uninstall; config keys (`user_settings.json` Evo-specific fields) act as fallback for pre-sentinel Evo 1.x installs |
| SQLite copy | `sqlite3.backup()` API | Raw `shutil.copy2` of `.db` file | Transaction-consistent snapshot; auto-checkpoints WAL/SHM; handles journal modes |
| Process detection | `psutil.process_iter()` | `tasklist` CLI | Cross-platform, available via pip, returns richer data (PID, exe path) |
| UI entry | Settings → new "Data" tab | Dedicated first-run wizard | Non-intrusive; user discovers it in natural settings flow; one-time disable after success |
| Test isolation | `tempfile.TemporaryDirectory` + `mock.patch` | Real user-data dirs | Matches established pattern in `test_config_manager_user_data.py` |

## Data Flow

```
Startup (ConfigManager.__init__):
  path = get_default_user_data_path()
       → %LOCALAPPDATA%\StreamCapEvo  [CHANGED]

  if new_path exists:
      use it (normal startup)
  elif old_path (%LOCALAPPDATA%\StreamCap) exists:
      if sentinel (.streamcapevo) OR Evo config keys:
          → forward_migrate(): shutil.copytree(old → new, copy_function=shutil.copy2)
          → write .streamcapevo to old_path root (for future re-detection)
          → config_path = new_path/config/
      else:
          → mark "original StreamCap data detected" flag (for Settings UI)
          → create new_path/config/ fresh
  else:
      → create new_path/config/ fresh

Import (user-initiated from Settings → Data tab):
  User clicks "Import from StreamCap"
    → psutil.process_iter(): StreamCap.exe running? → BLOCK: "Please close StreamCap"
    → Detect: %LOCALAPPDATA%\StreamCap/config/ has recordings.db?
    → For recordings.db:
        sqlite3.connect(source_db) → conn.backup(dest_db_conn, pages=1000, progress=cb)
    → For JSON files:
        shutil.copy2(src, dst) — skip if locked, log, continue
    → Report result (success / partial with skipped files)
    → Disable button (one-time; set user_settings["import_completed"] = true)
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `main_qt.py` | Modify | AppUserModelID → `StreamCapEvo.streamcapevo.app.1` |
| `installer/StreamCap.iss` | Modify | AppId, AppName, ExeName, DefaultDirName, DefaultGroupName, Publisher, OutputBaseFilename → `StreamCapEvo` |
| `build_qt_nuitka.bat` | Modify | `--output-filename=StreamCapEvo.exe`, `--product-name`, `--company-name` |
| `package_windows_installer.bat` | Modify | `BUILD_EXE` → `StreamCapEvo.exe` |
| `app/core/config/config_manager.py` | Modify | `get_default_user_data_path()` → `StreamCapEvo`; add forward-migration call before `init()` |
| `app/core/data_import/__init__.py` | Create | Package init |
| `app/core/data_import/import_engine.py` | Create | Core import: process detection, file copy, sqlite3.backup() |
| `app/core/data_import/migration.py` | Create | Sentinel detection, forward-migration orchestration |
| `app/qt/views/settings_view.py` | Modify | Add 5th tab "Data" with import button + status |
| `locales/en.json`, `locales/es.json` | Modify | Translation keys for import UI |
| `test_config_manager_user_data.py` | Modify | Update path assertions; add migration unit tests |
| `test_data_import.py` | Create | Full TDD suite for import engine + SQLite backup |

## Interfaces / Contracts

```python
# app/core/data_import/migration.py
@dataclass
class DetectionResult:
    is_evo_data: bool
    has_original_data: bool
    sentinel_present: bool
    fallback_keys_found: bool

def forward_migrate(old_path: str, new_path: str) -> int  # returns bytes copied

# app/core/data_import/import_engine.py
@dataclass
class ImportResult:
    success: bool
    files_copied: list[str]
    files_skipped: list[str]
    errors: list[str]

class ImportEngine:
    def __init__(self, source_path: str, dest_config: str)
    def is_source_running(self) -> bool
    def has_importable_data(self) -> bool
    def import_all(self) -> ImportResult
```

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | Sentinel detection | 4 cases: sentinel present, keys only, neither, both |
| Unit | `ImportEngine.has_importable_data` | Empty dir, populated dir, no dir |
| Unit | `ImportEngine.is_source_running` | `mock.patch("psutil.process_iter")` |
| Unit | SQLite `sqlite3.backup()` | Create DB with WAL, backup, verify row count + checksums |
| Unit | File-in-use handling | `mock.patch("shutil.copy2", side_effect=PermissionError)` |
| Integration | Forward migration full flow | `TemporaryDirectory` old → `TemporaryDirectory` new → verify all files |
| Integration | ConfigManager path resolution | Union of existing `test_*_user_data` pattern + new `StreamCapEvo` path |

All tests: `unittest.TestCase` + `tempfile.TemporaryDirectory` + `unittest.mock.patch`. Strict TDD: RED (test fails) → GREEN (implement) → REFACTOR.

## Migration / Rollout

No migration for non-Evo users — this change IS the migration. Identity change means taskbar pins break (document in release notes). Forward-migration runs ONCE at first startup of new build; idempotent by checking existence of new path. Import is always user-initiated, never automatic.

**Rollback**: Revert identity fields + restore `get_default_user_data_path()` to `StreamCap`. Forward-migrated data stays in new path — old path untouched.

## Implementation Slicing (Chained PRs)

800-line review budget → 3 slices:

1. **PR 1 (Identity separation)** ~200 lines: `main_qt.py`, `StreamCap.iss`, `build_qt_nuitka.bat`, `package_windows_installer.bat`. Pure mechanical rename; trivially verifiable.
2. **PR 2 (Data path + forward-migration)** ~300 lines: `config_manager.py` path change, `migration.py` (new), test updates. Core data safety logic.
3. **PR 3 (Import engine + UI)** ~300 lines: `import_engine.py` (new), settings "Data" tab, locale keys, `test_data_import.py`. User-facing feature.

## Open Questions

- [ ] Should `predictor_metrics.db` be included in forward-migration? It lives in `config_path/predictor_metrics.db` — same new path inherits this automatically via path change. Confirm no extra step needed.
- [ ] Sentinel file location: `%LOCALAPPDATA%\StreamCap\.streamcapevo` or `%LOCALAPPDATA%\StreamCap\config\.streamcapevo`? Root-level avoids colliding with config files.
- [ ] Source-run detection scope: detect `StreamCap.exe` only, or include other common names that indicate the original app is active?
