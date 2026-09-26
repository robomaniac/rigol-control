"""Read-only web status dashboard for benchctl (standard library only)."""

from benchctl.web.server import StatusCollector, create_server

__all__ = ["StatusCollector", "create_server"]
