"""A job: one file to analyse, sent by the controller to a worker."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

from filetag_protocol.errors import ProtocolError
from filetag_protocol.fields import Fields

KINDS = ("video",)
_HEX64 = re.compile(r"[0-9a-f]{64}")
_JOB_ID = re.compile(r"[0-9a-f]{32}")


@dataclass(frozen=True)
class Job:
    """One file to analyse.

    The job never carries a file name or path of the archive: the worker
    receives the content under the pseudonymous ``job_id`` only.

    Attributes:
        job_id: 32 lower-case hex digits, pseudonymous.
        kind: Media type, one of ``KINDS``.
        size: File size in bytes.
        sha256: Hash of the content, 64 lower-case hex digits.
        options: Analysis options (e.g. ``frame_interval_s``).
        protocol: Protocol number.
    """

    job_id: str
    kind: str
    size: int
    sha256: str
    options: dict[str, int | float | str] = field(default_factory=dict)
    protocol: int = 1

    def __post_init__(self) -> None:
        """Validate the fields.

        Raises:
            ProtocolError: A field has an invalid value.
        """
        if not _JOB_ID.fullmatch(self.job_id):
            raise ProtocolError("job: job_id must be 32 lower-case hex digits")
        if self.kind not in KINDS:
            raise ProtocolError(f"job: kind '{self.kind}' not supported")
        if self.size < 0:
            raise ProtocolError("job: size must not be negative")
        if not _HEX64.fullmatch(self.sha256):
            raise ProtocolError("job: sha256 must be 64 lower-case hex digits")

    def to_json(self) -> str:
        """Serialise the job.

        Returns:
            JSON text with sorted keys.
        """
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def from_json(cls, text: str, supported: int = 1) -> Job:
        """Parse and validate a job.

        Args:
            text: JSON text.
            supported: Protocol number this side understands.

        Returns:
            The job.

        Raises:
            ProtocolError: Invalid JSON, wrong protocol or invalid fields.
        """
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProtocolError(f"job: invalid JSON ({exc.msg})") from exc
        fields = Fields(data, "job")
        protocol = fields.protocol(supported)
        options = fields.get("options", dict, required=False) or {}
        return cls(job_id=fields.get("job_id", str), kind=fields.get("kind", str),
                   size=fields.get("size", int), sha256=fields.get("sha256", str),
                   options=options, protocol=protocol)
