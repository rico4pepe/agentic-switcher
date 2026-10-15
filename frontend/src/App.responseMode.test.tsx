import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { Mock } from 'vitest'
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

class FakeUtterance {
  text: string
  lang = ''
  onstart: (() => void) | null = null
  onend: (() => void) | null = null
  onerror: (() => void) | null = null

  constructor(text: string) {
    this.text = text
  }
}

interface FakeSynthesis {
  speaking: boolean
  speak: Mock<(utterance: FakeUtterance) => void>
  cancel: Mock<() => void>
}

function stubSpeech() {
  const spoken: FakeUtterance[] = []
  const synthesis: FakeSynthesis = {
    speaking: false,
    cancel: vi.fn(),
    speak: vi.fn((utterance: FakeUtterance) => {
      spoken.push(utterance)
      utterance.onstart?.()
    }),
  }
  vi.stubGlobal('speechSynthesis', synthesis)
  vi.stubGlobal('SpeechSynthesisUtterance', FakeUtterance)
  return { spoken, synthesis }
}

function clarifyConversation() {
  return makeConversation({
    step: 'clarify',
    prompt: 'To continue, please provide the beneficiary phone number.',
    missing_fields: ['beneficiary'],
    draft: makeDraft({ network: 'MTN', amount: '5000.00' }),
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

function chatCalls(fetchMock: ReturnType<typeof stubBackend>) {
  return fetchMock.mock.calls.filter(([url]) => url === '/api/chat')
}

function conversationTurns(): Element[] {
  return Array.from(document.querySelectorAll('.conversation-turn'))
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('response mode preference', () => {
  it('defaults to Text + spoken and speaks the prompt and the final result', async () => {
    const user = userEvent.setup()
    const { spoken, synthesis } = stubSpeech()
    const sequence = [confirmationConversation(), completedConversation()]
    let index = 0
    stubBackend(async () => jsonResponse(sequence[index++]))

    render(<App />)

    expect(screen.getByRole('radio', { name: 'Text + spoken' })).toBeChecked()

    await user.type(screen.getByLabelText('Your request'), EXAMPLE_REQUEST)
    await user.click(screen.getByRole('button', { name: /submit request/i }))

    expect(
      await screen.findByRole('heading', { name: 'Confirm purchase' }),
    ).toBeInTheDocument()
    await waitFor(() => expect(spoken).toHaveLength(1))
    expect(spoken[0]?.text).toBe(
      'Confirm: buy ₦5,000 MTN airtime for 08030000001?',
    )

    await user.click(screen.getByRole('button', { name: 'Confirm purchase' }))

    expect(
      await screen.findByText('Success', { selector: '.status-badge' }),
    ).toBeInTheDocument()
    await waitFor(() => expect(spoken).toHaveLength(2))
    expect(spoken[1]?.text).toBe(
      'Your ₦5,000 MTN airtime purchase for 08030000001 was completed successfully through Vendor A.',
    )
    expect(synthesis.speak).toHaveBeenCalledTimes(2)
  })

  it('shows prompts as text without speaking in Text only mode', async () => {
    const user = userEvent.setup()
    const { synthesis } = stubSpeech()
    const sequence = [confirmationConversation(), completedConversation()]
    let index = 0
    stubBackend(async () => jsonResponse(sequence[index++]))

    render(<App />)

    await user.click(screen.getByRole('radio', { name: 'Text only' }))
    expect(screen.getByRole('radio', { name: 'Text only' })).toBeChecked()

    await user.type(screen.getByLabelText('Your request'), EXAMPLE_REQUEST)
    await user.click(screen.getByRole('button', { name: /submit request/i }))

    expect(
      await screen.findByRole('heading', { name: 'Confirm purchase' }),
    ).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Confirm purchase' }))
    expect(
      await screen.findByText('Success', { selector: '.status-badge' }),
    ).toBeInTheDocument()

    expect(synthesis.speak).not.toHaveBeenCalled()
    // Switching to Text only cancels any in-flight speech.
    expect(synthesis.cancel).toHaveBeenCalled()
  })

  it('switching modes mid-conversation does not reset, duplicate, or re-speak turns', async () => {
    const user = userEvent.setup()
    const { spoken } = stubSpeech()
    const sequence = [clarifyConversation(), confirmationConversation()]
    let index = 0
    const fetchMock = stubBackend(async () => jsonResponse(sequence[index++]))

    render(<App />)

    await user.type(screen.getByLabelText('Your request'), EXAMPLE_REQUEST)
    await user.click(screen.getByRole('button', { name: /submit request/i }))
    expect(await screen.findByText('Details needed')).toBeInTheDocument()

    await waitFor(() => expect(spoken).toHaveLength(1))
    expect(chatCalls(fetchMock)).toHaveLength(1)
    expect(conversationTurns()).toHaveLength(2)

    // Text only: the in-flight/applicable speech is cancelled but nothing else
    // about the conversation changes.
    await user.click(screen.getByRole('radio', { name: 'Text only' }))
    expect(chatCalls(fetchMock)).toHaveLength(1)
    expect(spoken).toHaveLength(1)
    expect(conversationTurns()).toHaveLength(2)
    expect(
      screen.getAllByText('To continue, please provide the beneficiary phone number.'),
    ).toHaveLength(1)

    // Back to Text + spoken: the already-consumed turn is not spoken again.
    await user.click(screen.getByRole('radio', { name: 'Text + spoken' }))
    expect(chatCalls(fetchMock)).toHaveLength(1)
    expect(spoken).toHaveLength(1)
    expect(conversationTurns()).toHaveLength(2)

    // The conversation continues on the same backend conversation.
    await user.type(screen.getByLabelText('Your request'), '08030000001')
    await user.click(screen.getByRole('button', { name: /submit request/i }))
    expect(
      await screen.findByRole('heading', { name: 'Confirm purchase' }),
    ).toBeInTheDocument()

    const calls = chatCalls(fetchMock)
    expect(calls).toHaveLength(2)
    const secondCall = calls[1]
    if (!secondCall) {
      throw new Error('expected second call')
    }
    const init = secondCall[1] as RequestInit
    const body = typeof init.body === 'string' ? init.body : String(init.body)
    expect(JSON.parse(body)).toEqual({
      message: '08030000001',
      mode: 'conversation',
      conversation_id: '22222222-2222-2222-2222-222222222222',
    })
    await waitFor(() => expect(spoken).toHaveLength(2))
    expect(spoken[1]?.text).toBe(
      'Confirm: buy ₦5,000 MTN airtime for 08030000001?',
    )
  })

  it('hides microphone capture in the demo build and explains typing is required', () => {
    stubBackend(async () => jsonResponse(completedConversation()))

    render(<App />)

    expect(
      screen.queryByRole('button', { name: /voice input/i }),
    ).not.toBeInTheDocument()
    expect(
      screen.getByText(/voice input is turned off for this demo/i),
    ).toBeInTheDocument()
  })

  it('disables the spoken option when the browser cannot speak', () => {
    stubBackend(async () => jsonResponse(completedConversation()))

    render(<App />)

    expect(screen.getByRole('radio', { name: 'Text only' })).toBeChecked()
    expect(screen.getByRole('radio', { name: 'Text + spoken' })).toBeDisabled()
    expect(
      screen.getByText(/spoken responses aren't available in this browser/i),
    ).toBeInTheDocument()
  })
})

describe('assistant speech coverage', () => {
  it('speaks every distinct clarification prompt, then the summary, in order', async () => {
    const user = userEvent.setup()
    const { spoken } = stubSpeech()
    const sequence = [
      makeConversation({
        step: 'clarify',
        prompt: 'Happy to help! How much airtime would you like to buy?',
        missing_fields: ['amount', 'network', 'beneficiary'],
        draft: makeDraft(),
      }),
      makeConversation({
        step: 'clarify',
        prompt: 'MTN, got it! How much airtime would you like to buy?',
        missing_fields: ['amount', 'beneficiary'],
        draft: makeDraft({ network: 'MTN' }),
      }),
      makeConversation({
        step: 'clarify',
        prompt:
          '₦5,000, got it! Which phone number should receive the airtime?',
        missing_fields: ['beneficiary'],
        draft: makeDraft({ network: 'MTN', amount: '5000.00' }),
      }),
      confirmationConversation(),
    ]
    let index = 0
    stubBackend(async () => jsonResponse(sequence[index++]))

    render(<App />)

    await user.type(screen.getByLabelText('Your request'), 'Buy airtime')
    await user.click(screen.getByRole('button', { name: /submit request/i }))
    await waitFor(() => expect(spoken).toHaveLength(1))

    await user.type(screen.getByLabelText('Your request'), 'MTN')
    await user.click(screen.getByRole('button', { name: /submit request/i }))
    await waitFor(() => expect(spoken).toHaveLength(2))

    await user.type(screen.getByLabelText('Your request'), '5000')
    await user.click(screen.getByRole('button', { name: /submit request/i }))
    await waitFor(() => expect(spoken).toHaveLength(3))

    await user.type(screen.getByLabelText('Your request'), '08030000001')
    await user.click(screen.getByRole('button', { name: /submit request/i }))
    await waitFor(() => expect(spoken).toHaveLength(4))

    const spokenTexts = spoken.map((utterance) => utterance.text)
    expect(spokenTexts).toEqual([
      'Happy to help! How much airtime would you like to buy?',
      'MTN, got it! How much airtime would you like to buy?',
      '₦5,000, got it! Which phone number should receive the airtime?',
      'Confirm: buy ₦5,000 MTN airtime for 08030000001?',
    ])
    // User messages are never spoken as assistant responses.
    expect(spokenTexts).not.toContain('Buy airtime')
    expect(spokenTexts).not.toContain('5000')
  })

  it('never speaks an identical prompt twice in the same conversation', async () => {
    const user = userEvent.setup()
    const { spoken } = stubSpeech()
    const repeated = makeConversation({
      step: 'clarify',
      prompt: 'How much airtime would you like to buy?',
      missing_fields: ['amount'],
      draft: makeDraft({ network: 'MTN' }),
    })
    const fetchMock = stubBackend(async () => jsonResponse(repeated))

    render(<App />)

    await user.type(screen.getByLabelText('Your request'), 'Buy airtime')
    await user.click(screen.getByRole('button', { name: /submit request/i }))
    await waitFor(() => expect(conversationTurns()).toHaveLength(2))
    await waitFor(() => expect(spoken).toHaveLength(1))

    await user.type(screen.getByLabelText('Your request'), '5000')
    await user.click(screen.getByRole('button', { name: /submit request/i }))
    await waitFor(() => expect(chatCalls(fetchMock)).toHaveLength(2))
    await waitFor(() => expect(conversationTurns()).toHaveLength(4))

    expect(spoken).toHaveLength(1)
  })

  it('speaks the cancellation response', async () => {
    const user = userEvent.setup()
    const { spoken } = stubSpeech()
    const sequence = [
      confirmationConversation(),
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
    stubBackend(async () => jsonResponse(sequence[index++]))

    render(<App />)

    await user.type(screen.getByLabelText('Your request'), EXAMPLE_REQUEST)
    await user.click(screen.getByRole('button', { name: /submit request/i }))
    await waitFor(() => expect(spoken).toHaveLength(1))

    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    await waitFor(() => expect(spoken).toHaveLength(2))
    expect(spoken[1]?.text).toBe(
      'Conversation cancelled. No purchase was submitted to a vendor.',
    )
  })

  it('does not speak before any assistant response arrives', async () => {
    const { synthesis } = stubSpeech()
    stubBackend(async () => jsonResponse(confirmationConversation()))

    render(<App />)

    // The demo scenario has loaded, but the user has not submitted anything.
    expect(
      await screen.findByRole('button', { name: /reset to normal/i }),
    ).toBeInTheDocument()
    expect(synthesis.speak).not.toHaveBeenCalled()
  })

  it('does not speak for a failed request and keeps the transcript authoritative', async () => {
    const user = userEvent.setup()
    const { synthesis } = stubSpeech()
    stubBackend(async () =>
      jsonResponse({ detail: 'Unsupported product type: data' }, 400),
    )

    render(<App />)

    await user.type(screen.getByLabelText('Your request'), 'Buy data')
    await user.click(screen.getByRole('button', { name: /submit request/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Unsupported product type: data',
    )
    expect(synthesis.speak).not.toHaveBeenCalled()
  })

  it('keeps the conversation usable when speech synthesis is unavailable', async () => {
    const user = userEvent.setup()
    stubBackend(async () => jsonResponse(completedConversation()))

    render(<App />)

    expect(screen.getByRole('radio', { name: 'Text only' })).toBeChecked()

    await user.type(screen.getByLabelText('Your request'), EXAMPLE_REQUEST)
    await user.click(screen.getByRole('button', { name: /submit request/i }))

    expect(
      await screen.findByText('Success', { selector: '.status-badge' }),
    ).toBeInTheDocument()
  })
})