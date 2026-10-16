import { classifyOutcome } from '../outcome'
import type { ConversationResponse } from '../types'
import { ResultPanel } from './ResultPanel'

type StepState =
  | 'pending'
  | 'active'
  | 'done'
  | 'skipped'
  | 'stopped'
  | 'success'
  | 'danger'
  | 'warning'
  | 'neutral'

interface TraceStep {
  label: string
  state: StepState
}

const STEP_STATE_TEXT: Record<StepState, string> = {
  pending: 'not reached',
  active: 'in progress',
  done: 'completed',
  skipped: 'not run',
  stopped: 'stopped',
  success: 'completed',
  danger: 'completed',
  warning: 'completed',
  neutral: 'completed',
}

/**
 * Presentation only: derive the visual progress stages from the existing
 * conversation step and backend result. It reads the same fields the panels
 * below already render and never decides or alters an outcome. A policy denial
 * is shown as the vendor call not having run, matching the backend's own
 * "denied before reaching a vendor" wording.
 */
function deriveSteps(response: ConversationResponse | null): TraceStep[] {
  const labels = ['Request', 'Details', 'Approval', 'Vendor call', 'Result']
  const states: StepState[] = ['pending', 'pending', 'pending', 'pending', 'pending']

  if (response) {
    const result = response.result ?? null
    states[0] = 'done'
    if (result) {
      const outcome = classifyOutcome(result.status)
      states[1] = 'done'
      states[2] = 'done'
      states[3] = outcome.kind === 'denied' ? 'skipped' : 'done'
      states[4] = outcome.tone
    } else if (response.step === 'clarify') {
      states[1] = 'active'
    } else if (response.step === 'confirm') {
      states[1] = 'done'
      states[2] = 'active'
    } else if (response.step === 'cancelled') {
      states[1] = 'done'
      states[2] = 'stopped'
      states[3] = 'skipped'
      states[4] = 'skipped'
    } else {
      states[1] = 'done'
      states[2] = 'done'
      states[3] = 'active'
    }
  }

  return labels.map((label, index) => ({ label, state: states[index] }))
}

function StepIcon({ state }: { state: StepState }) {
  const common = {
    viewBox: '0 0 24 24',
    focusable: false,
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 3,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
  }
  if (state === 'done' || state === 'success') {
    return (
      <svg {...common}>
        <path d="M5 12.5l4.5 4.5L19 7.5" />
      </svg>
    )
  }
  if (state === 'danger' || state === 'stopped') {
    return (
      <svg {...common}>
        <path d="M7 7l10 10M17 7L7 17" />
      </svg>
    )
  }
  if (state === 'warning' || state === 'neutral') {
    return (
      <svg {...common}>
        <path d="M12 6v7M12 18h.01" />
      </svg>
    )
  }
  return null
}

function TraceStepper({ response }: { response: ConversationResponse | null }) {
  const steps = deriveSteps(response)
  return (
    <ol className="trace-stepper" aria-label="Transaction progress">
      {steps.map((step, index) => (
        <li
          key={step.label}
          className="trace-step"
          data-state={step.state}
          data-reached={
            step.state !== 'pending' && step.state !== 'skipped' ? 'true' : 'false'
          }
          aria-current={step.state === 'active' ? 'step' : undefined}
        >
          <span className="trace-step__marker" aria-hidden="true">
            <StepIcon state={step.state} />
          </span>
          <span className="trace-step__label">{step.label}</span>
          <span className="visually-hidden">
            {`step ${index + 1}, ${STEP_STATE_TEXT[step.state]}`}
          </span>
        </li>
      ))}
    </ol>
  )
}

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

      <TraceStepper response={response} />

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
