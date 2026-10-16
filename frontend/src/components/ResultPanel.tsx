import { useId, useState } from 'react'

import { classifyOutcome, formatAmount, vendorName } from '../outcome'
import type { ChatResult } from '../types'
import { StatusBadge } from './StatusBadge'

interface ResultPanelProps {
  result: ChatResult
}

function displayValue(value: string | null | undefined): string {
  return value === null || value === undefined || value === '' ? '—' : value
}

function vendorValue(code: string | null): string {
  const name = vendorName(code)
  if (!name) {
    return '—'
  }
  return code && name !== code ? `${name} (${code})` : name
}

/**
 * Render the backend's authoritative transaction result.
 *
 * While collapsed the panel shows the compact status line — the outcome badge
 * and the raw `status` value, e.g. ``Success · status: success`` — followed by
 * the backend's own outcome message (its authoritative `explanation`, which
 * already states the amount, network/product, beneficiary and selected vendor
 * for a success, and a truthful message for denied, failed and unconfirmed
 * outcomes) and the disclosure control. The detailed technical evidence
 * (outcome, selected vendor, reason, status, amount, network, beneficiary,
 * action, planner candidate, transaction id, vendor reference,
 * service/product, message and the verbatim backend response) lives behind the
 * disclosure and is revealed on demand.
 *
 * Nothing here is inferred: every value comes from the backend result, and a
 * planner candidate is always labelled separately so it is never presented as
 * the selected vendor.
 */
export function ResultPanel({ result }: ResultPanelProps) {
  const outcome = classifyOutcome(result.status)
  const [expanded, setExpanded] = useState(false)
  const detailsId = useId()

  return (
    <section
      className="result-panel"
      data-outcome={outcome.kind}
      aria-label="Transaction result"
    >
      <div className="result-header">
        <StatusBadge outcome={outcome} />
        <span className="status-raw">status: {result.status}</span>
      </div>

      {/* The backend's own outcome message, shown before expansion so the
          result is judge-visible without a click. It is the authoritative
          explanation, not a frontend-composed string. */}
      <p className="result-outcome">{result.explanation}</p>

      <button
        type="button"
        className="trace-disclosure"
        aria-expanded={expanded}
        aria-controls={detailsId}
        onClick={() => setExpanded((value) => !value)}
      >
        <span
          className="trace-disclosure__chevron"
          data-expanded={expanded}
          aria-hidden="true"
        >
          ▸
        </span>
        {expanded ? 'Hide full trace' : 'Show full trace'}
      </button>

      <div
        id={detailsId}
        className="result-details"
        data-expanded={expanded}
        hidden={!expanded}
      >
        <p className="muted">{outcome.detail}</p>

        <dl className="result-summary">
          <div className="result-field result-field--primary">
            <dt>Outcome</dt>
            <dd>{outcome.label}</dd>
          </div>
          <div className="result-field result-field--primary">
            <dt>Selected vendor</dt>
            <dd>{vendorValue(result.vendor_code)}</dd>
            <small className="result-field__note">
              the vendor the Switcher routed to
            </small>
          </div>
          <div className="result-field result-field--primary">
            <dt>Reason</dt>
            <dd>{displayValue(result.reason)}</dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd>{result.status}</dd>
          </div>
          <div>
            <dt>Amount</dt>
            <dd>{formatAmount(result.amount)}</dd>
          </div>
          <div>
            <dt>Network</dt>
            <dd>{displayValue(result.network)}</dd>
          </div>
          <div>
            <dt>Beneficiary</dt>
            <dd className="mono">{displayValue(result.beneficiary)}</dd>
          </div>
          <div>
            <dt>Action</dt>
            <dd>{displayValue(result.action)}</dd>
          </div>
          <div>
            <dt>Planner candidate</dt>
            <dd>{vendorValue(result.planner_candidate_vendor)}</dd>
            <small className="result-field__note">
              the vendor the planner proposed
            </small>
          </div>
          <div>
            <dt>Transaction ID</dt>
            <dd className="mono">{displayValue(result.transaction_id)}</dd>
          </div>
        </dl>

        <dl className="result-grid">
          <div className="result-field result-field--secondary">
            <dt>Vendor reference</dt>
            <dd className="mono">{displayValue(result.vendor_reference)}</dd>
          </div>
          <div className="result-field result-field--secondary">
            <dt>Service / Product</dt>
            <dd>
              {displayValue(result.service_type)} /{' '}
              {displayValue(result.product_type)}
            </dd>
          </div>
          <div className="result-field result-field--secondary">
            <dt>Message</dt>
            <dd>{displayValue(result.message)}</dd>
          </div>
        </dl>

        <details className="raw-response">
          <summary>Raw backend response</summary>
          <pre>{JSON.stringify(result, null, 2)}</pre>
        </details>
      </div>
    </section>
  )
}
