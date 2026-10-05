"""Application contract for structured LLM responses."""

from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel


StructuredOutput = TypeVar("StructuredOutput", bound=BaseModel)


@runtime_checkable
class LLMProvider(Protocol):
    """Provide a Pydantic-validated structured response for planner input."""

    def generate_structured(
        self,
        prompt: str,
        output_model: type[StructuredOutput],
    ) -> StructuredOutput:
        """Generate and validate output against the requested Pydantic model."""
