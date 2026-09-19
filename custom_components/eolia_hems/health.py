"""Health class for the Eolia HEMS integration."""

from dataclasses import dataclass


@dataclass(slots=True)
class RuntimeHealth:
    last_client_error: str | None = None
    last_client_error_at: float | None = None
    last_restart_at: float | None = None
    restart_attempts: int = 0
    last_runtime_activity_at: float | None = None
