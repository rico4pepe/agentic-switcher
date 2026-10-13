import { findPhoneNumber, normalizeSpokenText } from '../voice/numberWords'
import { useSpeechRecognition } from '../voice/useSpeechRecognition'

interface VoiceInputProps {
  /**
   * Receive the assembled spoken transcript. The transcript fills the existing
   * request field (normalized for spoken number forms) so the user still
   * reviews and submits it through the normal conversation path.
   */
  onTranscript: (transcript: string) => void
  /** Disable the control while a request is in flight or terminal. */
  disabled?: boolean
}

export function VoiceInput({ onTranscript, disabled = false }: VoiceInputProps) {
  const {
    supported,
    listening,
    restarting,
    transcript,
    interimTranscript,
    error,
    start,
    stop,
    reset,
    clearError,
  } = useSpeechRecognition({
    captureMode: true,
    // The field receives a clean, reviewable request; the raw transcript stays
    // visible above so the user can compare what was heard with what will be sent.
    onTranscript: (raw) => onTranscript(normalizeSpokenText(raw)),
  })

  if (!supported) {
    return (
      <p className="voice-input--unsupported">
        Voice input is not supported in this browser; please type your request.
      </p>
    )
  }

  const captured = transcript.trim()
  const phone = findPhoneNumber(captured)
  const state = listening ? 'listening' : restarting ? 'restarting' : captured ? 'ready' : 'idle'

  function handleStart() {
    clearError()
    start()
  }

  return (
    <div className="voice-input" data-state={state}>
      <div className="voice-input__orb" data-active={listening} aria-hidden="true">
        <span className="voice-input__orb-ring" />
      </div>

      <div className="voice-input__body">
        <div className="voice-input__controls">
          {!listening && (
            <button
              type="button"
              className="secondary-button voice-input__button"
              onClick={handleStart}
              disabled={disabled}
              aria-label={captured ? 'Speak again' : 'Start voice input'}
            >
              {captured ? 'Speak again' : 'Speak request'}
            </button>
          )}

          {listening && (
            <button
              type="button"
              className="primary-button voice-input__button"
              onClick={stop}
              disabled={disabled}
              aria-label="Done capturing voice input"
            >
              Done
            </button>
          )}

          {!listening && captured && (
            <button
              type="button"
              className="link-button"
              onClick={reset}
              disabled={disabled}
            >
              Clear
            </button>
          )}
        </div>

        <p className="voice-input__status" role="status" aria-live="polite">
          {listening
            ? restarting
              ? 'Listening… reconnecting after a pause.'
              : interimTranscript
                ? `“${transcript}”`
                : 'Listening… take your time.'
            : captured
              ? 'Captured. Review the request below, then submit.'
              : 'Tap “Speak request” and say your order.'}
        </p>

        {listening && (
          <div className="voice-input__meter" aria-hidden="true">
            <span />
            <span />
            <span />
            <span />
            <span />
          </div>
        )}

        {phone && (
          <p className="voice-input__number">
            Number heard:{' '}
            <span className="mono voice-input__number-value">{phone}</span>
          </p>
        )}

        {captured && (
          <p className="voice-input__transcript">
            <span className="voice-input__transcript-label">Heard</span>
            <span className="voice-input__transcript-text">{captured}</span>
          </p>
        )}

        {error && (
          <p className="inline-message inline-message--error" role="alert">
            {error}
          </p>
        )}
      </div>
    </div>
  )
}
