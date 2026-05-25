# Data Migration Specification — FULL SPEC

## Purpose

Automatically forward-migrate existing StreamCapEvo 1.x data from `%LOCALAPPDATA%\StreamCap` to `%LOCALAPPDATA%\StreamCapEvo` on first run after upgrade. Migration MUST use copy-only semantics, never move or delete original data.

## Requirements

### Requirement: Forward Migration on First Run

The system MUST detect Evo 1.x data in the old path (`%LOCALAPPDATA%\StreamCap`) and copy it to the new path (`%LOCALAPPDATA%\StreamCapEvo`) when the new path does not exist but the old path contains Evo-specific data.

#### Scenario: First run after upgrade from Evo 1.x

- GIVEN `%LOCALAPPDATA%\StreamCap` contains Evo data (sentinel or config keys present)
- AND `%LOCALAPPDATA%\StreamCapEvo` does NOT exist
- WHEN StreamCapEvo starts for the first time after upgrade
- THEN all files from old path MUST be copied to `%LOCALAPPDATA%\StreamCapEvo`
- AND ALL subsequent reads MUST use the new path
- AND original files in old path MUST remain untouched

#### Scenario: Clean install with no old data

- GIVEN neither `%LOCALAPPDATA%\StreamCapEvo` nor `%LOCALAPPDATA%\StreamCap` exist
- WHEN StreamCapEvo starts
- THEN a fresh data directory MUST be created at `%LOCALAPPDATA%\StreamCapEvo`
- AND no migration logic SHALL execute

### Requirement: Sentinel-Based Detection

The system MUST write a `.streamcapevo` sentinel file into `%LOCALAPPDATA%\StreamCap` when Evo first creates data there. On startup, use the sentinel as primary detection signal and Evo-specific `user_settings.json` config keys as secondary fallback.

#### Scenario: Sentinel present identifies Evo 1.x data

- GIVEN `%LOCALAPPDATA%\StreamCap\.streamcapevo` exists
- WHEN migration logic evaluates the old path
- THEN the data MUST be classified as Evo 1.x data and migrated

#### Scenario: No sentinel but Evo config keys present

- GIVEN the sentinel file does NOT exist
- BUT `user_settings.json` contains Evo-specific keys (e.g., `window_geometry`, `recording_output_dir`)
- WHEN migration logic evaluates the old path
- THEN the data MUST still be classified as Evo 1.x data (secondary signal)
- AND a `.streamcapevo` sentinel MUST be written to prevent re-detection

### Requirement: Non-Destructive Semantics

Migration MUST copy data from old path to new path. The system MUST NOT move, delete, or alter any file in the old path.

#### Scenario: Original data preserved after migration

- GIVEN migration from old path to new path completed successfully
- WHEN all files in `%LOCALAPPDATA%\StreamCap` are compared to their pre-migration checksums
- THEN every file MUST be byte-identical to its pre-migration state
