"""
Best-effort POSIX permissions for runtime JSON files.

The service writes JSON files via atomic replace. On Linux that creates a new
inode, so we must reapply shared permissions after each write.
"""
from __future__ import annotations

import os
from pathlib import Path

RUNTIME_DIR_MODE = 0o2770
RUNTIME_FILE_MODE = 0o660


def apply_shared_json_permissions(path: Path) -> None:
    """Keep runtime JSON files writable by the service group.

    Permission repair must never make the original write fail. Some local
    development environments do not support POSIX chmod semantics.
    """
    if os.name != "posix":
        return

    try:
        path.parent.chmod(RUNTIME_DIR_MODE)
    except OSError:
        pass

    try:
        path.chmod(RUNTIME_FILE_MODE)
    except OSError:
        pass
