import { formatAmount } from '../outcome'
import type { ConversationDraft, ConversationResponse } from '../types'

interface ConversationPanelProps {
  response: ConversationResponse
  pending: boolean
  onConfirm: () => void
  onCancel: () => void
  onNewConversation: () => void
}

const FIELD_LABELS: Record<string, string> = {
  intent: 'what to do',
  product: 'product',
  amount: 'amount',
  network: 'network',
  beneficiary: 'phone number',
}

function missingLabel(field: string): string {
  return FIELD_LABELS[field] ?? field.replace(/_/g, ' ')
}

function DraftSummary({ draft }: { draft: ConversationDraft }) {
  return (
    <dl className="conversation-summary">
      <div>
        <dt>Amount</dt>
        <dd>{draft.amount === null ? '—' : formatAmount(draft.amount)}</dd>
      </div>
      <div>
        <dt>Network</dt>
        <dd>{draft.network ?? '—'}</dd>
      </div>
      <div>
        <dt>Beneficiary</dt>
        <dd className="mono">{draft.beneficiary ?? '—'}</dd>
      </div>
    </dl>
  )
}

function NewConversationButton({
  pending,
  onClick,
}: {
  pending: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      className="secondary-button"
      onClick={onClick}
      disabled={pending}
    >
      Start a new conversation
    </button>
  )
}

export function ConversationPanel({
  response,
  pending,
  onConfirm,
  onCancel,
  onNewConversation,
}: ConversationPanelProps) {
  return (
    <section
      className="card conversation-panel"
      data-step={response.step}
      aria-label="Conversation"
    >
      {response.step === 'complete' && (
        <>
          <h2>Transaction finished</h2>
          <p className="muted">
            The outcome and full trace are shown in the transaction trace panel.
          </p>
          <NewConversationButton pending={pending} onClick={onNewConversation} />
        </>
      )}

      {response.step === 'cancelled' && (
        <>
          <h2>Conversation cancelled</h2>
          <p className="muted">
            No transaction was submitted. Start a new conversation to try again.
          </p>
          <NewConversationButton pending={pending} onClick={onNewConversation} />
        </>
      )}

      {response.step === 'clarify' && (
        <>
          <h2>Details needed</h2>
          {response.missing_fields.length > 0 && (
            <ul className="conversation-missing" aria-label="Missing fields">
              {response.missing_fields.map((field) => (
                <li key={field}>{missingLabel(field)}</li>
              ))}
            </ul>
          )}
          {response.draft && <DraftSummary draft={response.draft} />}
        </>
      )}

      {response.step === 'confirm' && (
        <>
          <h2>Confirm purchase</h2>
          {response.draft && <DraftSummary draft={response.draft} />}
          <div className="conversation-actions">
            <button
              type="button"
              className="primary-button"
              onClick={onConfirm}
              disabled={pending}
            >
              Confirm purchase
            </button>
            <button
              type="button"
              className="secondary-button"
              onClick={onCancel}
              disabled={pending}
            >
              Cancel
            </button>
          </div>
        </>
      )}
    </section>
  )
}
