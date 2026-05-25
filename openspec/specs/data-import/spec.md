# Data Import Specification — FULL SPEC

## Purpose

Provide a safe, optional, user-initiated import from the original StreamCap's data directory into StreamCapEvo's data directory. Import uses copy-only semantics with proper lock/error handling. The user consents explicitly; import is never automatic.

## Requirements

### Requirement: Optional User-Initiated Import

The system MAY provide a one-time import dialog that allows the user to selectively copy recordings, settings, cookies, accounts, and auth tokens from the original StreamCap data directory (`%LOCALAPPDATA%\StreamCap`) into `%LOCALAPPDATA%\StreamCapEvo`.

#### Scenario: User initiates import from settings

- GIVEN `%LOCALAPPDATA%\StreamCap` contains recognizable StreamCap data
- AND the original StreamCap process is NOT running
- WHEN the user clicks "Import from StreamCap" in the settings dialog
- THEN compatible data files SHALL be copied to `%LOCALAPPDATA%\StreamCapEvo`
- AND the import progress and result SHALL be reported
- AND the import option SHALL be disabled after success (one-time operation)

#### Scenario: No original StreamCap data detected

- GIVEN `%LOCALAPPDATA%\StreamCap` does NOT exist or is empty
- WHEN the import dialog opens
- THEN the import option SHALL show as unavailable with a descriptive reason
- AND no copy operation SHALL be attempted

### Requirement: Copy-Only Semantics

Import MUST copy data from the original StreamCap path. It MUST NOT move, delete, or modify any original data in any circumstance.

#### Scenario: Original data untouched after import

- GIVEN import completed successfully
- WHEN comparing all files in `%LOCALAPPDATA%\StreamCap` to pre-import state
- THEN every file MUST be byte-identical

### Requirement: Concurrent Access Handling

The system MUST detect whether the original StreamCap process is running before starting import. If running, the import SHALL be blocked with a user-facing message. If a file lock error occurs mid-operation, the system MUST surface the error without corrupting already-imported data.

#### Scenario: Original StreamCap process is running

- GIVEN the original StreamCap.exe process is active
- WHEN the user attempts to start import
- THEN the system SHALL display: "Please close StreamCap before importing"
- AND no copy operation SHALL begin

#### Scenario: File lock acquired during import

- GIVEN import is in progress copying multiple files
- WHEN a single file returns a file-in-use error
- THEN the system SHALL log the specific error, skip the locked file, and continue with remaining files
- AND the final status SHALL report partial completion with the skipped file names

### Requirement: SQLite Database Integrity

The system MUST use a SQLite-safe copy mechanism for `recordings.db` — either `sqlite3.backup()` API or a WAL checkpoint-then-copy — to ensure the imported snapshot is transaction-consistent.

#### Scenario: Import with WAL journal files present

- GIVEN `recordings.db` in the source path has associated `-wal` and `-shm` files
- WHEN the import copies the database
- THEN the imported copy MUST be transaction-consistent (all WAL frames checkpointed)
- AND the raw `-wal` and `-shm` files MUST NOT be imported as standalone files
