import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { jsonResponse, makeScenario } from '../test/fixtures'
import { ScenarioPanel } from './ScenarioPanel'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function scenarioPayload() {
  return {
    current: makeScenario(),
    available: [
      makeScenario(),
      makeScenario({
        scenario: 'TIMEOUT',
        vendor_simulation: { vendor_a_timeout: true },
        description: 'Vendor A submission times out; transaction remains UNKNOWN.',
      }),
    ],
  }
}

describe('ScenarioPanel', () => {
  it('loads scenarios and displays the current scenario and description', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(scenarioPayload())))

    render(<ScenarioPanel />)

    expect(screen.getByText('Loading scenarios…')).toBeInTheDocument()

    const current = (await screen.findByText('Current scenario')).closest(
      '.current-scenario',
    ) as HTMLElement
    expect(within(current).getByText('NORMAL')).toBeInTheDocument()
    expect(
      within(current).getByText(
        'Vendor A available and preferred; normal account balance.',
      ),
    ).toBeInTheDocument()
    expect(screen.getAllByRole('radio')).toHaveLength(2)
  })

  it('selects a scenario through the backend and reports the change', async () => {
    const user = userEvent.setup()
    const changed = makeScenario({ scenario: 'TIMEOUT' })
    const onScenarioChange = vi.fn()
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        return jsonResponse(changed)
      }
      return jsonResponse(scenarioPayload())
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<ScenarioPanel onScenarioChange={onScenarioChange} />)

    const timeoutRadio = await screen.findByRole('radio', { name: /TIMEOUT/ })
    await user.click(timeoutRadio)

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/demo/scenarios',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ scenario: 'TIMEOUT' }),
        }),
      )
    })

    const currentName = document.querySelector('.current-scenario__name')
    expect(currentName).toHaveTextContent('TIMEOUT')
    expect(onScenarioChange).toHaveBeenLastCalledWith(changed)
  })

  it('resets the scenario through the backend', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn(async (url: string) => {
      if (url === '/api/demo/scenarios/reset') {
        return jsonResponse(makeScenario())
      }
      return jsonResponse(scenarioPayload())
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<ScenarioPanel />)

    await screen.findByText('Current scenario')
    await user.click(screen.getByRole('button', { name: /reset to normal/i }))

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/demo/scenarios/reset',
        expect.objectContaining({ method: 'POST' }),
      )
    })
  })

  it('disables selection and reset when the disabled prop is set', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        return jsonResponse(makeScenario({ scenario: 'TIMEOUT' }))
      }
      return jsonResponse(scenarioPayload())
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<ScenarioPanel disabled />)

    const radios = await screen.findAllByRole('radio')
    expect(radios).toHaveLength(2)
    for (const radio of radios) {
      expect(radio).toBeDisabled()
    }

    const reset = screen.getByRole('button', { name: /reset to normal/i })
    expect(reset).toBeDisabled()

    await user.click(radios[1])
    await user.click(reset)

    const postCalls = fetchMock.mock.calls.filter(
      ([, init]) => (init as RequestInit | undefined)?.method === 'POST',
    )
    expect(postCalls).toHaveLength(0)
  })

  it('shows a scenario loading error and recovers on retry', async () => {
    const user = userEvent.setup()
    let attempt = 0
    const fetchMock = vi.fn(async () => {
      attempt += 1
      if (attempt === 1) {
        throw new TypeError('Failed to fetch')
      }
      return jsonResponse(scenarioPayload())
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<ScenarioPanel />)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/could not reach the backend/i)

    await user.click(screen.getByRole('button', { name: /try again/i }))

    expect(
      await screen.findByText('NORMAL', { selector: '.current-scenario__name' }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
