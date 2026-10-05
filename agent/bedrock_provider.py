"""AWS Bedrock implementation of the structured LLM provider contract."""

import json
from typing import Mapping, Protocol

import boto3
from botocore.exceptions import BotoCoreError
from pydantic import BaseModel, ValidationError

from agent.llm_provider import StructuredOutput
from apps.api.app.config import Settings, settings


class ConverseClient(Protocol):
    """Minimal Bedrock Runtime client surface used by the provider."""

    def converse(self, **kwargs: object) -> Mapping[str, object]:
        """Send a Converse request and return the Bedrock response."""


class BedrockProviderError(RuntimeError):
    """Raised when Bedrock cannot produce the requested structured output."""


class BedrockProvider:
    """Generate Pydantic-validated structured output with Bedrock Converse."""

    def __init__(
        self,
        client: ConverseClient | None = None,
        *,
        app_settings: Settings | None = None,
    ) -> None:
        config = app_settings or settings
        if not config.bedrock_model_id:
            raise BedrockProviderError(
                "BEDROCK_MODEL_ID must be configured to use BedrockProvider"
            )

        self._model_id = config.bedrock_model_id
        self._client = client or boto3.client(
            "bedrock-runtime",
            region_name=config.aws_region,
        )

    def generate_structured(
        self,
        prompt: str,
        output_model: type[StructuredOutput],
    ) -> StructuredOutput:
        """Generate structured output and validate it with the requested model."""
        schema = output_model.model_json_schema()
        request = {
            "modelId": self._model_id,
            "messages": [
                {
                    "role": "user",
                    "content": [{"text": prompt}],
                }
            ],
            "outputConfig": {
                "textFormat": {
                    "type": "json_schema",
                    "structure": {
                        "jsonSchema": {
                            "name": output_model.__name__,
                            "schema": json.dumps(schema, separators=(",", ":")),
                        }
                    },
                }
            },
        }

        try:
            response = self._client.converse(**request)
        except BotoCoreError as error:
            raise BedrockProviderError(
                "Bedrock Converse request failed"
            ) from error

        response_text = self._extract_response_text(response)
        try:
            payload = json.loads(response_text)
        except json.JSONDecodeError as error:
            raise BedrockProviderError(
                "Bedrock returned malformed JSON structured output"
            ) from error

        try:
            return output_model.model_validate(payload)
        except ValidationError as error:
            raise BedrockProviderError(
                f"Bedrock output did not validate as {output_model.__name__}"
            ) from error

    @staticmethod
    def _extract_response_text(response: Mapping[str, object]) -> str:
        output = response.get("output")
        if not isinstance(output, Mapping):
            raise BedrockProviderError(
                "Bedrock response did not contain an output message"
            )

        message = output.get("message")
        if not isinstance(message, Mapping):
            raise BedrockProviderError(
                "Bedrock response did not contain an output message"
            )

        content = message.get("content")
        if not isinstance(content, list):
            raise BedrockProviderError(
                "Bedrock response did not contain message content"
            )

        text_blocks = [
            block["text"]
            for block in content
            if isinstance(block, Mapping) and isinstance(block.get("text"), str)
        ]
        if not text_blocks:
            raise BedrockProviderError(
                "Bedrock response did not contain structured output text"
            )
        return "".join(text_blocks)
