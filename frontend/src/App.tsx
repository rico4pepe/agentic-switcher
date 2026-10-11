import { useCallback, useRef, useState } from 'react'

import './App.css'
import { ApiError, NetworkError, submitChat } from './api'
import { finalAssistantMessage, shouldAppendFinalMessage } from './conversation'
import { ConversationPanel } from './components/ConversationPanel'
import { ScenarioPanel } from './components/ScenarioPanel'
import { TransactionForm } from './components/TransactionForm'
import type { ConversationResponse, Scenario } from './types'

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

  // A real scenario change starts a fresh conversation so a stale result is
  // never mistaken for the newly selected scenario's outcome, and a completed
  // conversation id is never reused. A failed scenario change never reaches
  // this callback, so the previous outcome stays.
  const handleScenarioChange = useCallback((next: Scenario) => {
    if (hasLoadedInitialScenario.current) {
      setConversationId(null)
      setTurns([])
      setResponse(null)
      setError(null)
      finalizedConversationId.current = null
    }
    hasLoadedInitialScenario.current = true
    setScenario(next)
  }, [])

  async function send(message: string) {
    const trimmed = message.trim()
    if (!trimmed || pending) {
      return
    }
    setPending(true)
    setError(null)
    setTurns((current) => [...current, { role: 'user', text: trimmed }])
    try {
      const next = await submitChat(trimmed, conversationId)
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
    } catch (caught) {
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
  }

  const terminal =
    response?.step === 'complete' || response?.step === 'cancelled'
  const showPlaceholder = turns.length === 0 && response === null && !error

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <h1>Agentic Switcher</h1>
          <p className="muted">
            The user chooses what. The agent understands how. The Switcher
            determines where. The backend remains authoritative.
          </p>
        </div>
        <div className="app-header__scenario" aria-live="polite">
          <span className="muted">Scenario</span>
          <strong data-testid="header-scenario">
            {scenario ? scenario.scenario : 'loading…'}
          </strong>
        </div>
      </header>

      <main className="app-grid">
        <div className="app-column">
          <TransactionForm
            onSubmit={(message) => void send(message)}
            submitting={pending}
            disabled={terminal}
          />

          <div className="result-region" aria-live="polite">
            {showPlaceholder && (
              <section className="card placeholder" aria-label="No result yet">
                <h2>No transaction submitted yet</h2>
                <p className="muted">
                  Describe an airtime purchase above. The assistant will ask
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
                    <span>{turn.text}</span>
                  </li>
                ))}
              </ol>
            )}

            {pending && (
              <section className="card placeholder" role="status">
                <h2>Submitting request…</h2>
                <p className="muted">Waiting for the backend to respond.</p>
              </section>
            )}

            {error && (
              <section
                className="card placeholder placeholder--error"
                role="alert"
                data-error-phase={error.phase}
              >
                <h2>
                  {error.phase === 'network-error'
                    ? 'Backend unreachable'
                    : error.phase === 'validation-error'
                      ? 'Request could not be accepted'
                      : error.phase === 'unavailable'
                        ? 'Assistant is at capacity'
                        : 'Request failed'}
                </h2>
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
                onConfirm={() => void send('confirm')}
                onCancel={() => void send('cancel')}
                onNewConversation={startNewConversation}
              />
            )}
          </div>
        </div>

        <div className="app-column">
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
