"""Typed access to the fields of a decoded JSON object."""
from __future__ import annotations

from typing import Any

from filetag_protocol.errors import ProtocolError


class Fields:
    """Reads required and optional fields with type checks.

    Attributes:
        data: Decoded JSON object.
        what: Name of the message, used in error texts.
    """

    def __init__(self, data: Any, what: str):
        """Wrap a decoded JSON object.

        Args:
            data: Decoded JSON value; must be an object.
            what: Name of the message, used in error texts.

        Raises:
            ProtocolError: ``data`` is not a JSON object.
        """
        if not isinstance(data, dict):
            raise ProtocolError(f"{what}: expected a JSON object")
        self.data: dict[str, Any] = data
        self.what = what

    def get(self, name: str, kind: type | tuple[type, ...], required: bool = True) -> Any:
        """Return one field after checking its type.

        Args:
            name: Field name.
            kind: Expected Python type or types (``int`` excludes ``bool``).
            required: Whether a missing field or ``null`` is an error.

        Returns:
            The value, or None for a missing optional field.

        Raises:
            ProtocolError: Field missing although required, or of wrong type.
        """
        value = self.data.get(name)
        if value is None:
            if required:
                raise ProtocolError(f"{self.what}: field '{name}' missing")
            return None
        kinds = kind if isinstance(kind, tuple) else (kind,)
        if not isinstance(value, kinds) or (bool not in kinds and isinstance(value, bool)):
            names = " or ".join(item.__name__ for item in kinds)
            raise ProtocolError(f"{self.what}: field '{name}' must be {names}")
        return value

    def protocol(self, supported: int) -> int:
        """Check the protocol number of the message.

        Args:
            supported: Protocol number this code understands.

        Returns:
            The protocol number.

        Raises:
            ProtocolError: Number missing or different from ``supported``.
        """
        number = self.get("protocol", int)
        if number != supported:
            raise ProtocolError(f"{self.what}: protocol {number} not supported "
                                f"(this side speaks {supported})")
        return int(number)
