"""One regular file found by a scan."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScanEntry:
    """Where a file lies and what its inode says.

    Attributes:
        path: Absolute path.
        device: Device number of the file system.
        inode: Inode number.
        size: Size in bytes.
        mtime_ns: Modification time in nanoseconds.
    """

    path: str
    device: int
    inode: int
    size: int
    mtime_ns: int

    def same_inode_state(self, other: "ScanEntry") -> bool:
        """Tell whether the file is unchanged since ``other`` was taken.

        Args:
            other: An earlier entry of the same path.

        Returns:
            True when device, inode, size and modification time agree.
        """
        return (self.device, self.inode, self.size, self.mtime_ns) == (
            other.device, other.inode, other.size, other.mtime_ns)
