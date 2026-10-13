/**
 * React hook wrapping the browser Speech Synthesis API to speak the assistant's
 * responses.
 *
 * This is output-only and derived entirely from the authoritative conversation
 * response the backend already returns: it never calls the backend and never
 * decides what the assistant should say. Speech is optional and feature
 * detected; when the browser has no synthesis support, or the user mutes it,
 * the hook is a no-op and the text transcript remains the source of truth.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

interface SpeechSynthesisLike {
  speak(utterance: SpeechSynthesisUtterance): void
  cancel(): void
  speaking: boolean
}

function getSpeechSynthesis(): SpeechSynthesisLike | null {
  if (typeof window === 'undefined') {
    return null
  }
  const candidate = window as unknown as { speechSynthesis?: SpeechSynthesisLike }
  return candidate.speechSynthesis ?? null
}

function isSpeechSynthesisSupported(): boolean {
  return (
    getSpeechSynthesis() !== null &&
    typeof SpeechSynthesisUtterance !== 'undefined'
  )
}

export interface UseSpeechSynthesisResult {
  /** Whether the browser can speak at all. */
  supported: boolean
  /** True while an utterance is being spoken. */
  speaking: boolean
  /** Whether the user has muted spoken responses. */
  muted: boolean
  setMuted: (muted: boolean) => void
  speak: (text: string) => void
  cancel: () => void
}

export function useSpeechSynthesis(): UseSpeechSynthesisResult {
  const [supported] = useState(() => isSpeechSynthesisSupported())
  const [speaking, setSpeaking] = useState(false)
  const [muted, setMutedState] = useState(false)
  const mutedRef = useRef(muted)

  useEffect(() => {
    mutedRef.current = muted
  }, [muted])

  const cancel = useCallback(() => {
    getSpeechSynthesis()?.cancel()
    setSpeaking(false)
  }, [])

  const speak = useCallback(
    (text: string) => {
      if (!supported || mutedRef.current) {
        return
      }
      const synthesis = getSpeechSynthesis()
      if (!synthesis || typeof SpeechSynthesisUtterance === 'undefined') {
        return
      }
      const trimmed = text.trim()
      if (!trimmed) {
        return
      }
      synthesis.cancel()
      const utterance = new SpeechSynthesisUtterance(trimmed)
      utterance.lang = navigator.language || 'en-US'
      utterance.onstart = () => setSpeaking(true)
      utterance.onend = () => setSpeaking(false)
      utterance.onerror = () => setSpeaking(false)
      synthesis.speak(utterance)
    },
    [supported],
  )

  const setMuted = useCallback(
    (next: boolean) => {
      setMutedState(next)
      if (next) {
        cancel()
      }
    },
    [cancel],
  )

  useEffect(() => {
    return () => {
      getSpeechSynthesis()?.cancel()
    }
  }, [])

  return { supported, speaking, muted, setMuted, speak, cancel }
}
