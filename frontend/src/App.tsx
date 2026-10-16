import { useCallback, useEffect, useRef, useState } from 'react'

import './App.css'
import {
  ApiError,
  NetworkError,
  cancelConversation,
  confirmConversation,
  submitChat,
} from './api'
import { finalAssistantMessage, shouldAppendFinalMessage } from './conversation'
import { classifyOutcome } from './outcome'
import { ConversationPanel } from './components/ConversationPanel'
import { MCPActivityPanel } from './components/MCPActivityPanel'
import { ScenarioPanel } from './components/ScenarioPanel'
import { TransactionForm } from './components/TransactionForm'
import { TransactionTrace } from './components/TransactionTrace'
import type { ConversationResponse, Scenario } from './types'
import { useSpeechSynthesis } from './voice/useSpeechSynthesis'

interface Turn {
  role: 'user' | 'assistant'
  text: string
}

type ErrorPhase =
  | 'validation-error'
  | 'network-error'
  | 'unavailable'
  | 'error'

interface ChatError {
  phase: ErrorPhase
  message: string
}

export type ResponseMode = 'text' | 'speech'

/**
 * Describe a finished conversation without implying success. The status mirrors
 * the backend's authoritative outcome; an unconfirmed result is never worded as
 * a success.
 */
function terminalStatusText(response: ConversationResponse): string {
  if (response.step === 'cancelled') {
    return 'Conversation cancelled'
  }
  if (response.result) {
    switch (classifyOutcome(response.result.status).kind) {
      case 'success':
        return 'Transaction succeeded'
      case 'failed':
        return 'Transaction failed'
      case 'denied':
        return 'Transaction denied'
      case 'unknown':
        return 'Outcome not confirmed'
      default:
        return 'Transaction finished'
    }
  }
  return 'Transaction finished'
}

