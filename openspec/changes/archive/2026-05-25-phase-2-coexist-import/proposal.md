# Proposal: Phase 2 — Coexistence & Optional Import

## Intent

StreamCapEvo shares ALL identity and data resources with the original StreamCap — same AppUserModelID, executable name, installer AppId, install directory, and `%LOCALAPPDATA%\StreamCap` data directory. This makes them indistinguishable at the OS level, prevents side-by-side installation, and risks data loss on uninstall. We need to establish full identity separation and provide a safe, optional path for importing existing data from the original app.

## Scope

### In Scope
- Change ALL Windows identity fields to `StreamCapEvo` (AppUserModelID, installer AppId, exe name, install dir, start menu, publisher)
- Move data directory to `%LOCALAPPDATA%\StreamCapEvo`
- Automatic forward-migration for existing Evo 1.x data from old path at first run
- Optional one-time import dialog for original StreamCap data (recordings, settings, cookies, accounts, auth tokens)
- Sentinel-based detection to distinguish Evo vs original data in `%LOCALAPPDATA%\StreamCap`

### Out of Scope
- Two-way sync between StreamCap and StreamCapEvo data
- Import from versions before StreamCap's current `recordings.db` schema
- Linux/macOS coexistence (not platform targets)
- Batch/multi-user import

## Capabilities

> Contract with sdd-spec. No existing specs in `openspec/specs/`.

### New Capabilities
- `app-identity`: Windows identity separation (AppUserModelID, installer metadata, exe name)
- `data-migration`: Forward-migration of Evo 1.x data from `%LOCALAPPDATA%\StreamCap` to `%LOCALAPPDATA%\StreamCapEvo`
- `data-import`: Optional user-initiated import of original StreamCap data

### Modified Capabilities
- None — no existing specs to modify

## Approach

Approach 4 from exploration: full identity separation + new data directory + automatic forward-migration for Evo 1.x + optional original StreamCap import. Sentinel file (`.streamcapevo`) distinguishes Evo from original data in the shared directory. Import uses COPY semantics — never moves or deletes original data. Forward-migration runs once at first startup after install.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `main_qt.py` | Modified | AppUserModelID -> StreamCapEvo |
| `installer/StreamCap.iss` | Modified | All identity fields |
| `build_qt_nuitka.bat` | Modified | Output filename, product name, company |
| `app/core/config/config_manager.py` | Modified | Data path -> `StreamCapEvo`; forward-migration logic |
| `package_windows_installer.bat` | Modified | Output exe name reference |
| `app/core/data_import/` | New | Import logic module |
| `app/qt/views/import_view.py` | New | Import dialog/settings page |
| `tests/` | New | Test modules for migration + import |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Data loss during forward-migration | Low | COPY only, never MOVE; leave originals |
| Detection false positive (Evo 1.x seen as original) | Med | Sentinel + Evo-specific config keys as secondary signal |
| Concurrent app access locks old data dir | Med | Check process list before import; handle file-in-use |
| Taskbar pinning lost (AppUserModelID change) | High | Unavoidable; document in release notes |

## Rollback Plan

Revert identity fields to original StreamCap values + restore `%LOCALAPPDATA%\StreamCap` as default data path. Imported data already in new path is safe. Forward-migration is idempotent — old data remains untouched.

## Dependencies

- Ability to detect running process of original StreamCap (Windows `tasklist` / `psutil`)
- Nuitka build verifies identity metadata at compile time

## Success Criteria

- [ ] Clean install: no identity collisions with original StreamCap on same machine
- [ ] Upgrade from Evo 1.x: data auto-migrates with zero data loss
- [ ] Import: user can import original StreamCap recordings/settings via dialog
- [ ] Uninstall: original StreamCap data is never deleted by StreamCapEvo uninstaller
- [ ] All import and migration logic passes strict TDD tests
