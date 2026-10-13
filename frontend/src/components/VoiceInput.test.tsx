import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { VoiceInput } from './VoiceInput'

interface ResultEntry {
  transcript: string
  isFinal: boolean
}

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
  stopped = false
  aborted = false

  constructor() {
    FakeSpeechRecognition.instances.push(this)
  }

  start() {
    this.started = true
  }

  stop() {
    this.stopped = true
  }

  abort() {
    this.aborted = true
  }
}

function makeResults(entries: ResultEntry[]) {
  const list = entries.map((entry) => {
    const alternatives = [
      { transcript: entry.transcript, confidence: 1 },
    ]
    return Object.assign(alternatives, { isFinal: entry.isFinal })
  })
  return Object.assign(list, { item: (index: number) => list[index] })
}

function latest(): FakeSpeechRecognition {
  const instance = FakeSpeechRecognition.instances.at(-1)
  if (!instance) {
    throw new Error('No SpeechRecognition instance was created')
  }
  return instance
}

beforeEach(() => {
  FakeSpeechRecognition.instances = []
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('VoiceInput', () => {
  it('explains when voice input is unsupported instead of rendering a broken control', () => {
    render(<VoiceInput onTranscript={vi.fn()} />)

    expect(
      screen.getByText(/voice input is not supported in this browser/i),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /voice input/i }),
    ).not.toBeInTheDocument()
  })

  it('starts listening and reports the listening state', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('SpeechRecognition', FakeSpeechRecognition)

    render(<VoiceInput onTranscript={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: 'Start voice input' }))

    expect(latest().started).toBe(true)

    act(() => {
      latest().onstart?.()
    })

    expect(screen.getByRole('status')).toHaveTextContent('Listening…')
    expect(
      screen.getByRole('button', { name: 'Done capturing voice input' }),
    ).toBeInTheDocument()
  })

  it('shows the live interim transcript while listening', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('SpeechRecognition', FakeSpeechRecognition)

    render(<VoiceInput onTranscript={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: 'Start voice input' }))
    act(() => {
      latest().onstart?.()
      latest().onresult?.({
        resultIndex: 0,
        results: makeResults([
          { transcript: 'buy five thousand airtime', isFinal: false },
        ]),
      })
    })

    expect(screen.getByRole('status')).toHaveTextContent(
      'buy five thousand airtime',
    )
  })

  it('delivers the finalized transcript and clears the interim state', async () => {
    const user = userEvent.setup()
    const onTranscript = vi.fn()
    vi.stubGlobal('SpeechRecognition', FakeSpeechRecognition)

    render(<VoiceInput onTranscript={onTranscript} />)
    await user.click(screen.getByRole('button', { name: 'Start voice input' }))
    act(() => {
      latest().onstart?.()
      latest().onresult?.({
        resultIndex: 0,
        results: makeResults([
          { transcript: '  Buy MTN airtime for 08030000001  ', isFinal: true },
        ]),
      })
    })

    expect(onTranscript).toHaveBeenCalledWith(
      'Buy MTN airtime for 08030000001',
    )
  })

  it('accumulates digit groups spoken across a pause and restarts recognition', async () => {
    const user = userEvent.setup()
    const onTranscript = vi.fn()
    vi.stubGlobal('SpeechRecognition', FakeSpeechRecognition)

    render(<VoiceInput onTranscript={onTranscript} />)
    await user.click(screen.getByRole('button', { name: 'Start voice input' }))
    act(() => {
      latest().onstart?.()
      latest().onresult?.({
        resultIndex: 0,
        results: makeResults([{ transcript: '0803', isFinal: true }]),
      })
    })
    expect(onTranscript).toHaveBeenCalledWith('0803')

    act(() => {
      latest().onend?.()
    })
    await waitFor(() => expect(FakeSpeechRecognition.instances).toHaveLength(2))

    act(() => {
      latest().onstart?.()
      latest().onresult?.({
        resultIndex: 0,
        results: makeResults([{ transcript: '000 0001', isFinal: true }]),
      })
    })
    expect(onTranscript).toHaveBeenLastCalledWith('0803 000 0001')
  })

  it('preserves digits that were only interim when a pause ended recognition', async () => {
    const user = userEvent.setup()
    const onTranscript = vi.fn()
    vi.stubGlobal('SpeechRecognition', FakeSpeechRecognition)

    render(<VoiceInput onTranscript={onTranscript} />)
    await user.click(screen.getByRole('button', { name: 'Start voice input' }))
    act(() => {
      latest().onstart?.()
      latest().onresult?.({
        resultIndex: 0,
        results: makeResults([{ transcript: '0803', isFinal: false }]),
      })
    })

    act(() => {
      latest().onend?.()
    })
    await waitFor(() => expect(FakeSpeechRecognition.instances).toHaveLength(2))

    act(() => {
      latest().onstart?.()
      latest().onresult?.({
        resultIndex: 0,
        results: makeResults([{ transcript: '000 0001', isFinal: true }]),
      })
    })
    expect(onTranscript).toHaveBeenLastCalledWith('0803 000 0001')
  })

  it('does not duplicate a transcript fragment re-emitted after a restart', async () => {
    const user = userEvent.setup()
    const onTranscript = vi.fn()
    vi.stubGlobal('SpeechRecognition', FakeSpeechRecognition)

    render(<VoiceInput onTranscript={onTranscript} />)
    await user.click(screen.getByRole('button', { name: 'Start voice input' }))
    const emitNumber = () => {
      latest().onresult?.({
        resultIndex: 0,
        results: makeResults([{ transcript: '08030000001', isFinal: true }]),
      })
    }
    act(() => {
      latest().onstart?.()
      emitNumber()
    })

    act(() => {
      latest().onend?.()
    })
    await waitFor(() => expect(FakeSpeechRecognition.instances).toHaveLength(2))

    act(() => {
      latest().onstart?.()
      emitNumber()
    })

    expect(onTranscript).toHaveBeenCalledTimes(1)
    expect(onTranscript).toHaveBeenCalledWith('08030000001')
  })

  it('normalizes a phone number spoken as words and shows it for review', async () => {
    const user = userEvent.setup()
    const onTranscript = vi.fn()
    vi.stubGlobal('SpeechRecognition', FakeSpeechRecognition)

    render(<VoiceInput onTranscript={onTranscript} />)
    await user.click(screen.getByRole('button', { name: 'Start voice input' }))
    act(() => {
      latest().onstart?.()
      latest().onresult?.({
        resultIndex: 0,
        results: makeResults([
          {
            transcript: 'zero eight zero three zero zero zero zero zero zero one',
            isFinal: true,
          },
        ]),
      })
    })

    expect(onTranscript).toHaveBeenCalledWith('08030000001')
    expect(screen.getByText('08030000001')).toBeInTheDocument()
  })

  it('commits the interim digits on Done without submitting', async () => {
    const user = userEvent.setup()
    const onTranscript = vi.fn()
    vi.stubGlobal('SpeechRecognition', FakeSpeechRecognition)

    render(<VoiceInput onTranscript={onTranscript} />)
    await user.click(screen.getByRole('button', { name: 'Start voice input' }))
    act(() => {
      latest().onstart?.()
      latest().onresult?.({
        resultIndex: 0,
        results: makeResults([{ transcript: '0803', isFinal: false }]),
      })
    })

    await user.click(
      screen.getByRole('button', { name: 'Done capturing voice input' }),
    )

    expect(onTranscript).toHaveBeenCalledWith('0803')
  })

  it('reports a denied microphone permission as an error', async () => {
    const user = userEvent.setup()
    const onTranscript = vi.fn()
    vi.stubGlobal('SpeechRecognition', FakeSpeechRecognition)

    render(<VoiceInput onTranscript={onTranscript} />)
    await user.click(screen.getByRole('button', { name: 'Start voice input' }))
    act(() => {
      latest().onerror?.({ error: 'not-allowed', message: 'denied' })
    })

    expect(screen.getByRole('alert')).toHaveTextContent(
      /microphone access was denied/i,
    )
    expect(onTranscript).not.toHaveBeenCalled()
  })

  it('stays silent when recognition is aborted on purpose', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('SpeechRecognition', FakeSpeechRecognition)

    render(<VoiceInput onTranscript={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: 'Start voice input' }))
    act(() => {
      latest().onerror?.({ error: 'aborted', message: '' })
    })

    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('stops recognition when the user toggles the control off', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('SpeechRecognition', FakeSpeechRecognition)

    render(<VoiceInput onTranscript={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: 'Start voice input' }))
    act(() => {
      latest().onstart?.()
    })
    await user.click(
      screen.getByRole('button', { name: 'Done capturing voice input' }),
    )

    expect(latest().stopped).toBe(true)
  })

  it('disables the control when asked', () => {
    vi.stubGlobal('SpeechRecognition', FakeSpeechRecognition)

    render(<VoiceInput onTranscript={vi.fn()} disabled />)

    expect(
      screen.getByRole('button', { name: 'Start voice input' }),
    ).toBeDisabled()
  })

  it('aborts recognition when unmounted', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('SpeechRecognition', FakeSpeechRecognition)

    const { unmount } = render(<VoiceInput onTranscript={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: 'Start voice input' }))
    const recognition = latest()

    unmount()

    expect(recognition.aborted).toBe(true)
  })
})
