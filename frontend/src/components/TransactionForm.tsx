import { useId, useState } from 'react'

export const EXAMPLE_REQUEST = 'Buy ₦5,000 MTN airtime for 08030000001.'

interface TransactionFormProps {
  onSubmit: (message: string) => void
  submitting: boolean
}

export function TransactionForm({ onSubmit, submitting }: TransactionFormProps) {
  const [message, setMessage] = useState('')
  const [validationError, setValidationError] = useState<string | null>(null)
  const fieldId = useId()
  const exampleId = `${fieldId}-example`
  const errorId = `${fieldId}-error`

  const trimmed = message.trim()
  const canSubmit = trimmed.length > 0 && !submitting

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!trimmed) {
      setValidationError('Enter a transaction request before submitting.')
      return
    }
    setValidationError(null)
    onSubmit(trimmed)
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
        disabled={submitting}
      />

      <p id={exampleId} className="muted example-hint">
        Example: <code>{EXAMPLE_REQUEST}</code>
        <button
          type="button"
          className="link-button"
          onClick={handleUseExample}
          disabled={submitting}
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
