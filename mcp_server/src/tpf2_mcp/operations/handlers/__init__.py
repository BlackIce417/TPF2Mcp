"""Operation handler registry; each handler owns one operation's semantics."""
from .base import OperationHandler
from .registry import get

__all__ = ["OperationHandler", "get"]
