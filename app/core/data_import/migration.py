"""Data migration utilities for StreamCapEvo.

Handles forward migration from Evo 1.x data directory to the new StreamCapEvo
data directory, including sentinel-based detection and safe file copying.
"""

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ...utils.logger import logger


@dataclass
class DetectionResult:
    """Result of Evo data detection in a directory."""
    is_evo_data: bool
    sentinel_present: bool
    fallback_keys_found: bool


def detect_evo_data(old_path: str) -> DetectionResult:
    """Detect if the old path contains Evo 1.x data.
    
    Uses sentinel file (.streamcapevo) as primary signal, with Evo-specific
    config keys as fallback. If fallback keys are found but no sentinel,
    writes the sentinel for future detection.
    
    Args:
        old_path: Path to the old data directory (e.g., %LOCALAPPDATA%\\StreamCap)
        
    Returns:
        DetectionResult with detection status and details
    """
    old_path_obj = Path(old_path)
    sentinel_path = old_path_obj / ".streamcapevo"
    config_path = old_path_obj / "config"
    user_settings_path = config_path / "user_settings.json"
    
    # Check if old path exists at all
    if not old_path_obj.exists():
        return DetectionResult(
            is_evo_data=False,
            sentinel_present=False,
            fallback_keys_found=False
        )
    
    sentinel_present = sentinel_path.exists()
    fallback_keys_found = False
    
    # Check for Evo-specific config keys if config exists
    if user_settings_path.exists():
        try:
            with open(user_settings_path, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            
            # Check for Evo-specific keys
            evo_keys = ["streamcapevo_version", "evo_migration_completed"]
            fallback_keys_found = any(key in user_config for key in evo_keys)
        except (json.JSONDecodeError, IOError):
            pass
    
    # Classify as Evo data if sentinel present OR Evo keys found
    is_evo_data = sentinel_present or fallback_keys_found
    
    # Write sentinel if we detected via fallback keys but no sentinel
    if is_evo_data and not sentinel_present:
        try:
            sentinel_path.touch()
            logger.info(f"Wrote Evo sentinel file to {sentinel_path}")
        except OSError as e:
            logger.warning(f"Could not write sentinel file: {e}")
    
    return DetectionResult(
        is_evo_data=is_evo_data,
        sentinel_present=sentinel_present,
        fallback_keys_found=fallback_keys_found
    )


def forward_migrate(old_path: str, new_path: str) -> int:
    """Forward migrate Evo 1.x data from old path to new path.
    
    Copies all files and directories from old_path to new_path using shutil.copytree
    with copy2 to preserve metadata. Original files remain untouched (copy-only).
    
    Args:
        old_path: Source path (e.g., %LOCALAPPDATA%\\StreamCap)
        new_path: Destination path (e.g., %LOCALAPPDATA%\\StreamCapEvo)
        
    Returns:
        Number of bytes copied
    """
    old_path_obj = Path(old_path)
    new_path_obj = Path(new_path)
    
    if not old_path_obj.exists():
        logger.info(f"Old path does not exist, skipping forward migration: {old_path}")
        return 0
    
    if new_path_obj.exists():
        logger.info(f"New path already exists, skipping forward migration: {new_path}")
        return 0
    
    try:
        # Use copytree with copy2 to preserve metadata
        shutil.copytree(
            old_path,
            new_path,
            copy_function=shutil.copy2
        )
        
        # Calculate bytes copied
        bytes_copied = _calculate_directory_size(new_path_obj)
        
        logger.info(
            f"Forward migration completed: {old_path} → {new_path} "
            f"({bytes_copied} bytes)"
        )
        
        return bytes_copied
        
    except Exception as e:
        logger.error(f"Forward migration failed: {e}")
        # Clean up partial copy if it exists
        if new_path_obj.exists():
            try:
                shutil.rmtree(new_path)
                logger.info(f"Cleaned up partial migration: {new_path}")
            except Exception as cleanup_error:
                logger.error(f"Failed to cleanup partial migration: {cleanup_error}")
        raise


def _calculate_directory_size(path: Path) -> int:
    """Calculate total size of all files in a directory recursively."""
    total_size = 0
    if path.exists():
        for item in path.rglob("*"):
            if item.is_file():
                total_size += item.stat().st_size
    return total_size
