"""Content fingerprint of a file without reading all of it."""
from __future__ import annotations

import hashlib
import os
from collections.abc import Callable

CHUNK = 16 * 1024 * 1024
BLOCK = 1024 * 1024


class Fingerprinter:
    """Hashes the size, the first and the last ``chunk`` bytes of a file.

    Large media files are read only at both ends, so a scan over WLAN or a
    slow disk stays fast. Files up to twice the chunk size are hashed
    completely. Two files that differ only in their middle part get the
    same fingerprint; the size in the hash makes that unlikely for media.

    Attributes:
        chunk: Bytes read at each end.
        block: Read size.
    """

    def __init__(self, chunk: int = CHUNK, block: int = BLOCK):
        """Set the read sizes.

        Args:
            chunk: Bytes read at the start and at the end of a file.
            block: Bytes per read call.

        Raises:
            ValueError: A size is not positive.
        """
        if chunk < 1 or block < 1:
            raise ValueError("chunk and block must be positive")
        self.chunk = chunk
        self.block = block

    def _feed(self, update: Callable[[bytes], object], handle: int, count: int) -> None:
        """Read ``count`` bytes from the current position into the digest.

        Args:
            update: ``update`` method of the running hash.
            handle: Open file descriptor.
            count: Bytes to read.

        Raises:
            OSError: The file became shorter while it was read.
        """
        while count > 0:
            data = os.read(handle, min(self.block, count))
            if not data:
                raise OSError("file shrank while it was read")
            update(data)
            count -= len(data)

    def digest(self, path: str, size: int) -> str:
        """Compute the fingerprint.

        Args:
            path: File to read.
            size: File size in bytes as found by the scan.

        Returns:
            64 lower-case hex digits (SHA-256).
        """
        digest = hashlib.sha256(size.to_bytes(8, "big"))
        handle = os.open(path, os.O_RDONLY)
        try:
            if size <= 2 * self.chunk:
                self._feed(digest.update, handle, size)
            else:
                self._feed(digest.update, handle, self.chunk)
                os.lseek(handle, size - self.chunk, os.SEEK_SET)
                self._feed(digest.update, handle, self.chunk)
        finally:
            os.close(handle)
        return digest.hexdigest()
