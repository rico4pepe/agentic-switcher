import type { ConversationResponse } from '../types'
import { ResultPanel } from './ResultPanel'

interface TransactionTraceProps {
  response: ConversationResponse | null
}

/**
 * The transaction trace panel.
 *
 * It mirrors the authoritative conversation step and, once a transaction has
 * executed, the backend's result. It never decides an outcome: intermediate
 * states are labelled as provisional and the completed result is rendered by
 * `ResultPanel` from the backend's own fields.
 *
 * While the assistant is still collecting details (or waiting for a
 * confirmation) no large, mostly-empty card is rendered: a single compact
 * status line states plainly that no vendor execution has happened yet.
 */
export function TransactionTrace({ response }: TransactionTraceProps) {
  const result = response?.result ?? null
  const step = response?.step ?? null

  return (
    <section className="card trace-panel" aria-label="Transaction trace">
      <div className="trace-panel__heading">
        <h2>Transaction trace</h2>
        <span className="muted">Where the transaction stands right now</span>
      </div>

      {!response && (
        <p className="muted trace-panel__idle">
          The transaction trace will appear here once you describe a request.
          Nothing has been submitted.
        </p>
      )}

      {response && !result && step === 'clarify' && (
        <div className="trace-state" data-trace-state="collecting">
          <span className="trace-state__dot" aria-hidden="true" />
          <p className="trace-state__text">
            <strong className="trace-state__label">Collecting details</strong>{' '}
            The assistant is still gathering what it needs; no transaction has
            been submitted to a vendor.
          </p>
        </div>
      )}

      {response && !result && step === 'confirm' && (
        <div className="trace-state" data-trace-state="awaiting-confirmation">
          <span className="trace-state__dot" aria-hidden="true" />
          <p className="trace-state__text">
            <strong className="trace-state__label">
              Awaiting your confirmation
            </strong>{' '}
            No transaction has been submitted to a vendor yet.
          </p>
        </div>
      )}

      {response && !result && step === 'cancelled' && (
        <div className="trace-state" data-trace-state="cancelled">
          <span className="trace-state__dot" aria-hidden="true" />
          <p className="trace-state__text">
            <strong className="trace-state__label">Cancelled</strong> Before any
            vendor was contacted; no transaction was executed.
          </p>
        </div>
      )}

      {result && <ResultPanel result={result} />}
    </section>
  )
}
