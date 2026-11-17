"""A result: what a worker found out about one job."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from filetag_protocol.errors import ProtocolError
from filetag_protocol.fields import Fields

STATUSES = ("ok", "error")


@dataclass(frozen=True)
class Result:
    """Outcome of one job.

    Attributes:
        job_id: Id of the job this result answers.
        status: ``ok`` or ``error``.
        model: Backend and model that produced the text, e.g. ``ollama/qwen3-vl:8b``.
        language: ISO 639-1 code of the spoken language, None if no speech.
        title: Short descriptive title (English).
        story: Description in English.
        story_de: German description, only when German is spoken.
        tags: Tags of the controlled vocabulary and free keywords.
        error: Error text when ``status`` is ``error``.
        protocol: Protocol number.
    """

    job_id: str
    status: str
    model: str = ""
    language: str | None = None
    title: str = ""
    story: str = ""
    story_de: str | None = None
    tags: list[str] = field(default_factory=list)
    error: str | None = None
    protocol: int = 1

    def __post_init__(self) -> None:
        """Validate the fields.

        Raises:
            ProtocolError: Unknown status, or status and error text disagree.
        """
        if self.status not in STATUSES:
            raise ProtocolError(f"result: status '{self.status}' unknown")
        if (self.status == "error") != bool(self.error):
            raise ProtocolError("result: an error text belongs to status 'error' only")

    def to_json(self) -> str:
        """Serialise the result.

        Returns:
            JSON text with sorted keys.
        """
        return json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str, supported: int = 1) -> Result:
        """Parse and validate a result.

        Args:
            text: JSON text.
            supported: Protocol number this side understands.

        Returns:
            The result.

        Raises:
            ProtocolError: Invalid JSON, wrong protocol or invalid fields.
        """
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProtocolError(f"result: invalid JSON ({exc.msg})") from exc
        fields = Fields(data, "result")
        protocol = fields.protocol(supported)
        tags = fields.get("tags", list, required=False) or []
        if not all(isinstance(tag, str) for tag in tags):
            raise ProtocolError("result: tags must be strings")
        return cls(job_id=fields.get("job_id", str), status=fields.get("status", str),
                   model=fields.get("model", str, required=False) or "",
                   language=fields.get("language", str, required=False),
                   title=fields.get("title", str, required=False) or "",
                   story=fields.get("story", str, required=False) or "",
                   story_de=fields.get("story_de", str, required=False),
                   tags=tags, error=fields.get("error", str, required=False),
                   protocol=protocol)
