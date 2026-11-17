"""Error raised for malformed or incompatible protocol messages."""


class ProtocolError(ValueError):
    """A job or result does not follow the protocol."""
