import os
import json
import logging
import time
from typing import Dict, Any, List, Optional, Tuple, cast
from cline_utils.dependency_system.utils.calculate_hash import calculate_content_hash
from cline_utils.dependency_system.utils.cache_manager import (
    normalize_path_cached as normalize_path,
)
from cline_utils.dependency_system.io.file_io import read_file_content_safely

logger = logging.getLogger(__name__)

# Registry location
REGISTRY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "core", "transparency_registry.json"
)


class TransparencyManager:
    """
    Manages the "invisible" transparency layer for documentation section markers.
    Maps file paths to line-number based section definitions stored externally.
    """

    def __init__(self, registry_path: str = REGISTRY_PATH):
        super().__init__()
        self.registry_path = registry_path
        self._registry: Dict[str, Any] = {"files": {}}
        self._load()

    def _load(self) -> None:
        """Loads the transparency registry from disk."""
        if os.path.exists(self.registry_path):
            try:
                with open(self.registry_path, "r", encoding="utf-8") as f:
                    self._registry = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load transparency registry: {e}")
                self._registry = {"files": {}}
        else:
            self._registry = {"files": {}}

    def _save(self) -> None:
        """Saves the transparency registry to disk."""
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.registry_path), exist_ok=True)
            with open(self.registry_path, "w", encoding="utf-8") as f:
                json.dump(self._registry, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save transparency registry: {e}")

    def get_file_metadata(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Retrieves transparency metadata for a specific file."""
        norm_path = normalize_path(file_path)
        return self._registry["files"].get(norm_path)

    def update_file_metadata(
        self, file_path: str, sections: Dict[str, Any], content: str
    ) -> None:
        """
        Updates the registry for a file, recording section mappings and current checksum.

        Args:
            file_path: Absolute or relative path to the file.
            sections: Dictionary mapping section names (e.g. 'TAGS') to (start_line, end_line).
            content: Current file content to generate checksum.
        """
        norm_path = normalize_path(file_path)
        checksum = calculate_content_hash(content, file_path)

        self._registry["files"][norm_path] = {
            "checksum": checksum,
            "last_modified": (
                os.path.getmtime(file_path)
                if os.path.exists(file_path)
                else time.time()
            ),
            "sections": sections,
        }
        self._save()

    def check_drift(self, file_path: str, current_content: str) -> bool:
        """
        Checks if the file content has drifted from the recorded checksum.
        Returns True if drift is detected.
        """
        metadata = self.get_file_metadata(file_path)
        if not metadata:
            return False

        current_checksum = calculate_content_hash(current_content, file_path)
        return current_checksum != metadata.get("checksum")

    def cleanup_missing_files(self) -> None:
        """Removes entries for files that no longer exist on disk."""
        missing: List[str] = []
        files_map = cast(Dict[str, Any], self._registry["files"])
        for path in files_map:
            if not os.path.exists(path):
                missing.append(path)

        if missing:
            for path in missing:
                del files_map[path]
            self._save()
            logger.info(
                f"Cleaned up {len(missing)} missing files from transparency registry."
            )


# Global instance for shared use
_manager_instance: Optional[TransparencyManager] = None


def get_transparency_manager() -> TransparencyManager:
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = TransparencyManager()
    return _manager_instance


def read_file_transparently(
    file_path: str,
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Reads a file and retrieves its transparency metadata (virtual markers).

    Returns:
        A tuple of (content, transparency_metadata).
    """
    content = read_file_content_safely(file_path)
    if content is None:
        return None, None

    manager = get_transparency_manager()
    metadata = manager.get_file_metadata(file_path)

    # Check for drift
    if metadata and manager.check_drift(file_path, content):
        import logging

        logging.getLogger(__name__).warning(
            f"Transparency drift detected for {file_path}. Metadata may be inaccurate."
        )

    return content, metadata
