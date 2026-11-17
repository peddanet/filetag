"""Model backends of filetag: local inference servers and cloud APIs.

Each backend is described by a profile (``profiles/*.json``): endpoint,
interface, what it accepts, and the facts of its data and content policy
with the date they were last checked. The setup assistant shows these facts
before an API key is stored; a profile whose policy facts are older than
``ProfileRegistry.MAX_AGE_DAYS`` is reported as stale.
"""
from filetag_providers.profile import Profile
from filetag_providers.registry import ProfileRegistry

__version__ = "0.1.0"

__all__ = ["Profile", "ProfileRegistry", "__version__"]
