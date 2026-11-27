"""`vol`: voluptuous, as Home Assistant types it.

Home Assistant 2026.10+ runs on probatio, which answers to the name voluptuous at runtime, and its type hints name
probatio's classes; older versions use voluptuous itself. Runtime always imports voluptuous (unchanged); only the type
checker is pointed at probatio, so schemas built here match the types Home Assistant asks for."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import probatio as vol
else:
    import voluptuous as vol

__all__ = ["vol"]
