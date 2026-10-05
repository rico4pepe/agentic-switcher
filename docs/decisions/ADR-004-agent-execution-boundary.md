# ADR-004: Agent Execution Boundary

**Status:** Planned architecture decision; not implemented

## Decision

> LLM reasons; deterministic application controls and executes.

An LLM or agent may propose a structured execution plan. The application must validate that plan before action: capability validation and deterministic policy validation occur before execution.

The agent must not directly call arbitrary vendor APIs, bypass the transaction engine, or bypass the policy layer. Controlled Switcher services and vendor adapters remain the execution boundary.

This ADR locks an architectural boundary for the upcoming agent layer. It does not claim that agent planning, plan validation, or policy enforcement has been implemented.