function App() {
  const [scenario, setScenario] = useState<Scenario | null>(null)
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [turns, setTurns] = useState<Turn[]>([])
  const [response, setResponse] = useState<ConversationResponse | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<ChatError | null>(null)
  const hasLoadedInitialScenario = useRef(false)
  // Guards against appending the same terminal outcome more than once if a
  // confirmation is repeated and the backend replays the same result.
  const finalizedConversationId = useRef<string | null>(null)
  // Tracks the last turn that was spoken so a re-render never repeats it.
  const spokenTurnRef = useRef<string | null>(null)
  // The conversation history is its own scroll region. We only follow new
  // messages while the reader is already at (or near) the bottom, so scrolling
  // up to re-read earlier turns is never yanked back by an unrelated render.
  const transcriptRef = useRef<HTMLDivElement | null>(null)
  const stickToBottomRef = useRef(true)

  const {
    supported: speechSupported,
    speaking,
    setMuted,
    speak,
    cancel: cancelSpeech,
  } = useSpeechSynthesis()

  // Preference: text-only responses, or text plus spoken responses. Spoken is
  // the default when the browser supports it so the demo behaves as before;
  // text-only is the fallback otherwise. `spokenTurnRef` marks a turn as
  // consumed even in text mode, so switching modes mid-conversation never
  // re-speaks or duplicates an earlier turn.
  const [responseMode, setResponseMode] = useState<ResponseMode>(() =>
    speechSupported ? 'speech' : 'text',
  )

  useEffect(() => {
    setMuted(responseMode === 'text' || !speechSupported)
  }, [responseMode, speechSupported, setMuted])

  // Speak the authoritative assistant turn (the backend's own prompt or the
  // outcome explanation). Speech is derived from the response; the backend
  // contract is untouched and the text transcript remains authoritative.
  //
  // The dedup key includes the message text, not just the step: every
  // clarification in a conversation shares one conversation id and the
  // `clarify` step, so keying on the step alone would speak only the first
  // acknowledgement/question and silently drop the rest. Each distinct
  // assistant message is spoken exactly once, while re-renders, a replayed
  // outcome, or a repeated question never re-speak.
  useEffect(() => {
    if (!response) {
      return
    }

    const message =
      response.step === 'complete' || response.step === 'cancelled'
        ? finalAssistantMessage(response)
        : response.step === 'clarify' || response.step === 'confirm'
          ? response.prompt
          : null
    if (!message) {
      return
    }

    const turnKey = `${response.conversation_id}:${response.step}:${message}`
    if (spokenTurnRef.current === turnKey) {
      return
    }
    spokenTurnRef.current = turnKey
    speak(message)
  }, [response, speak])

  // Record whether the reader is parked at the bottom of the history. A small
  // threshold keeps a message that is only a few pixels off-screen "at the
  // bottom" so the follow behaviour feels natural.
  const handleTranscriptScroll = useCallback(() => {
    const element = transcriptRef.current
    if (!element) {
      return
    }
    const distanceFromBottom =
      element.scrollHeight - element.scrollTop - element.clientHeight
    stickToBottomRef.current = distanceFromBottom <= 48
  }, [])

  // Follow the latest message only when the reader is already at the bottom.
  // The newest message/card is already in the DOM by the time a passive effect
  // runs, so this keeps it visible without fighting a deliberate scroll-up.
  useEffect(() => {
    const element = transcriptRef.current
    if (!element || !stickToBottomRef.current) {
      return
    }
    element.scrollTop = element.scrollHeight
  }, [turns, pending, error, response])

  // A real scenario change starts a fresh conversation so a stale result is
  // never mistaken for the newly selected scenario's outcome, and a completed
  // conversation id is never reused. A failed scenario change never reaches
  // this callback, so the previous outcome stays.
  const handleScenarioChange = useCallback(
    (next: Scenario) => {
      if (hasLoadedInitialScenario.current) {
        setConversationId(null)
        setTurns([])
        setResponse(null)
        setError(null)
        finalizedConversationId.current = null
        spokenTurnRef.current = null
        stickToBottomRef.current = true
        cancelSpeech()
      }
      hasLoadedInitialScenario.current = true
      setScenario(next)
    },
    [cancelSpeech],
  )

  function applyResponse(next: ConversationResponse) {
    setConversationId(next.conversation_id)
    setResponse(next)
    if (shouldAppendFinalMessage(finalizedConversationId.current, next)) {
      finalizedConversationId.current = next.conversation_id
      const finalMessage = finalAssistantMessage(next)
      if (finalMessage) {
        setTurns((current) => [
          ...current,
          { role: 'assistant', text: finalMessage },
        ])
      }
    } else if (next.step !== 'complete' && next.step !== 'cancelled') {
      setTurns((current) => [
        ...current,
        { role: 'assistant', text: next.prompt },
      ])
    }
  }

  function applyError(caught: unknown) {
    if (caught instanceof NetworkError) {
      setError({ phase: 'network-error', message: caught.message })
    } else if (caught instanceof ApiError) {
      setError({
        phase:
          caught.status === 400 || caught.status === 422
            ? 'validation-error'
            : caught.status === 503
              ? 'unavailable'
              : 'error',
        message: caught.message,
      })
    } else {
      setError({
        phase: 'error',
        message: 'An unexpected error occurred while submitting the request.',
      })
    }
  }

  async function send(message: string) {
    const trimmed = message.trim()
    if (!trimmed || pending) {
      return
    }
    // An explicit submission always follows its own message to the bottom.
    stickToBottomRef.current = true
    setPending(true)
    setError(null)
    setTurns((current) => [...current, { role: 'user', text: trimmed }])
    try {
      applyResponse(await submitChat(trimmed, conversationId))
    } catch (caught) {
      applyError(caught)
    } finally {
      setPending(false)
    }
  }

  // Confirm/Cancel are button-only: they send an explicit control action, never
  // free text, so a typed "yes" or "cancel" can never execute or cancel. The
  // pending transaction is addressed by its own conversation id.
  async function sendAction(action: 'confirm' | 'cancel') {
    if (!conversationId || pending) {
      return
    }
    stickToBottomRef.current = true
    setPending(true)
    setError(null)
    try {
      const next =
        action === 'confirm'
          ? await confirmConversation(conversationId)
          : await cancelConversation(conversationId)
      applyResponse(next)
    } catch (caught) {
      applyError(caught)
    } finally {
      setPending(false)
    }
  }

  function startNewConversation() {
    setConversationId(null)
    setTurns([])
    setResponse(null)
    setError(null)
    finalizedConversationId.current = null
    spokenTurnRef.current = null
    stickToBottomRef.current = true
    cancelSpeech()
  }

  const terminal =
    response?.step === 'complete' || response?.step === 'cancelled'
  const showPlaceholder = turns.length === 0 && response === null && !error
  const voiceStatus = pending
    ? 'Processing your request'
    : speaking
      ? 'Assistant is speaking'
      : terminal && response
        ? terminalStatusText(response)
        : responseMode === 'speech'
          ? 'Ready'
          : 'Text responses only'

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-header__brand">
          <div className="assistant-identity">
            <span className="assistant-identity__avatar" aria-hidden="true">
              AS
            </span>
            <div>
              <h1>Agentic Switcher</h1>
              <p className="muted">
                The user chooses what. The agent understands how. The Switcher
                determines where. The backend remains authoritative.
              </p>
            </div>
          </div>
          <span className="assistant-identity__tag">
            Simulated assistant · demo environment
          </span>
        </div>
        <div className="app-header__side">
          <div className="app-header__scenario" aria-live="polite">
            <span className="muted">Scenario</span>
            <strong data-testid="header-scenario">
              {scenario ? scenario.scenario : 'loading…'}
            </strong>
          </div>
          <div className="app-header__voice">
            <div className="voice-state-row">
              <span
                className="voice-state"
                data-speaking={speaking}
                data-pending={pending}
                aria-live="polite"
              >
                <span className="voice-state__dot" aria-hidden="true" />
                {voiceStatus}
              </span>
              <span
                className="voice-wave"
                data-speaking={speaking}
                aria-hidden="true"
              >
                <span />
                <span />
                <span />
                <span />
                <span />
              </span>
            </div>
            <fieldset className="response-mode">
              <legend className="response-mode__legend">
                Assistant responses
              </legend>
              <div className="response-mode__options">
                <label className="response-mode__option">
                  <input
                    type="radio"
                    name="response-mode"
                    value="text"
                    checked={responseMode === 'text'}
                    onChange={() => setResponseMode('text')}
                  />
                  <span>Text only</span>
                </label>
                <label
                  className="response-mode__option"
                  data-disabled={!speechSupported}
                >
                  <input
                    type="radio"
                    name="response-mode"
                    value="speech"
                    checked={responseMode === 'speech'}
                    onChange={() => setResponseMode('speech')}
                    disabled={!speechSupported}
                  />
                  <span>Text + spoken</span>
                </label>
              </div>
              {!speechSupported && (
                <p className="response-mode__note">
                  Spoken responses aren't available in this browser.
                </p>
              )}
            </fieldset>
          </div>
        </div>
      </header>

      <main className="app-grid">
        <div className="app-column app-column--conversation">
          <div className="conversation-header">
            <span className="assistant-identity__avatar" aria-hidden="true">
              AS
            </span>
            <div>
              <h2>Assistant</h2>
              <p className="muted">
                Simulated assistant. Describe a transaction in plain language.
              </p>
            </div>
          </div>

          <div
            className="conversation-scroll"
            ref={transcriptRef}
            onScroll={handleTranscriptScroll}
          >
            <div className="result-region" aria-live="polite">
              {showPlaceholder && (
                <section className="conversation-empty" aria-label="No result yet">
                  <h2>No transaction submitted yet</h2>
                  <p className="muted">
                    Describe an airtime purchase below. The assistant will ask
                    for anything missing before executing.
                  </p>
                </section>
              )}

              {turns.length > 0 && (
                <ol className="conversation-transcript" aria-label="Conversation">
                  {turns.map((turn, index) => (
                    <li
                      key={`${index}-${turn.role}`}
                      data-role={turn.role}
                      className={`conversation-turn conversation-turn--${turn.role}`}
                    >
                      <span className="conversation-turn__role">
                        {turn.role === 'user' ? 'You' : 'Assistant'}
                      </span>
                      <div className="conversation-turn__bubble">
                        <span className="conversation-turn__text">
                          {turn.text}
                        </span>
                      </div>
                    </li>
                  ))}
                </ol>
              )}

              {pending && (
                <div
                  className="conversation-typing"
                  role="status"
                  aria-live="polite"
                >
                  <span className="conversation-typing__dots" aria-hidden="true">
                    <span />
                    <span />
                    <span />
                  </span>
                  <span>Submitting request…</span>
                </div>
              )}

              {error && (
                <section
                  className="conversation-error"
                  role="alert"
                  data-error-phase={error.phase}
                >
                  <h3>
                    {error.phase === 'network-error'
                      ? 'Backend unreachable'
                      : error.phase === 'validation-error'
                        ? 'Request could not be accepted'
                        : error.phase === 'unavailable'
                          ? 'Assistant is at capacity'
                          : 'Request failed'}
                  </h3>
                  <p>{error.message}</p>
                  {error.phase === 'network-error' && (
                    <p className="muted">
                      Confirm the backend is running on port 8000 and that the
                      Vite proxy is active.
                    </p>
                  )}
                  {error.phase === 'unavailable' && (
                    <p className="muted">
                      No transaction was started. Please try again shortly.
                    </p>
                  )}
                </section>
              )}

              {response && (
                <ConversationPanel
                  response={response}
                  pending={pending}
                  onConfirm={() => void sendAction('confirm')}
                  onCancel={() => void sendAction('cancel')}
                  onNewConversation={startNewConversation}
                />
              )}
            </div>
          </div>

          <div className="composer">
            <TransactionForm
              onSubmit={(message) => void send(message)}
              submitting={pending}
              disabled={terminal}
            />
          </div>
        </div>

        <div className="app-column app-column--rail">
          <TransactionTrace response={response} />
          <MCPActivityPanel response={response} pending={pending} />
          <ScenarioPanel
            onScenarioChange={handleScenarioChange}
            disabled={pending}
          />
        </div>
      </main>
    </div>
  )
}

export default App
