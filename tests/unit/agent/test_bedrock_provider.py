"""Tests for the AWS Bedrock structured-output provider."""

import json
from decimal import Decimal
from typing import Mapping

import pytest
from botocore.exceptions import BotoCoreError
from pydantic import BaseModel

from agent.bedrock_provider import BedrockProvider, BedrockProviderError
from agent.execution_plan import ExecutionPlan, PlanStep
from apps.api.app.config import Settings


class FakeConverseClient:
    """In-memory stand-in for the Bedrock Runtime Converse client."""

    def __init__(self, response: Mapping[str, object] | None = None) -> None:
        self.response = response
        self.request: dict[str, object] | None = None

    def converse(self, **kwargs: object) -> Mapping[str, object]:
        self.request = kwargs
        if self.response is None:
            raise AssertionError("Fake Converse client requires a response")
        return self.response


def settings(
    *,
    aws_region: str | None = "us-west-2",
    bedrock_model_id: str | None = "test-model-id",
) -> Settings:
    return Settings(
        database_url="sqlite://",
        aws_region=aws_region,
        bedrock_model_id=bedrock_model_id,
    )


def execution_plan_payload() -> dict[str, object]:
    return {
        "intent": "airtime_purchase",
        "service_type": "airtime",
        "product_type": "airtime",
        "network": "MTN",
        "beneficiary": "08030000000",
        "amount": "5000",
        "candidate_vendor": None,
        "steps": ["validate_customer", "execute_transaction"],
    }


def converse_response(text: str) -> dict[str, object]:
    return {
        "output": {
            "message": {
                "content": [{"text": text}],
            }
        }
    }


def test_converse_request_uses_model_id_prompt_and_native_json_schema():
    client = FakeConverseClient(converse_response("{}"))
    provider = BedrockProvider(client, app_settings=settings())

    with pytest.raises(BedrockProviderError, match="did not validate"):
        provider.generate_structured("create a plan", ExecutionPlan)

    assert client.request is not None
    assert client.request["modelId"] == "test-model-id"
    assert client.request["messages"] == [
        {
            "role": "user",
            "content": [{"text": "create a plan"}],
        }
    ]
    output_config = client.request["outputConfig"]
    assert output_config == {
        "textFormat": {
            "type": "json_schema",
            "structure": {
                "jsonSchema": {
                    "name": "ExecutionPlan",
                    "schema": json.dumps(
                        ExecutionPlan.model_json_schema(),
                        separators=(",", ":"),
                    ),
                }
            },
        }
    }


def test_provider_uses_configured_region_and_model_id(monkeypatch):
    calls: list[tuple[str, dict[str, object]]] = []
    client = FakeConverseClient(converse_response(json.dumps(execution_plan_payload())))

    def fake_boto3_client(service_name: str, **kwargs: object) -> FakeConverseClient:
        calls.append((service_name, kwargs))
        return client

    monkeypatch.setattr("agent.bedrock_provider.boto3.client", fake_boto3_client)
    provider = BedrockProvider(app_settings=settings())

    result = provider.generate_structured("request", ExecutionPlan)

    assert calls == [("bedrock-runtime", {"region_name": "us-west-2"})]
    assert result.model_dump()["amount"] == Decimal("5000")
    assert client.request is not None
    assert client.request["modelId"] == "test-model-id"


def test_provider_requires_a_configured_model_id():
    with pytest.raises(BedrockProviderError, match="BEDROCK_MODEL_ID"):
        BedrockProvider(FakeConverseClient(), app_settings=settings(bedrock_model_id=None))


def test_execution_plan_schema_is_generated_from_supplied_model():
    class SmallOutput(BaseModel):
        answer: str

    client = FakeConverseClient(converse_response('{"answer":"ok"}'))
    provider = BedrockProvider(client, app_settings=settings())

    assert provider.generate_structured("prompt", SmallOutput) == SmallOutput(
        answer="ok"
    )
    assert client.request is not None
    text_format = client.request["outputConfig"]["textFormat"]
    schema = json.loads(text_format["structure"]["jsonSchema"]["schema"])
    assert schema == SmallOutput.model_json_schema()


def test_successful_structured_response_returns_execution_plan():
    expected = ExecutionPlan(
        intent="airtime_purchase",
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        beneficiary="08030000000",
        amount=Decimal("5000"),
        steps=(PlanStep.VALIDATE_CUSTOMER, PlanStep.EXECUTE_TRANSACTION),
    )
    provider = BedrockProvider(
        FakeConverseClient(
            converse_response(json.dumps(execution_plan_payload()))
        ),
        app_settings=settings(),
    )

    result = provider.generate_structured("create a plan", ExecutionPlan)

    assert result == expected


def test_malformed_response_text_raises_provider_error():
    provider = BedrockProvider(
        FakeConverseClient(converse_response("{invalid")),
        app_settings=settings(),
    )

    with pytest.raises(BedrockProviderError, match="malformed JSON"):
        provider.generate_structured("create a plan", ExecutionPlan)


def test_invalid_pydantic_output_raises_provider_error():
    provider = BedrockProvider(
        FakeConverseClient(converse_response('{"intent":"missing fields"}')),
        app_settings=settings(),
    )

    with pytest.raises(BedrockProviderError, match="did not validate as ExecutionPlan"):
        provider.generate_structured("create a plan", ExecutionPlan)


def test_unexpected_bedrock_response_shape_raises_provider_error():
    provider = BedrockProvider(
        FakeConverseClient({"unexpected": "response"}),
        app_settings=settings(),
    )

    with pytest.raises(BedrockProviderError, match="did not contain an output message"):
        provider.generate_structured("create a plan", ExecutionPlan)


def test_bedrock_client_error_is_wrapped_with_provider_error():
    class FailingConverseClient:
        def converse(self, **kwargs: object) -> Mapping[str, object]:
            raise BotoCoreError()

    provider = BedrockProvider(
        FailingConverseClient(),
        app_settings=settings(),
    )

    with pytest.raises(BedrockProviderError, match="Converse request failed") as error:
        provider.generate_structured("create a plan", ExecutionPlan)

    assert isinstance(error.value.__cause__, BotoCoreError)
