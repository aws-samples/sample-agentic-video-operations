"""
Request Context Singleton

Provides a thread-safe singleton to share request context (prompt_uuid, user_timezone, etc.)
across the orchestrator and subagents within a single request lifecycle.
"""

from threading import Lock
from typing import Optional


class RequestContext:
    """Singleton class to hold request-scoped context values."""
    
    _instance: Optional["RequestContext"] = None
    _lock: Lock = Lock()
    
    def __new__(cls) -> "RequestContext":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._prompt_uuid: str = ""
        self._user_timezone: str = "US/Pacific"
        self._session_id: str = ""
        self._user_id: str = "guest"
        self._initialized = True
    
    def set(
        self,
        prompt_uuid: str,
        user_timezone: str = "US/Pacific",
        session_id: str = "",
        user_id: str = "guest"
    ) -> None:
        """Set the request context values."""
        self._prompt_uuid = prompt_uuid
        self._user_timezone = user_timezone
        self._session_id = session_id
        self._user_id = user_id
    
    @property
    def prompt_uuid(self) -> str:
        return self._prompt_uuid
    
    @property
    def user_timezone(self) -> str:
        return self._user_timezone
    
    @property
    def session_id(self) -> str:
        return self._session_id
    
    @property
    def user_id(self) -> str:
        return self._user_id
    
    def clear(self) -> None:
        """Clear the context values."""
        self._prompt_uuid = ""
        self._user_timezone = "US/Pacific"
        self._session_id = ""
        self._user_id = "guest"


# Global instance accessor
def get_request_context() -> RequestContext:
    """Get the singleton RequestContext instance."""
    return RequestContext()
