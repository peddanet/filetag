"""Job and result format exchanged between the filetag controller and a worker.

The format is versioned independently of the package version: a worker
refuses a job whose ``protocol`` number it does not know.
"""
from filetag_protocol.errors import ProtocolError
from filetag_protocol.job import Job
from filetag_protocol.result import Result

__version__ = "0.1.0"
PROTOCOL_VERSION = 1

__all__ = ["Job", "PROTOCOL_VERSION", "ProtocolError", "Result", "__version__"]
