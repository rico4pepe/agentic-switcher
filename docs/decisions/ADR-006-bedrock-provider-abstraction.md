# ADR-006: Bedrock Provider Abstraction

**Status:** Planned 4H architecture decision; not implemented

## Decision

Introduce an application-level `LLMProvider` abstraction as the boundary between the agent/planner and the underlying model provider. The first concrete implementation will target Amazon Bedrock.

No provider abstraction, Bedrock dependency, SDK integration, or model invocation is implemented at this stage.
