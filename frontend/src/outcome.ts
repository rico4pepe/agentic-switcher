/**
 * Map an authoritative backend status to a presentation outcome.
 *
 * This module only classifies and labels; it never changes the underlying
 * status. In particular, `unknown` is always surfaced as "Outcome unconfirmed"
 * and must never be shown with success styling or success wording.
 */

import type { AgentTransactionStatus } from './types'

export type OutcomeKind =
  | 'success'
  | 'failed'
  | 'denied'
  | 'unknown'
  | 'in_progress'
  | 'unrecognized'

export type OutcomeTone = 'success' | 'danger' | 'warning' | 'neutral'

export interface Outcome {
  kind: OutcomeKind
  /** Human-facing label, e.g. "Outcome unconfirmed". */
  label: string
  tone: OutcomeTone
  /** Short, neutral explanation of what the label means. */
  detail: string
}

/**
 * Statuses the backend may report while a transaction is still in flight. Only
 * these are classified as intermediate; anything else is treated as
 * unrecognized rather than assumed to be progressing (or succeeding).
 */
const INTERMEDIATE_STATUSES: ReadonlySet<string> = new Set([
  'created',
  'validating',
  'validated',
  'submitting',
  'submitted',
  'investigating',
  'status_resolved',
])

export function classifyOutcome(status: string): Outcome {
  switch (status) {
    case 'success':
      return {
        kind: 'success',
        label: 'Success',
        tone: 'success',
        detail: 'The backend confirmed the transaction completed successfully.',
      }
    case 'failed':
      return {
        kind: 'failed',
        label: 'Failed',
        tone: 'danger',
        detail: 'The backend confirmed the transaction failed.',
      }
    case 'denied':
      return {
        kind: 'denied',
        label: 'Policy denied',
        tone: 'warning',
        detail:
          'Policy denied the request before it reached a vendor. No transaction was executed.',
      }
    case 'unknown':
      return {
        kind: 'unknown',
        label: 'Outcome unconfirmed',
        tone: 'neutral',
        detail:
          'The backend could not confirm the outcome. Treat this transaction as pending investigation rather than complete.',
      }
    default:
      if (INTERMEDIATE_STATUSES.has(status)) {
        return {
          kind: 'in_progress',
          label: humanizeStatus(status as AgentTransactionStatus),
          tone: 'neutral',
          detail: 'The backend reported an intermediate state.',
        }
      }
      return {
        kind: 'unrecognized',
        label: 'Unrecognized status',
        tone: 'neutral',
        detail:
          'The backend returned a status this simulator does not recognize, so the outcome cannot be determined.',
      }
  }
}

export function humanizeStatus(status: string): string {
  return status
    .split('_')
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

const KNOWN_VENDOR_NAMES: Record<string, string> = {
  vendor_a: 'Vendor A',
  vendor_b: 'Vendor B',
}

/** Render a vendor code without inferring any routing decision. */
export function vendorName(vendorCode: string | null): string | null {
  if (!vendorCode || !vendorCode.trim()) {
    return null
  }
  const normalized = vendorCode.trim().toLowerCase()
  return (
    KNOWN_VENDOR_NAMES[normalized] ??
    vendorCode
      .replace(/[_-]+/g, ' ')
      .replace(/\b\w/g, (character) => character.toUpperCase())
  )
}

/** Format a backend-provided amount without inventing fractional precision. */
export function formatAmount(amount: string | number): string {
  const numeric = typeof amount === 'number' ? amount : Number(amount)
  if (!Number.isFinite(numeric)) {
    return String(amount)
  }
  const formatted = numeric.toLocaleString('en-US', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  })
  return `₦${formatted}`
}
