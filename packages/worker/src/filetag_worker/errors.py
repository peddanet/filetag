"""Errors of the worker."""


class WorkerError(RuntimeError):
    """A job cannot be carried out."""


class FlaggedContent(WorkerError):
    """The model flagged a frame; the file needs a review by a person."""
