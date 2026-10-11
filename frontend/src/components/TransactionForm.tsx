import { useId, useState } from 'react'

export const EXAMPLE_REQUEST = 'Buy ₦5,000 MTN airtime for 08030000001.'

interface TransactionFormProps {
  onSubmit: (message: string) => void
  submitting: boolean
  /**
   * Disable input once a conversation is terminal, so a new message cannot be
   * applied to a completed or cancelled conversation.
   */
  disabled?: boolean
}

export function TransactionForm({
  onSubmit,
  submitting,
  disabled = false,
}: TransactionFormProps) {
  const [message, setMessage] = useState('')
  const [validationError, setValidationError] = useState<string | null>(null)
  const fieldId = useId()
  const exampleId = `${fieldId}-example`
  const errorId = `${fieldId}-error`

  const trimmed = message.trim()
  const canSubmit = trimmed.length > 0 && !submitting && !disabled

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!trimmed) {
      setValidationError('Enter a transaction request before submitting.')
      return
    }
    setValidationError(null)
    onSubmit(trimmed)
    // Clear the field so the next turn starts from an empty box; the submitted
    // text is preserved in the conversation transcript.
    setMessage('')
  }

  function handleUseExample() {
    setMessage(EXAMPLE_REQUEST)
    setValidationError(null)
  }

  return (
    <form className="card transaction-form" onSubmit={handleSubmit} noValidate>
      <h2>Transaction request</h2>
      <p className="muted">
        Describe the transaction in plain language. The backend decides policy,
        routing, and the final outcome.
      </p>

      <label htmlFor={fieldId} className="field-label">
        Your request
      </label>
      <textarea
        id={fieldId}
        name="message"
        rows={3}
        maxLength={1000}
        value={message}
        placeholder={EXAMPLE_REQUEST}
        aria-describedby={validationError ? `${exampleId} ${errorId}` : exampleId}
        aria-invalid={validationError ? true : undefined}
        onChange={(event) => {
          setMessage(event.target.value)
          if (validationError) {
            setValidationError(null)
          }
        }}
        disabled={submitting || disabled}
      />

      <p id={exampleId} className="muted example-hint">
        Example: <code>{EXAMPLE_REQUEST}</code>
        <button
          type="button"
          className="link-button"
          onClick={handleUseExample}
          disabled={submitting || disabled}
        >
          Use example
        </button>
      </p>

      {validationError && (
        <p id={errorId} className="inline-message inline-message--error" role="alert">
          {validationError}
        </p>
      )}

      <button type="submit" className="primary-button" disabled={!canSubmit}>
        {submitting ? 'Submitting…' : 'Submit request'}
      </button>
    </form>
  )
}
