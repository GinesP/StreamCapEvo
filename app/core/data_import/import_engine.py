"""Import engine for optional data import from original StreamCap.

Provides safe, non-destructive import of data from the original StreamCap
application to StreamCapEvo, with process detection and SQLite backup support.
"""

import os
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

from ...utils.logger import logger


@dataclass
class ImportResult:
    """Result of an import operation."""
    success: bool
    files_copied: List[str] = field(default_factory=list)
    files_skipped: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class ImportEngine:
    """Engine for importing data from original StreamCap to StreamCapEvo.
    
    Handles:
    - Process detection (blocks import if StreamCap is running)
    - Safe file copying with error handling
    - SQLite database backup (transaction-consistent)
    - Non-destructive operations (never modifies source)
    """
    
    # Files to import from source config directory
    IMPORTABLE_FILES = [
        "user_settings.json",
        "cookies.json",
        "accounts.json",
        "web_auth.json",
        "recordings.db",
    ]
    
    # Process names that indicate original StreamCap is running
    SOURCE_PROCESS_NAMES = ["StreamCap.exe", "StreamCap"]
    
    def __init__(self, source_path: str, dest_config_path: str):
        """Initialize the import engine.
        
        Args:
            source_path: Path to original StreamCap data directory
            dest_config_path: Path to StreamCapEvo config directory
        """
        self.source_path = Path(source_path)
        self.source_config_path = self.source_path / "config"
        self.dest_config_path = Path(dest_config_path)
    
    def is_source_running(self) -> bool:
        """Check if the original StreamCap application is currently running.
        
        Uses psutil to iterate through processes and check for StreamCap.exe
        or similar process names.
        
        Returns:
            True if StreamCap appears to be running, False otherwise
        """
        if not PSUTIL_AVAILABLE:
            # If psutil is not available, assume not running (allow import)
            logger.warning("psutil not available, cannot detect if StreamCap is running")
            return False
        
        try:
            for proc in psutil.process_iter(['name', 'pid']):
                try:
                    proc_name = proc.info.get('name', '')
                    if proc_name in self.SOURCE_PROCESS_NAMES:
                        logger.info(f"Detected running StreamCap process: {proc_name} (PID: {proc.info.get('pid')})")
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as e:
            logger.error(f"Error checking for running StreamCap: {e}")
        
        return False
    
    def has_importable_data(self) -> bool:
        """Check if the source directory contains importable data.
        
        Looks for recordings.db as the primary indicator of data presence.
        
        Returns:
            True if importable data exists, False otherwise
        """
        if not self.source_config_path.exists():
            return False
        
        # Check for recordings.db as primary indicator
        recordings_db = self.source_config_path / "recordings.db"
        return recordings_db.exists()
    
    def import_all(self) -> ImportResult:
        """Perform the import operation.
        
        Steps:
        1. Check if StreamCap is running (block if so)
        2. Copy JSON files using shutil.copy2
        3. Copy SQLite databases using sqlite3.backup() for consistency
        4. Handle file-in-use errors gracefully
        
        Returns:
            ImportResult with success status and details
        """
        result = ImportResult(success=False)
        
        # Check if source is running
        if self.is_source_running():
            error_msg = "StreamCap is currently running. Please close StreamCap before importing."
            result.errors.append(error_msg)
            logger.warning(f"Import blocked: {error_msg}")
            return result
        
        # Check if source has data
        if not self.has_importable_data():
            error_msg = "No importable data found in StreamCap directory."
            result.errors.append(error_msg)
            logger.warning(f"Import failed: {error_msg}")
            return result
        
        # Ensure destination exists
        self.dest_config_path.mkdir(parents=True, exist_ok=True)
        
        # Import each file
        for filename in self.IMPORTABLE_FILES:
            source_file = self.source_config_path / filename
            dest_file = self.dest_config_path / filename
            
            if not source_file.exists():
                continue
            
            try:
                if filename.endswith('.db'):
                    # Use SQLite backup for databases
                    self._import_sqlite_database(source_file, dest_file)
                else:
                    # Use shutil.copy2 for other files
                    shutil.copy2(source_file, dest_file)
                
                result.files_copied.append(filename)
                logger.info(f"Imported: {filename}")
                
            except PermissionError as e:
                # File in use - skip but continue
                result.files_skipped.append(filename)
                error_msg = f"Skipped {filename}: File in use ({e})"
                result.errors.append(error_msg)
                logger.warning(error_msg)
                
            except Exception as e:
                # Other errors - skip but continue
                result.files_skipped.append(filename)
                error_msg = f"Failed to import {filename}: {e}"
                result.errors.append(error_msg)
                logger.error(error_msg)
        
        # Success if we copied at least one file
        result.success = len(result.files_copied) > 0
        
        if result.success:
            logger.info(f"Import completed: {len(result.files_copied)} files copied, {len(result.files_skipped)} skipped")
        
        return result
    
    def _import_sqlite_database(self, source_path: Path, dest_path: Path) -> None:
        """Import a SQLite database using the backup API for consistency.
        
        Uses sqlite3.backup() which handles WAL checkpointing automatically,
        ensuring a transaction-consistent snapshot.
        
        Args:
            source_path: Path to source database
            dest_path: Path to destination database
        """
        # Connect to source database
        source_conn = sqlite3.connect(str(source_path))
        try:
            # Create destination database
            dest_conn = sqlite3.connect(str(dest_path))
            try:
                # Use backup API for consistent snapshot
                source_conn.backup(dest_conn, pages=1000)
                dest_conn.commit()
                logger.info(f"SQLite backup completed: {source_path.name}")
            finally:
                dest_conn.close()
        finally:
            source_conn.close()
