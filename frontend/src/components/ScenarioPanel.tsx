import { useCallback, useEffect, useState } from 'react'

import {
  ApiError,
  NetworkError,
  getScenarios,
  resetScenario,
  selectScenario,
} from '../api'
import type { Scenario } from '../types'

interface ScenarioPanelProps {
  onScenarioChange?: (scenario: Scenario) => void
  /**
   * Externally disable scenario controls, e.g. while a chat request is in
   * flight. Prevents a scenario change racing an earlier transaction result.
   */
  disabled?: boolean
}

function describeError(error: unknown): string {
  if (error instanceof NetworkError) {
    return error.message
  }
  if (error instanceof ApiError) {
    return error.message
  }
  return 'Something went wrong while loading demo scenarios.'
}

function conditionSummary(scenario: Scenario): string[] {
  const conditions: string[] = []
  conditions.push(
    scenario.vendor_a_available ? 'Vendor A available' : 'Vendor A unavailable',
  )
  conditions.push(
    scenario.vendor_b_available ? 'Vendor B available' : 'Vendor B unavailable',
  )
  if (scenario.account_balance_override !== null) {
    conditions.push(`Balance override: ${scenario.account_balance_override}`)
  }
  if (scenario.vendor_simulation?.vendor_a_timeout) {
    conditions.push('Vendor A timeout simulated')
  }
  if (scenario.vendor_simulation?.vendor_b_timeout) {
    conditions.push('Vendor B timeout simulated')
  }
  return conditions
}

export function ScenarioPanel({
  onScenarioChange,
  disabled = false,
}: ScenarioPanelProps) {
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [available, setAvailable] = useState<Scenario[]>([])
  const [current, setCurrent] = useState<Scenario | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const applyData = useCallback(
    (data: { current: Scenario; available: Scenario[] }) => {
      setAvailable(data.available)
      setCurrent(data.current)
      setErrorMessage(null)
      onScenarioChange?.(data.current)
    },
    [onScenarioChange],
  )

  useEffect(() => {
    let cancelled = false
    getScenarios()
      .then((data) => {
        if (!cancelled) {
          applyData(data)
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setErrorMessage(describeError(error))
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [applyData])

  function handleRetry() {
    setLoading(true)
    setErrorMessage(null)
    getScenarios()
      .then((data) => applyData(data))
      .catch((error: unknown) => setErrorMessage(describeError(error)))
      .finally(() => setLoading(false))
  }

  async function applyScenario(next: Scenario) {
    setBusy(true)
    setErrorMessage(null)
    try {
      const updated = await selectScenario(next.scenario)
      setCurrent(updated)
      onScenarioChange?.(updated)
    } catch (error) {
      setErrorMessage(describeError(error))
    } finally {
      setBusy(false)
    }
  }

  async function handleReset() {
    setBusy(true)
    setErrorMessage(null)
    try {
      const updated = await resetScenario()
      setCurrent(updated)
      onScenarioChange?.(updated)
    } catch (error) {
      setErrorMessage(describeError(error))
    } finally {
      setBusy(false)
    }
  }

  const controlsDisabled = loading || busy || disabled

  return (
    <section className="card scenario-panel" aria-label="Demo scenario controls">
      <h2>Demo scenario</h2>
      <p className="muted">
        Scenario selection configures backend conditions only. It does not
        execute a transaction.
      </p>

      {loading && (
        <p className="inline-message" role="status">
          Loading scenarios…
        </p>
      )}

      {errorMessage && (
        <div className="inline-message inline-message--error" role="alert">
          <p>{errorMessage}</p>
          <button type="button" className="link-button" onClick={handleRetry}>
            Try again
          </button>
        </div>
      )}

      {current && (
        <div className="current-scenario">
          <h3>Current scenario</h3>
          <p className="current-scenario__name">{current.scenario}</p>
          <p>{current.description}</p>
          <ul className="condition-list">
            {conditionSummary(current).map((condition) => (
              <li key={condition}>{condition}</li>
            ))}
          </ul>
        </div>
      )}

      {!loading && available.length > 0 && (
        <fieldset className="scenario-options" disabled={controlsDisabled}>
          <legend>Select a scenario</legend>
          {available.map((scenario) => {
            const optionId = `scenario-${scenario.scenario}`
            const selected = current?.scenario === scenario.scenario
            return (
              <label
                key={scenario.scenario}
                htmlFor={optionId}
                className={`scenario-option${selected ? ' scenario-option--selected' : ''}`}
              >
                <input
                  id={optionId}
                  type="radio"
                  name="scenario"
                  value={scenario.scenario}
                  checked={selected}
                  onChange={() => void applyScenario(scenario)}
                />
                <span className="scenario-option__body">
                  <span className="scenario-option__name">{scenario.scenario}</span>
                  <span className="scenario-option__description">
                    {scenario.description}
                  </span>
                </span>
              </label>
            )
          })}
        </fieldset>
      )}

      <button
        type="button"
        className="secondary-button"
        onClick={() => void handleReset()}
        disabled={controlsDisabled}
      >
        Reset to NORMAL
      </button>
    </section>
  )
}
