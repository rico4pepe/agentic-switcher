import { useId, useState } from 'react'

import { VOICE_INPUT_ENABLED } from '../config'
import { VoiceInput } from './VoiceInput'

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

  // The single submission routine shared by the Submit button and Enter-to-send,
  // so both go through the exact same handler, validation and request state.
  function submitMessage() {
    if (!canSubmit) {
      return
    }
    setValidationError(null)
    onSubmit(trimmed)
    // Clear the field so the next turn starts from an empty box; the submitted
    // text is preserved in the conversation transcript.
    setMessage('')
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!trimmed) {
      setValidationError('Enter a transaction request before submitting.')
      return
    }
    submitMessage()
  }

  // Enter sends; Shift+Enter keeps the textarea's default newline. This only
  // ever submits through `submitMessage`, which is a no-op when the message is
  // empty/whitespace-only, while a request is in flight, or once the
  // conversation is terminal. It sends free text as an ordinary turn, so it can
  // never authorize a purchase — only the explicit Confirm purchase control does.
  function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== 'Enter' || event.shiftKey) {
      return
    }
    // Respect an in-progress IME composition (for example non-Latin input):
    // Enter commits the composition instead of sending the message.
    if (event.nativeEvent.isComposing) {
      return
    }
    event.preventDefault()
    submitMessage()
  }

  function handleUseExample() {
    setMessage(EXAMPLE_REQUEST)
    setValidationError(null)
  }

  // Voice fills the request field so the user reviews the recognized transcript
  // and submits it through the same path as typed input.
  function handleVoiceTranscript(transcript: string) {
    setMessage(transcript)
    if (validationError) {
      setValidationError(null)
    }
  }

  return (
    // The composer stays compact: a single request field, a short helper line
    // and one send control. It reuses the existing submission handler,
    // validation and request state rather than introducing a new path.
    <form className="transaction-form" onSubmit={handleSubmit} noValidate>
      <label htmlFor={fieldId} className="visually-hidden">
        Your request
      </label>

      <div className="composer__field">
        <textarea
          id={fieldId}
          name="message"
          rows={2}
          maxLength={1000}
          value={message}
          placeholder={EXAMPLE_REQUEST}
          aria-describedby={
            validationError ? `${exampleId} ${errorId}` : exampleId
          }
          aria-invalid={validationError ? true : undefined}
          onChange={(event) => {
            setMessage(event.target.value)
            if (validationError) {
              setValidationError(null)
            }
          }}
          onKeyDown={handleKeyDown}
          disabled={submitting || disabled}
        />

        <button
          type="submit"
          className="primary-button composer__send"
          disabled={!canSubmit}
        >
          <span className="composer__send-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" focusable="false">
              <path
                d="M4 12l14-7-5 14-3-5-6-2z"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            </svg>
          </span>
          {submitting ? 'Submitting…' : 'Submit request'}
        </button>
      </div>

      <p id={exampleId} className="example-hint">
        <span className="muted">Example:</span>
        <code>{EXAMPLE_REQUEST}</code>
        <button
          type="button"
          className="link-button"
          onClick={handleUseExample}
          disabled={submitting || disabled}
        >
          Use example
        </button>
      </p>

      {VOICE_INPUT_ENABLED ? (
        <VoiceInput
          onTranscript={handleVoiceTranscript}
          disabled={submitting || disabled}
        />
      ) : (
        <p className="composer__note">
          Voice input is turned off for this demo. Type your request in the box
          above.
        </p>
      )}

      {validationError && (
        <p id={errorId} className="inline-message inline-message--error" role="alert">
          {validationError}
        </p>
      )}
    </form>
  )
}
