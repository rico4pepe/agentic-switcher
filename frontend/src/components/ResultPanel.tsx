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

export function ResultPanel({ result }: ResultPanelProps) {
  const outcome = classifyOutcome(result.status)

  return (
    <section
      className="card result-panel"
      data-outcome={outcome.kind}
      aria-label="Transaction result"
    >
      <div className="result-header">
        <StatusBadge outcome={outcome} />
        <span className="status-raw">status: {result.status}</span>
      </div>

      <p className="result-explanation">{result.explanation}</p>
      <p className="muted">{outcome.detail}</p>

      <dl className="result-grid">
        <div>
          <dt>Outcome</dt>
          <dd>{outcome.label}</dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>{result.status}</dd>
        </div>
        <div>
          <dt>Transaction ID</dt>
          <dd className="mono">{displayValue(result.transaction_id)}</dd>
        </div>
        <div>
          <dt>Service / Product</dt>
          <dd>
            {displayValue(result.service_type)} / {displayValue(result.product_type)}
          </dd>
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
          <dt>Selected vendor</dt>
          <dd>{vendorValue(result.vendor_code)}</dd>
        </div>
        <div>
          <dt>Planner candidate</dt>
          <dd>{vendorValue(result.planner_candidate_vendor)}</dd>
        </div>
        <div>
          <dt>Action</dt>
          <dd>{displayValue(result.action)}</dd>
        </div>
        <div>
          <dt>Reason</dt>
          <dd>{displayValue(result.reason)}</dd>
        </div>
        <div>
          <dt>Message</dt>
          <dd>{displayValue(result.message)}</dd>
        </div>
        <div>
          <dt>Vendor reference</dt>
          <dd className="mono">{displayValue(result.vendor_reference)}</dd>
        </div>
      </dl>

      <details className="raw-response">
        <summary>Raw backend response</summary>
        <pre>{JSON.stringify(result, null, 2)}</pre>
      </details>
    </section>
  )
}
