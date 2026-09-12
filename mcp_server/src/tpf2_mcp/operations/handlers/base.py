from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any

class OperationHandler(ABC):
    """Boundary between generic lifecycle control and operation semantics."""
    operation_type: str
    @abstractmethod
    def validate_parameters(self, target: dict[str, Any], parameters: dict[str, Any]) -> str | None: ...
    @abstractmethod
    def expected_effect(self, index: Any, target: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]: ...
    @abstractmethod
    def verify_postcondition(self, index: Any, operation: dict[str, Any]) -> dict[str, Any]: ...
