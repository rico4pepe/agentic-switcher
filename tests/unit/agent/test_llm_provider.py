"""Tests for the application-facing LLM provider contract."""

import ast
import inspect

import pytest
from pydantic import BaseModel, ValidationError

from agent.llm_provider import LLMProvider


class TransactionSummary(BaseModel):
    """Small structured output used to test provider behavior."""

    transaction_id: str
    state: str


class FakeLLMProvider:
    """Test provider that validates deterministic structured payloads."""

    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def generate_structured(
        self,
        prompt: str,
        output_model: type[TransactionSummary],
    ) -> TransactionSummary:
        return output_model.model_validate(self._payload)


def test_llm_provider_contract_can_be_implemented_by_fake_provider():
    provider = FakeLLMProvider(
        {"transaction_id": "transaction-1", "state": "success"}
    )

    assert isinstance(provider, LLMProvider)


def test_fake_provider_returns_valid_pydantic_structured_model():
    provider = FakeLLMProvider(
        {"transaction_id": "transaction-1", "state": "success"}
    )

    response = provider.generate_structured(
        "Summarize transaction transaction-1.",
        TransactionSummary,
    )

    assert response == TransactionSummary(
        transaction_id="transaction-1",
        state="success",
    )


def test_invalid_structured_output_is_rejected_by_pydantic_validation():
    provider = FakeLLMProvider({"transaction_id": "transaction-1"})

    with pytest.raises(ValidationError):
        provider.generate_structured("Summarize transaction.", TransactionSummary)


def test_llm_provider_contract_has_no_bedrock_or_aws_imports():
    source = inspect.getsource(__import__("agent.llm_provider", fromlist=["*"]))
    imports = ast.parse(source)
    imported_modules = {
        node.module
        for node in ast.walk(imports)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert "boto3" not in imported_modules
    assert not any(module.startswith("botocore") for module in imported_modules)
