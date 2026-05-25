# StreamCapEvo Identity Specification — FULL SPEC

## Purpose

Define the Windows identity separation between StreamCapEvo and original StreamCap to enable side-by-side coexistence. All identity fields MUST use the `StreamCapEvo` token — distinct from the original `StreamCap` — at the OS, installer, and filesystem levels.

## Requirements

### Requirement: Identity Separation

The system MUST use the value `StreamCapEvo` for every Windows identity field: AppUserModelID, installer AppId/AppName, executable filename, default install directory path, Start Menu group name, and publisher/company name.

#### Scenario: Clean install uses distinct OS identity

- GIVEN a machine with no StreamCap or StreamCapEvo installed
- WHEN StreamCapEvo is installed via its Windows installer
- THEN the AppUserModelID MUST be `StreamCapEvo.streamcapevo.app.1`
- AND the executable filename MUST be `StreamCapEvo.exe`
- AND the default install directory MUST be `%LOCALAPPDATA%\Programs\StreamCapEvo`
- AND the Start Menu group MUST be `StreamCapEvo`

#### Scenario: Side-by-side coexistence with original StreamCap

- GIVEN original StreamCap is already installed on the same machine
- WHEN StreamCapEvo is also installed
- THEN both products MUST appear as separate entries in Windows Add/Remove Programs
- AND their executables MUST reside in distinct install directories
- AND launching either MUST NOT affect the other's process or identity

### Requirement: Non-Destructive Identity Change

The identity change MUST NOT modify, delete, or overwrite any original StreamCap identity artifacts — including registry keys, shortcuts, uninstall entries, or Start Menu items.

#### Scenario: Original StreamCap shortcuts preserved

- GIVEN original StreamCap is installed with Start Menu shortcuts
- WHEN StreamCapEvo installer runs and completes
- THEN all original StreamCap Start Menu entries MUST remain intact

#### Scenario: Original StreamCap uninstall entry preserved

- GIVEN original StreamCap has a registered uninstall entry in Windows Registry
- WHEN StreamCapEvo installer runs
- THEN the original StreamCap uninstall entry MUST remain in the registry unchanged
