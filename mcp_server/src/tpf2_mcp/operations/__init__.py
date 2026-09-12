"""Controlled-operation proposal and validation layer.

This package deliberately contains no game write transport until an engine API
has been verified in a dedicated test save.
"""

from .capabilities import capabilities
from .controller import OperationController

__all__ = ["OperationController", "capabilities"]
