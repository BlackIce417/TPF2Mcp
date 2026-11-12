"""Controlled-operation proposal and validation layer.

This package deliberately contains no game write transport until an engine API
has been verified in a dedicated test save.
"""

from tpf2_mcp.services.operations.capabilities import capabilities
from tpf2_mcp.services.operations.controller import OperationController

__all__ = ["OperationController", "capabilities"]
