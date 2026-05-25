"""Synchronize StreamCapEvo release versions.

pyproject.toml is the technical source of truth. This helper keeps the
user-facing release metadata in config/version.json aligned with it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = ROOT / "pyproject.toml"
VERSION_JSON_PATH = ROOT / "config" / "version.json"
SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
PYPROJECT_VERSION_RE = re.compile(
    r'(?m)^(version\s*=\s*)"((?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))"'
)
TITLE_VERSION_RE = re.compile(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")


@dataclass(frozen=True)
class VersionState:
    pyproject_version: str
    release_version: str
    title_versions: tuple[str, ...]


def parse_semver(value: str) -> tuple[int, int, int]:
    match = SEMVER_RE.fullmatch(value)
    if not match:
        raise ValueError(f"Invalid SemVer '{value}'. Expected X.Y.Z, for example 1.0.3.")
    return tuple(int(part) for part in match.groups())


def bump_patch(value: str) -> str:
    major, minor, patch = parse_semver(value)
    return f"{major}.{minor}.{patch + 1}"


def read_pyproject_version() -> str:
    content = PYPROJECT_PATH.read_text(encoding="utf-8")
    match = PYPROJECT_VERSION_RE.search(content)
    if not match:
        raise RuntimeError(f"Could not find [project] version in {PYPROJECT_PATH}.")
    return match.group(2)


def read_version_json() -> dict:
    with VERSION_JSON_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def get_first_release(version_data: dict) -> dict:
    updates = version_data.get("version_updates")
    if not isinstance(updates, list) or not updates:
        raise RuntimeError(f"{VERSION_JSON_PATH} must contain a non-empty version_updates list.")
    first_release = updates[0]
    if not isinstance(first_release, dict):
        raise RuntimeError(f"{VERSION_JSON_PATH} version_updates[0] must be an object.")
    return first_release


def collect_title_versions(first_release: dict) -> tuple[str, ...]:
    versions: list[str] = []
    announcements = first_release.get("announcement", {})
    if not isinstance(announcements, dict):
        return tuple()

    for entries in announcements.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            title = entry.get("title")
            if not isinstance(title, str):
                continue
            versions.extend(match.group(0)[1:] for match in TITLE_VERSION_RE.finditer(title))

    return tuple(versions)


def read_state() -> VersionState:
    pyproject_version = read_pyproject_version()
    version_data = read_version_json()
    first_release = get_first_release(version_data)
    release_version = first_release.get("version")
    if not isinstance(release_version, str):
        raise RuntimeError(f"{VERSION_JSON_PATH} version_updates[0].version must be a string.")

    return VersionState(
        pyproject_version=pyproject_version,
        release_version=release_version,
        title_versions=collect_title_versions(first_release),
    )


def validate_state(state: VersionState) -> list[str]:
    errors: list[str] = []

    for label, value in (
        ("pyproject.toml [project].version", state.pyproject_version),
        ("config/version.json version_updates[0].version", state.release_version),
    ):
        try:
            parse_semver(value)
        except ValueError as exc:
            errors.append(f"{label}: {exc}")

    if state.pyproject_version != state.release_version:
        errors.append(
            "Version mismatch: "
            f"pyproject.toml has {state.pyproject_version}, "
            f"config/version.json has {state.release_version}."
        )

    mismatched_titles = sorted({version for version in state.title_versions if version != state.pyproject_version})
    if mismatched_titles:
        errors.append(
            "Announcement title version mismatch: "
            f"expected v{state.pyproject_version}, found "
            + ", ".join(f"v{version}" for version in mismatched_titles)
            + "."
        )

    return errors


def update_pyproject_version(new_version: str) -> None:
    content = PYPROJECT_PATH.read_text(encoding="utf-8")
    updated, count = PYPROJECT_VERSION_RE.subn(rf'\g<1>"{new_version}"', content, count=1)
    if count != 1:
        raise RuntimeError(f"Expected to update exactly one version entry in {PYPROJECT_PATH}.")
    PYPROJECT_PATH.write_text(updated, encoding="utf-8")


def update_release_titles(first_release: dict, new_version: str) -> None:
    announcements = first_release.get("announcement", {})
    if not isinstance(announcements, dict):
        return

    for entries in announcements.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            title = entry.get("title")
            if isinstance(title, str):
                entry["title"] = TITLE_VERSION_RE.sub(f"v{new_version}", title)


def update_version_json(new_version: str) -> None:
    version_data = read_version_json()
    first_release = get_first_release(version_data)
    first_release["version"] = new_version
    update_release_titles(first_release, new_version)

    with VERSION_JSON_PATH.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(version_data, file, ensure_ascii=False, indent=2)
        file.write("\n")


def write_version(new_version: str) -> None:
    parse_semver(new_version)
    update_pyproject_version(new_version)
    update_version_json(new_version)


def run_check() -> int:
    state = read_state()
    errors = validate_state(state)
    if errors:
        print("[ERROR] Version metadata is not synchronized:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(f"[OK] Version metadata is synchronized: {state.pyproject_version}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bump or validate StreamCapEvo version metadata.")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--patch", action="store_true", help="Increment only the SemVer patch digit.")
    actions.add_argument("--set", metavar="X.Y.Z", help="Set an explicit SemVer version.")
    actions.add_argument("--check", action="store_true", help="Validate synchronized versions without writing files.")
    actions.add_argument("--current", action="store_true", help="Print the current pyproject.toml version.")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    try:
        if args.check:
            return run_check()

        if args.current:
            version = read_pyproject_version()
            parse_semver(version)
            print(version)
            return 0

        if args.patch:
            state = read_state()
            errors = validate_state(state)
            if errors:
                print("[ERROR] Refusing to bump while version metadata is inconsistent:", file=sys.stderr)
                for error in errors:
                    print(f"  - {error}", file=sys.stderr)
                return 1
            new_version = bump_patch(state.pyproject_version)
        else:
            new_version = args.set
            parse_semver(new_version)

        old_version = read_pyproject_version()
        write_version(new_version)
        print(f"[OK] Version updated: {old_version} -> {new_version}")
        return 0
    except (RuntimeError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
