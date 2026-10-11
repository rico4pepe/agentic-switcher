import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import { EXAMPLE_REQUEST } from './components/TransactionForm'
import {
  jsonResponse,
  makeConversation,
  makeDraft,
  makeResult,
  makeScenario,
} from './test/fixtures'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function completedConversation() {
  return makeConversation({
    step: 'complete',
    prompt: 'Confirmed. Submitting the transaction.',
    missing_fields: [],
    draft: makeDraft({
      network: 'MTN',
      beneficiary: '08030000001',
      amount: '5000.00',
    }),
    result: makeResult(),
  })
}

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
    const fetchMock = stubBackend(async () =>
      jsonResponse(completedConversation()),
    )

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

  it('submits a message in conversation mode and renders the backend result', async () => {
    const user = userEvent.setup()
    const fetchMock = stubBackend(async () =>
      jsonResponse(completedConversation()),
    )

    render(<App />)

    await user.type(screen.getByLabelText('Your request'), EXAMPLE_REQUEST)
    await user.click(screen.getByRole('button', { name: /submit request/i }))

    expect(
      await screen.findByText('Success', { selector: '.status-badge' }),
    ).toBeInTheDocument()
    const explanation =
      'Your ₦5,000 MTN airtime purchase for 08030000001 was completed successfully through Vendor A.'
    expect(
      within(screen.getByLabelText('Transaction result')).getByText(explanation),
    ).toBeInTheDocument()
    expect(
      screen.getByText(explanation, { selector: '[data-role="assistant"] span' }),
    ).toBeInTheDocument()

    const chatCall = fetchMock.mock.calls.find(([url]) => url === '/api/chat')
    expect(chatCall).toBeDefined()
    const init = chatCall?.[1] as RequestInit
    expect(JSON.parse(String(init.body))).toEqual({
      message: EXAMPLE_REQUEST,
      mode: 'conversation',
    })
  })

  it('clarifies, confirms, and completes without inventing a result', async () => {
    const user = userEvent.setup()
    const calls: Array<Record<string, unknown>> = []
    const sequence = [
      makeConversation({
        step: 'clarify',
        prompt: 'Please add the network and beneficiary.',
        missing_fields: ['network', 'beneficiary'],
        draft: makeDraft({ amount: '5000.00' }),
      }),
      makeConversation({
        step: 'clarify',
        prompt: 'Please add the beneficiary.',
        missing_fields: ['beneficiary'],
        draft: makeDraft({
          network: 'MTN',
          amount: '5000.00',
        }),
      }),
      makeConversation({
        step: 'confirm',
        prompt: 'Confirm the MTN airtime purchase for 08030000001?',
        missing_fields: [],
        draft: makeDraft({
          network: 'MTN',
          beneficiary: '08030000001',
          amount: '5000.00',
        }),
      }),
      completedConversation(),
    ]
    let index = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url === '/api/demo/scenarios') {
          return jsonResponse({
            current: makeScenario(),
            available: [makeScenario()],
          })
        }
        if (url === '/api/chat') {
          calls.push(JSON.parse(String(init?.body)) as Record<string, unknown>)
          return jsonResponse(sequence[index++])
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    render(<App />)

    await user.type(screen.getByLabelText('Your request'), EXAMPLE_REQUEST)
    await user.click(screen.getByRole('button', { name: /submit request/i }))

    expect(await screen.findByText('Details needed')).toBeInTheDocument()
    expect(screen.queryByText('Success')).not.toBeInTheDocument()

    await user.type(screen.getByLabelText('Your request'), 'MTN')
    await user.click(screen.getByRole('button', { name: /submit request/i }))
    expect(await screen.findByText(/Please add the beneficiary/)).toBeInTheDocument()

    await user.type(screen.getByLabelText('Your request'), '08030000001')
    await user.click(screen.getByRole('button', { name: /submit request/i }))
    expect(
      await screen.findByRole('heading', { name: 'Confirm purchase' }),
    ).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /^confirm purchase$/i }))

    expect(
      await screen.findByText('Success', { selector: '.status-badge' }),
    ).toBeInTheDocument()

    expect(calls[0]).toEqual({
      message: EXAMPLE_REQUEST,
      mode: 'conversation',
    })
    expect(calls[1]).toEqual({
      message: 'MTN',
      mode: 'conversation',
      conversation_id: '22222222-2222-2222-2222-222222222222',
    })
    expect(calls[3]).toEqual({
      message: 'confirm',
      mode: 'conversation',
      conversation_id: '22222222-2222-2222-2222-222222222222',
    })
    expect(calls[3]).not.toHaveProperty('transaction_id')
  })

  it('presents an unconfirmed outcome without success wording', async () => {
    const user = userEvent.setup()
    stubBackend(async () =>
      jsonResponse(
        makeConversation({
          step: 'complete',
          prompt: 'Submitted.',
          missing_fields: [],
          draft: makeDraft({
            network: 'MTN',
            beneficiary: '08030000001',
            amount: '5000.00',
          }),
          result: makeResult({
            status: 'unknown',
            transaction_id: null,
            vendor_code: null,
            vendor_reference: null,
            action: null,
            message: 'Outcome could not be confirmed',
            explanation:
              'The backend could not confirm whether the transaction completed.',
          }),
        }),
      ),
    )

    render(<App />)

    await user.type(screen.getByLabelText('Your request'), EXAMPLE_REQUEST)
    await user.click(screen.getByRole('button', { name: /submit request/i }))

    expect(
      await screen.findByText('Outcome unconfirmed', { selector: '.status-badge' }),
    ).toBeInTheDocument()
    expect(screen.queryByText('Success')).not.toBeInTheDocument()
    expect(
      screen.getByText(/could not confirm.*investigate it before any further action/s),
    ).toBeInTheDocument()
    expect(
      screen.queryByText('completed successfully', {
        selector: '[data-role="assistant"] span',
      }),
    ).not.toBeInTheDocument()
  })

  it('reports a policy denial and that no vendor was contacted', async () => {
    const user = userEvent.setup()
    stubBackend(async () =>
      jsonResponse(
        makeConversation({
          step: 'complete',
          prompt: 'Submitted.',
          missing_fields: [],
          draft: makeDraft({
            network: 'MTN',
            beneficiary: '08030000001',
            amount: '5000.00',
          }),
          result: makeResult({
            status: 'denied',
            action: 'deny',
            transaction_id: null,
            vendor_code: null,
            vendor_reference: null,
            reason: 'Insufficient balance',
            message: 'Denied by policy',
            explanation:
              "I couldn't complete your ₦5,000 MTN airtime purchase for 08030000001. Reason: Insufficient balance.",
          }),
        }),
      ),
    )

    render(<App />)

    await user.type(screen.getByLabelText('Your request'), EXAMPLE_REQUEST)
    await user.click(screen.getByRole('button', { name: /submit request/i }))

    expect(
      await screen.findByText('Policy denied', { selector: '.status-badge' }),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/I couldn't complete your ₦5,000 MTN airtime purchase.*No transaction was submitted to a vendor\./s),
    ).toBeInTheDocument()
  })

  it('announces cancellation as a final assistant message', async () => {
    const user = userEvent.setup()
    const calls: Array<Record<string, unknown>> = []
    const sequence = [
      makeConversation({
        step: 'confirm',
        prompt: 'Confirm the MTN airtime purchase for 08030000001?',
        missing_fields: [],
        draft: makeDraft({
          network: 'MTN',
          beneficiary: '08030000001',
          amount: '5000.00',
        }),
      }),
      makeConversation({
        step: 'cancelled',
        prompt: 'Conversation cancelled.',
        missing_fields: [],
        draft: makeDraft({
          network: 'MTN',
          beneficiary: '08030000001',
          amount: '5000.00',
        }),
      }),
    ]
    let index = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url === '/api/demo/scenarios') {
          return jsonResponse({
            current: makeScenario(),
            available: [makeScenario()],
          })
        }
        if (url === '/api/chat') {
          calls.push(JSON.parse(String(init?.body)) as Record<string, unknown>)
          return jsonResponse(sequence[index++])
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    render(<App />)

    await user.type(screen.getByLabelText('Your request'), EXAMPLE_REQUEST)
    await user.click(screen.getByRole('button', { name: /submit request/i }))
    await screen.findByRole('heading', { name: 'Confirm purchase' })

    await user.click(screen.getByRole('button', { name: /^cancel$/i }))

    expect(
      await screen.findByText(/Conversation cancelled\. No purchase was submitted to a vendor\./),
    ).toBeInTheDocument()
    expect(calls[1]).toEqual({
      message: 'cancel',
      mode: 'conversation',
      conversation_id: '22222222-2222-2222-2222-222222222222',
    })
  })

  it('appends exactly one final message and blocks further input after completion', async () => {
    const user = userEvent.setup()
    const sequence = [
      makeConversation({
        step: 'confirm',
        prompt: 'Confirm the MTN airtime purchase for 08030000001?',
        missing_fields: [],
        draft: makeDraft({
          network: 'MTN',
          beneficiary: '08030000001',
          amount: '5000.00',
        }),
      }),
      completedConversation(),
    ]
    let index = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url === '/api/demo/scenarios') {
          return jsonResponse({
            current: makeScenario(),
            available: [makeScenario()],
          })
        }
        if (url === '/api/chat') {
          return jsonResponse(sequence[index++])
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    render(<App />)

    await user.type(screen.getByLabelText('Your request'), EXAMPLE_REQUEST)
    await user.click(screen.getByRole('button', { name: /submit request/i }))
    await screen.findByRole('heading', { name: 'Confirm purchase' })

    await user.click(screen.getByRole('button', { name: /^confirm purchase$/i }))

    const explanation =
      'Your ₦5,000 MTN airtime purchase for 08030000001 was completed successfully through Vendor A.'
    expect(
      await screen.findByText(explanation, {
        selector: '[data-role="assistant"] span',
      }),
    ).toBeInTheDocument()
    expect(
      screen.getAllByText(explanation, {
        selector: '[data-role="assistant"] span',
      }),
    ).toHaveLength(1)

    // Reaching a terminal outcome disables the form, so a completed
    // conversation cannot be replayed through the UI.
    expect(screen.getByLabelText('Your request')).toBeDisabled()
    expect(
      screen.queryByRole('button', { name: /^confirm purchase$/i }),
    ).not.toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /start a new conversation/i }),
    ).toBeInTheDocument()
  })

  it('does not reuse a completed conversation id for a new message', async () => {
    const user = userEvent.setup()
    const calls: Array<Record<string, unknown>> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url === '/api/demo/scenarios') {
          return jsonResponse({
            current: makeScenario(),
            available: [makeScenario()],
          })
        }
        if (url === '/api/chat') {
          calls.push(JSON.parse(String(init?.body)) as Record<string, unknown>)
          return jsonResponse(completedConversation())
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    render(<App />)

    await user.type(screen.getByLabelText('Your request'), EXAMPLE_REQUEST)
    await user.click(screen.getByRole('button', { name: /submit request/i }))
    await screen.findByText('Success', { selector: '.status-badge' })

    await user.click(
      screen.getByRole('button', { name: /start a new conversation/i }),
    )
    await user.type(screen.getByLabelText('Your request'), EXAMPLE_REQUEST)
    await user.click(screen.getByRole('button', { name: /submit request/i }))
    await screen.findByText('Success', { selector: '.status-badge' })

    expect(calls).toHaveLength(2)
    expect(calls[0]).not.toHaveProperty('conversation_id')
    expect(calls[1]).not.toHaveProperty('conversation_id')
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

  it('reports capacity exhaustion without implying a transaction outcome', async () => {
    const user = userEvent.setup()
    stubBackend(async () =>
      jsonResponse(
        { detail: 'The conversation store is at capacity and no eligible conversation can be evicted' },
        503,
      ),
    )

    render(<App />)

    await user.type(screen.getByLabelText('Your request'), EXAMPLE_REQUEST)
    await user.click(screen.getByRole('button', { name: /submit request/i }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Assistant is at capacity')
    expect(alert).toHaveTextContent('No transaction was started')
    expect(screen.queryByText('Success')).not.toBeInTheDocument()
    expect(screen.queryByText('Failed')).not.toBeInTheDocument()
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
        return jsonResponse(completedConversation())
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

    resolveChat(jsonResponse(completedConversation()))

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
