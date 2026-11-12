"""Operation handler registry; each handler owns one operation's semantics."""
from tpf2_mcp.services.operations.handlers.base import OperationHandler
from tpf2_mcp.services.operations.handlers.registry import get

__all__ = ["OperationHandler", "get"]
