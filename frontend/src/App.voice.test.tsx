import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import { EXAMPLE_REQUEST } from './components/TransactionForm'
import {
  jsonResponse,
  makeConversation,
  makeDraft,
  makeResult,
  makeScenario,
} from './test/fixtures'

// These tests exercise the speech-recognition capture path, so the demo flag
// that disables the microphone is overridden for this file only.
vi.mock('./config', () => ({ VOICE_INPUT_ENABLED: true }))

class FakeSpeechRecognition {
  static instances: FakeSpeechRecognition[] = []
  lang = ''
  continuous = false
  interimResults = false
  maxAlternatives = 1
  onstart: (() => void) | null = null
  onresult:
    | ((event: { resultIndex: number; results: unknown }) => void)
    | null = null
  onerror: ((event: { error: string; message: string }) => void) | null = null
  onend: (() => void) | null = null
  started = false

  constructor() {
    FakeSpeechRecognition.instances.push(this)
  }

  start() {
    this.started = true
  }

  stop() {}

  abort() {}

  emitResult(transcript: string, isFinal: boolean) {
    const alternative = [{ transcript, confidence: 1 }]
    const result = Object.assign(alternative, { isFinal })
    const results = Object.assign([result], {
      item: (index: number) => [result][index],
    })
    this.onresult?.({ resultIndex: 0, results })
  }

  emitFinal(transcript: string) {
    this.emitResult(transcript, true)
  }

  emitInterim(transcript: string) {
    this.emitResult(transcript, false)
  }
}

function latest(): FakeSpeechRecognition {
  const instance = FakeSpeechRecognition.instances.at(-1)
  if (!instance) {
    throw new Error('No SpeechRecognition instance was created')
  }
  return instance
}

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

