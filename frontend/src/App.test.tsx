import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import { EXAMPLE_REQUEST } from './components/TransactionForm'
import { jsonResponse, makeResult, makeScenario } from './test/fixtures'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function stubBackend(chat: () => Promise<Response>) {
  const fetchMock = vi.fn(async (url: string, _init?: RequestInit) => {
    if (url === '/api/demo/scenarios') {
      return jsonResponse({
        current: makeScenario(),
        available: [makeScenario()],
      })
    }
    if (url === '/api/chat') {
      return chat()
    }
    throw new Error(`Unexpected request: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('App', () => {
  it('cannot submit an empty request', async () => {
    const user = userEvent.setup()
    const fetchMock = stubBackend(async () => jsonResponse(makeResult()))

    render(<App />)

    const submit = screen.getByRole('button', { name: /submit request/i })
    expect(submit).toBeDisabled()

    const textarea = screen.getByLabelText('Your request')
    await user.type(textarea, '    ')
    expect(submit).toBeDisabled()

    await user.clear(textarea)
    await user.type(textarea, EXAMPLE_REQUEST)
    expect(submit).toBeEnabled()

    expect(
      fetchMock.mock.calls.some(([url]) => url === '/api/chat'),
    ).toBe(false)
  })

  it('submits a message and renders the backend result', async () => {
    const user = userEvent.setup()
    const fetchMock = stubBackend(async () => jsonResponse(makeResult()))

    render(<App />)

    await user.type(screen.getByLabelText('Your request'), EXAMPLE_REQUEST)
    await user.click(screen.getByRole('button', { name: /submit request/i }))

    expect(
      await screen.findByText('Success', { selector: '.status-badge' }),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        'Your ₦5,000 MTN airtime purchase for 08030000001 was completed successfully through Vendor A.',
      ),
    ).toBeInTheDocument()

    const chatCall = fetchMock.mock.calls.find(([url]) => url === '/api/chat')
    expect(chatCall).toBeDefined()
    const init = chatCall?.[1] as RequestInit
    expect(JSON.parse(String(init.body))).toEqual({ message: EXAMPLE_REQUEST })
  })

  it('renders a backend validation error without fabricating a result', async () => {
    const user = userEvent.setup()
    stubBackend(async () =>
      jsonResponse({ detail: 'Unsupported product type: data' }, 400),
    )

    render(<App />)

    await user.type(screen.getByLabelText('Your request'), 'Buy data')
    await user.click(screen.getByRole('button', { name: /submit request/i }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Unsupported product type: data')
    expect(screen.queryByText('Success')).not.toBeInTheDocument()
  })

  it('renders a network error state when the backend is unreachable', async () => {
    const user = userEvent.setup()
    stubBackend(async () => {
      throw new TypeError('Failed to fetch')
    })

    render(<App />)

    await user.type(screen.getByLabelText('Your request'), EXAMPLE_REQUEST)
    await user.click(screen.getByRole('button', { name: /submit request/i }))

    expect(await screen.findByText('Backend unreachable')).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.queryByText('Success')).not.toBeInTheDocument()
    })
  })

  function stubScenarioChange(
    onChange: () => Promise<Response>,
  ): ReturnType<typeof vi.fn> {
    const timeout = makeScenario({ scenario: 'TIMEOUT' })
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/demo/scenarios' && init?.method === 'POST') {
        return onChange()
      }
      if (url === '/api/demo/scenarios') {
        return jsonResponse({
          current: makeScenario(),
          available: [makeScenario(), timeout],
        })
      }
      if (url === '/api/chat') {
        return jsonResponse(makeResult())
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    return fetchMock
  }

  it('clears the previous result after a successful scenario change', async () => {
    const user = userEvent.setup()
    stubScenarioChange(async () =>
      jsonResponse(makeScenario({ scenario: 'TIMEOUT' })),
    )

    render(<App />)

    await user.type(screen.getByLabelText('Your request'), EXAMPLE_REQUEST)
    await user.click(screen.getByRole('button', { name: /submit request/i }))
    expect(
      await screen.findByText('Success', { selector: '.status-badge' }),
    ).toBeInTheDocument()

    await user.click(await screen.findByRole('radio', { name: /TIMEOUT/ }))

    await waitFor(() => {
      expect(
        screen.queryByText('Success', { selector: '.status-badge' }),
      ).not.toBeInTheDocument()
    })
    expect(screen.getByText('No transaction submitted yet')).toBeInTheDocument()
    expect(screen.getByTestId('header-scenario')).toHaveTextContent('TIMEOUT')
  })

  it('disables scenario controls while a chat request is pending, then re-enables them', async () => {
    const user = userEvent.setup()
    let resolveChat: (response: Response) => void = () => {}
    const pendingChat = new Promise<Response>((resolve) => {
      resolveChat = resolve
    })
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url === '/api/demo/scenarios') {
          return jsonResponse({
            current: makeScenario(),
            available: [makeScenario(), makeScenario({ scenario: 'TIMEOUT' })],
          })
        }
        if (url === '/api/chat') {
          return pendingChat
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    render(<App />)

    const timeoutRadio = await screen.findByRole('radio', { name: /TIMEOUT/ })
    const reset = screen.getByRole('button', { name: /reset to normal/i })
    expect(timeoutRadio).toBeEnabled()
    expect(reset).toBeEnabled()

    await user.type(screen.getByLabelText('Your request'), EXAMPLE_REQUEST)
    await user.click(screen.getByRole('button', { name: /submit request/i }))

    expect(await screen.findByText('Submitting request…')).toBeInTheDocument()
    expect(timeoutRadio).toBeDisabled()
    expect(reset).toBeDisabled()

    resolveChat(jsonResponse(makeResult()))

    expect(
      await screen.findByText('Success', { selector: '.status-badge' }),
    ).toBeInTheDocument()
    await waitFor(() => {
      expect(timeoutRadio).toBeEnabled()
      expect(reset).toBeEnabled()
    })
  })

  it('keeps the previous result when a scenario change fails', async () => {
    const user = userEvent.setup()
    stubScenarioChange(async () => {
      throw new TypeError('Failed to fetch')
    })

    render(<App />)

    await user.type(screen.getByLabelText('Your request'), EXAMPLE_REQUEST)
    await user.click(screen.getByRole('button', { name: /submit request/i }))
    expect(
      await screen.findByText('Success', { selector: '.status-badge' }),
    ).toBeInTheDocument()

    await user.click(await screen.findByRole('radio', { name: /TIMEOUT/ }))

    const alerts = await screen.findAllByRole('alert')
    expect(
      alerts.some((element) =>
        /could not reach the backend/i.test(element.textContent ?? ''),
      ),
    ).toBe(true)

    expect(
      screen.getByText('Success', { selector: '.status-badge' }),
    ).toBeInTheDocument()
    expect(screen.getByTestId('header-scenario')).toHaveTextContent('NORMAL')
  })
})
