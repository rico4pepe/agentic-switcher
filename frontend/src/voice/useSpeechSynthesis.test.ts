import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useSpeechSynthesis } from './useSpeechSynthesis'

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

function stubSynthesis() {
  const spoken: FakeUtterance[] = []
  const synthesis = {
    speaking: false,
    speak: vi.fn((utterance: FakeUtterance) => {
      spoken.push(utterance)
      utterance.onstart?.()
    }),
    cancel: vi.fn(),
  }
  vi.stubGlobal('speechSynthesis', synthesis)
  vi.stubGlobal('SpeechSynthesisUtterance', FakeUtterance)
  return { synthesis, spoken }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('useSpeechSynthesis', () => {
  it('speaks the provided text when supported', () => {
    const { spoken } = stubSynthesis()
    const { result } = renderHook(() => useSpeechSynthesis())

    expect(result.current.supported).toBe(true)

    act(() => result.current.speak('Confirm the airtime purchase'))

    expect(spoken).toHaveLength(1)
    expect(spoken[0].text).toBe('Confirm the airtime purchase')
  })

  it('stays silent and cancels when muted', () => {
    const { synthesis, spoken } = stubSynthesis()
    const { result } = renderHook(() => useSpeechSynthesis())

    act(() => result.current.speak('First message'))
    act(() => result.current.setMuted(true))
    act(() => result.current.speak('Second message'))

    expect(spoken).toHaveLength(1)
    expect(synthesis.cancel).toHaveBeenCalled()
  })

  it('reports no support when the browser lacks speech synthesis', () => {
    const { result } = renderHook(() => useSpeechSynthesis())

    expect(result.current.supported).toBe(false)
    act(() => result.current.speak('Nothing should happen'))
  })
})