function confirmationConversation() {
  return makeConversation({
    step: 'confirm',
    prompt: 'Confirm: buy ₦5,000 MTN airtime for 08030000001?',
    missing_fields: [],
    draft: makeDraft({
      network: 'MTN',
      beneficiary: '08030000001',
      amount: '5000.00',
    }),
    result: null,
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

beforeEach(() => {
  FakeSpeechRecognition.instances = []
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('App voice input', () => {
  it('fills the request field from speech and submits through the normal path', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('SpeechRecognition', FakeSpeechRecognition)
    const fetchMock = stubBackend(async () =>
      jsonResponse(completedConversation()),
    )

    render(<App />)

    await user.click(screen.getByRole('button', { name: 'Start voice input' }))
    act(() => {
      latest().onstart?.()
      latest().emitFinal(EXAMPLE_REQUEST)
    })

    const textarea = screen.getByLabelText('Your request')
    expect(textarea).toHaveValue(EXAMPLE_REQUEST)

    await user.click(screen.getByRole('button', { name: /submit request/i }))

    expect(
      await screen.findByText('Success', { selector: '.status-badge' }),
    ).toBeInTheDocument()

    const chatCall = fetchMock.mock.calls.find(([url]) => url === '/api/chat')
    expect(chatCall).toBeDefined()
    const init = chatCall?.[1] as RequestInit
    expect(JSON.parse(String(init.body))).toEqual({
      message: EXAMPLE_REQUEST,
      mode: 'conversation',
    })
  })

  it('preserves a spaced spoken number verbatim and submits it unchanged', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('SpeechRecognition', FakeSpeechRecognition)
    const fetchMock = stubBackend(async () =>
      jsonResponse(confirmationConversation()),
    )

    render(<App />)

    const spoken = 'Buy ₦5,000 MTN airtime for 0803 000 0001'
    await user.click(screen.getByRole('button', { name: 'Start voice input' }))
    act(() => {
      latest().onstart?.()
      latest().emitFinal(spoken)
    })

    const textarea = screen.getByLabelText('Your request')
    expect(textarea).toHaveValue(spoken)

    await user.click(screen.getByRole('button', { name: /submit request/i }))
    expect(
      await screen.findByRole('heading', { name: 'Confirm purchase' }),
    ).toBeInTheDocument()

    const chatCall = fetchMock.mock.calls.find(([url]) => url === '/api/chat')
    expect(chatCall).toBeDefined()
    const init = chatCall?.[1] as RequestInit
    expect(JSON.parse(String(init.body))).toEqual({
      message: spoken,
      mode: 'conversation',
    })
  })

  it('does not submit until the user clicks Submit, even after Done', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('SpeechRecognition', FakeSpeechRecognition)
    const fetchMock = stubBackend(async () =>
      jsonResponse(confirmationConversation()),
    )

    render(<App />)

    await user.click(screen.getByRole('button', { name: 'Start voice input' }))
    act(() => {
      latest().onstart?.()
      latest().emitFinal('Buy 5000 MTN airtime for 0803 000 0001')
    })
    await user.click(
      screen.getByRole('button', { name: 'Done capturing voice input' }),
    )

    // Capture finished: the field is filled but nothing has been sent yet.
    expect(fetchMock.mock.calls.some(([url]) => url === '/api/chat')).toBe(false)

    await user.click(screen.getByRole('button', { name: /submit request/i }))
    expect(
      await screen.findByRole('heading', { name: 'Confirm purchase' }),
    ).toBeInTheDocument()
  })

  it('lets a partial spoken number be corrected before submitting', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('SpeechRecognition', FakeSpeechRecognition)
    const sequence = [
      makeConversation({
        step: 'clarify',
        prompt: 'To continue, please provide the beneficiary phone number.',
        missing_fields: ['beneficiary'],
        draft: makeDraft({ network: 'MTN', amount: '5000.00' }),
      }),
      confirmationConversation(),
    ]
    let index = 0
    stubBackend(async () => jsonResponse(sequence[index++]))

    render(<App />)

    await user.click(screen.getByRole('button', { name: 'Start voice input' }))
    act(() => {
      latest().onstart?.()
      latest().emitFinal('Buy 5000 MTN airtime for 0803 000')
    })
    await user.click(
      screen.getByRole('button', { name: 'Done capturing voice input' }),
    )
    await user.click(screen.getByRole('button', { name: /submit request/i }))

    expect(await screen.findByText('Details needed')).toBeInTheDocument()

    // Finish the number by typing the remaining digits, then submit again.
    await user.type(screen.getByLabelText('Your request'), ' 0001')
    await user.click(screen.getByRole('button', { name: /submit request/i }))

    expect(
      await screen.findByRole('heading', { name: 'Confirm purchase' }),
    ).toBeInTheDocument()
  })

  it('does not submit or fill the field from an interim result', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('SpeechRecognition', FakeSpeechRecognition)
    const fetchMock = stubBackend(async () =>
      jsonResponse(confirmationConversation()),
    )

    render(<App />)

    await user.click(screen.getByRole('button', { name: 'Start voice input' }))
    act(() => {
      latest().onstart?.()
      latest().emitInterim('0803 000')
    })

    expect(screen.getByLabelText('Your request')).toHaveValue('')
    expect(fetchMock.mock.calls.some(([url]) => url === '/api/chat')).toBe(false)
    expect(screen.getByRole('status')).toHaveTextContent('0803 000')
  })

  it('keeps typed input working when voice input is unsupported', async () => {
    const user = userEvent.setup()
    stubBackend(async () => jsonResponse(completedConversation()))

    render(<App />)

    expect(
      screen.getByText(/voice input is not supported in this browser/i),
    ).toBeInTheDocument()

    await user.type(screen.getByLabelText('Your request'), EXAMPLE_REQUEST)
    await user.click(screen.getByRole('button', { name: /submit request/i }))

    expect(
      await screen.findByText('Success', { selector: '.status-badge' }),
    ).toBeInTheDocument()
  })
})
