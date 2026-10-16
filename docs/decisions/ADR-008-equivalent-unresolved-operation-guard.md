# ADR-008: Equivalent unresolved operation guard and status-query failures

## Status
Accepted

## Context
The chat orchestrator generates a new idempotency key for every request, so an
idempotency key alone cannot stop a retry after a timeout from being treated as
a new purchase. Separately, a vendor status query that raised left the
transaction in `INVESTIGATING` and surfaced only an opaque tool error, losing the
transaction id (see ADR-003: an unconfirmed outcome is never a failure).

## Decision
1. **Status-query failure.** `PersistedTransactionExecutionService` catches a
   failing vendor status query, returns the row to `UNKNOWN`, records
   `error_code = STATUS_QUERY_FAILED` (keeping the earlier `error_message`,
   vendor reference and raw vendor response), and logs the exception server-side
   only. Nothing is resubmitted and no terminal outcome is claimed. A later
   successful query resolves the same transaction and clears the code.
2. **Equivalent unresolved guard.** After the existing same-key replay and
   same-key/different-input conflict checks, a request is matched against any
   *non-terminal* transaction with the same normalized `product_type`,
   `network`, `beneficiary` and `amount` (identity excludes idempotency key,
   vendor, ids, timestamps and chat wording). `SUCCESS` and `FAILED` never match,
   so later purchases stay possible. Pre-submission states match too, so
   concurrent equivalent requests join one row instead of each submitting.
3. **Concurrency.** The check-then-insert runs under
   `pg_advisory_xact_lock` keyed on the normalized fields, released by the commit
   or rollback before any vendor call. No schema change: a partial unique index
   would key on uppercase enum names and could not be applied over existing
   duplicate rows.
4. **No rerouting.** A matched operation is reconciled through the vendor that
   owns it (`vendor_execution_service_factory`), never the vendor the new request
   would have chosen. Without a resolver it is returned untouched.
5. **Contract.** The response shape is unchanged. A matched operation returns the
   existing transaction id and its real status, with a message stating that no
   additional purchase was submitted.

## Consequences
- An `UNKNOWN` transaction blocks equivalent purchases until reconciled (no age
  cut-off, by design).
- The number of failed status queries is logged, not persisted.
- Beneficiary formats (e.g. `+234…` vs `0…`) are not normalized.
