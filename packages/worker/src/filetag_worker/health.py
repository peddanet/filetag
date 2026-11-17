"""Self-report of a worker: versions and available programs."""
from __future__ import annotations

import platform
import shutil
from collections.abc import Callable

import filetag_protocol
import filetag_providers
from filetag_worker import __version__

PROGRAMS = ("ffmpeg", "ffprobe")


class Health:
    """Collects what the controller needs to know before sending a job.

    Attributes:
        which: Function that locates a program (``shutil.which``).
    """

    def __init__(self, which: Callable[[str], str | None] = shutil.which):
        """Inject the program lookup.

        Args:
            which: Function that returns the path of a program or None.
        """
        self.which = which

    def report(self) -> dict[str, object]:
        """Build the health report.

        Returns:
            Versions, protocol number, programs found and an overall ``ok``.
        """
        programs = {name: self.which(name) for name in PROGRAMS}
        return {
            "worker": __version__,
            "protocol": filetag_protocol.PROTOCOL_VERSION,
            "providers": filetag_providers.__version__,
            "python": platform.python_version(),
            "programs": programs,
            "ok": all(programs.values()),
        }
