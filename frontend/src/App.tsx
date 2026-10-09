import { useCallback, useRef, useState } from 'react'

import './App.css'
import { ApiError, NetworkError, submitChat } from './api'
import { ResultPanel } from './components/ResultPanel'
import { ScenarioPanel } from './components/ScenarioPanel'
import { TransactionForm } from './components/TransactionForm'
import type { ChatResult, Scenario } from './types'

type ChatState =
  | { phase: 'empty' }
  | { phase: 'loading' }
  | { phase: 'validation-error'; message: string }
  | { phase: 'network-error'; message: string }
  | { phase: 'error'; message: string }
  | { phase: 'result'; result: ChatResult }

function App() {
  const [chat, setChat] = useState<ChatState>({ phase: 'empty' })
  const [scenario, setScenario] = useState<Scenario | null>(null)
  const hasLoadedInitialScenario = useRef(false)

  // ScenarioPanel only reports successful scenario changes (and the initial
  // load). Clear any previous transaction result on a real change so a stale
  // outcome is never mistaken for the newly selected scenario's result. A
  // failed scenario change never reaches this callback, so the result stays.
  const handleScenarioChange = useCallback((next: Scenario) => {
    if (hasLoadedInitialScenario.current) {
      setChat((current) =>
        current.phase === 'result' ? { phase: 'empty' } : current,
      )
    }
    hasLoadedInitialScenario.current = true
    setScenario(next)
  }, [])

  async function handleSubmit(message: string) {
    setChat({ phase: 'loading' })
    try {
      const result = await submitChat(message)
      setChat({ phase: 'result', result })
    } catch (error) {
      if (error instanceof NetworkError) {
        setChat({ phase: 'network-error', message: error.message })
      } else if (error instanceof ApiError) {
        if (error.status === 400 || error.status === 422) {
          setChat({ phase: 'validation-error', message: error.message })
        } else {
          setChat({ phase: 'error', message: error.message })
        }
      } else {
        setChat({
          phase: 'error',
          message: 'An unexpected error occurred while submitting the request.',
        })
      }
    }
  }

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
            onSubmit={(message) => void handleSubmit(message)}
            submitting={chat.phase === 'loading'}
          />

          <div className="result-region" aria-live="polite">
            {chat.phase === 'empty' && (
              <section className="card placeholder" aria-label="No result yet">
                <h2>No transaction submitted yet</h2>
                <p className="muted">
                  Enter a request above to see the authoritative backend
                  outcome here.
                </p>
              </section>
            )}

            {chat.phase === 'loading' && (
              <section className="card placeholder" role="status">
                <h2>Submitting request…</h2>
                <p className="muted">Waiting for the backend to respond.</p>
              </section>
            )}

            {(chat.phase === 'validation-error' ||
              chat.phase === 'network-error' ||
              chat.phase === 'error') && (
              <section
                className="card placeholder placeholder--error"
                role="alert"
                data-error-phase={chat.phase}
              >
                <h2>
                  {chat.phase === 'network-error'
                    ? 'Backend unreachable'
                    : chat.phase === 'validation-error'
                      ? 'Request could not be accepted'
                      : 'Request failed'}
                </h2>
                <p>{chat.message}</p>
                {chat.phase === 'network-error' && (
                  <p className="muted">
                    Confirm the backend is running on port 8000 and that the
                    Vite proxy is active.
                  </p>
                )}
              </section>
            )}

            {chat.phase === 'result' && <ResultPanel result={chat.result} />}
          </div>
        </div>

        <div className="app-column">
          <ScenarioPanel
            onScenarioChange={handleScenarioChange}
            disabled={chat.phase === 'loading'}
          />
        </div>
      </main>
    </div>
  )
}

export default App
