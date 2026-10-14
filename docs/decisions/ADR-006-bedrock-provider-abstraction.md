# ADR-006: Bedrock Provider Abstraction

**Status:** Provider boundary and Bedrock Converse provider implemented; the demo wires a deterministic provider

## Decision

Introduce an application-level `LLMProvider` abstraction as the boundary between the agent/planner and the underlying model provider. The first concrete implementation will target Amazon Bedrock.

The application-level `LLMProvider` contract is implemented, and
`BedrockProvider` (`agent/bedrock_provider.py`, Amazon Bedrock Converse via
`boto3`) implements it and is covered by unit tests. It requires
`BEDROCK_MODEL_ID` (and an AWS region) to be configured. It is **not** wired into
the demo request path: `POST /api/chat` wires the deterministic
`DeterministicPlannerProvider`, so the running demo performs no model inference.
Implementing the provider does not mean the product already uses it.
