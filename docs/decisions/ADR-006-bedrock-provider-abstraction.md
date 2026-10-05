# ADR-006: Bedrock Provider Abstraction

**Status:** Provider boundary implemented; Bedrock integration planned

## Decision

Introduce an application-level `LLMProvider` abstraction as the boundary between the agent/planner and the underlying model provider. The first concrete implementation will target Amazon Bedrock.

The application-level `LLMProvider` contract is implemented. No concrete provider, Bedrock dependency, SDK integration, or model invocation is implemented at this stage.
