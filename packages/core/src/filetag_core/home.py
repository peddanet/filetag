"""Folder of all data of an installation."""
from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

ENV = "FILETAG_HOME"
DEFAULT = Path("~/.local/share/filetag")


class Home:
    """Locates ``~/.local/share/filetag`` (or ``$FILETAG_HOME``) and its files.

    Attributes:
        root: The data folder.
    """

    def __init__(self, environ: Mapping[str, str] | None = None):
        """Resolve the data folder.

        Args:
            environ: Environment to read ``FILETAG_HOME`` from; default
                ``os.environ``.
        """
        env = os.environ if environ is None else environ
        self.root = Path(env.get(ENV) or DEFAULT).expanduser()

    @property
    def database(self) -> Path:
        """Path of the database file.

        Returns:
            ``<root>/filetag.db``.
        """
        return self.root / "filetag.db"

    def ensure(self) -> Path:
        """Create the data folder with mode 0700 if it does not exist.

        Returns:
            The data folder.
        """
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        return self.root
