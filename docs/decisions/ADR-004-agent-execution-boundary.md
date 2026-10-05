# ADR-004: Agent Execution Boundary

**Status:** Planned architecture decision; not implemented

## Decision

> LLM reasons; deterministic application controls and executes.

An LLM or agent may propose a structured execution plan. The application must validate that plan before action: capability validation and deterministic policy validation occur before execution.

The agent must not directly call arbitrary vendor APIs, bypass the transaction engine, or bypass the policy layer. Controlled Switcher services and vendor adapters remain the execution boundary.

Planner-visible business operations and deterministic adapter lifecycle are intentionally separated. `ExecutionPlan.steps` represents the planner-visible business operations required for the requested transaction; the planner does not need to reproduce every operation in a vendor's canonical workflow. `Capability.workflow` remains the authoritative description of the vendor's complete execution requirements, while deterministic validation ensures required planner-visible business operations are represented in the plan.

`AUTHENTICATE` is a deterministic adapter/credential responsibility and is not required in the planner's execution plan. `QUERY_TRANSACTION` is a deterministic transaction-status/lifecycle responsibility and is not required in the initial planner execution plan. The deterministic execution and adapter layer remains responsible for those lifecycle and adapter operations.

This ADR locks an architectural boundary for the upcoming agent layer. It does not claim that agent planning, plan validation, or policy enforcement has been implemented.
