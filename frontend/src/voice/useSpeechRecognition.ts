/**
 * React hook wrapping the browser Web Speech API recognition as a voice-input
 * adapter.
 *
 * In the default one-shot mode the hook finalizes after a single utterance. In
 * capture mode (`captureMode: true`) it is pause tolerant: recognized speech is
 * accumulated across recognition events, an accidental end during a pause is
 * preserved and recognition is restarted, and duplicate fragments produced by a
 * restart are dropped. The hook owns the recognition lifecycle only; it performs
 * no network calls and no transaction logic. The caller decides what to do with
 * the recognized text, which in this app means filling the existing request
 * field so the user still reviews and submits through the normal conversation
 * path.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import {
  describeSpeechError,
  getSpeechRecognitionConstructor,
  type SpeechRecognitionErrorEventLike,
  type SpeechRecognitionEventLike,
  type SpeechRecognitionLike,
} from './speechRecognition'

/** How long to wait before reopening the microphone after a pause ends it. */
const RESTART_DELAY_MS = 300

/** Cap consecutive restarts that produced no speech, so a silent mic cannot loop. */
const MAX_CONSECUTIVE_RESTARTS = 8

/** Errors that can never recover by restarting; stop and surface them. */
const FATAL_ERRORS = new Set([
  'not-allowed',
  'service-not-allowed',
  'audio-capture',
])

export interface UseSpeechRecognitionOptions {
  /** Called whenever the accumulated transcript grows (and once on stop). */
  onTranscript?: (transcript: string) => void
  /**
   * Keep listening across pauses and restart recognition when it ends. Used for
   * dictating phone numbers, which are often spoken in several digit groups.
   */
  captureMode?: boolean
}

export interface UseSpeechRecognitionResult {
  /** Whether the current browser exposes speech recognition at all. */
  supported: boolean
  /** True while the microphone is open and recognition is active. */
  listening: boolean
  /** True while recognition is being reopened after an unexpected end. */
  restarting: boolean
  /** Live, not-yet-final transcript while listening. */
  interimTranscript: string
  /** Accumulated raw transcript (finalized text plus any live interim). */
  transcript: string
  /** User-facing error message, or null when there is none. */
  error: string | null
  start: () => void
  stop: () => void
  reset: () => void
  clearError: () => void
}

interface TranscriptParts {
  interim: string
  final: string
}

function collectTranscript(event: SpeechRecognitionEventLike): TranscriptParts {
  let interim = ''
  let final = ''
  for (let index = event.resultIndex; index < event.results.length; index += 1) {
    const result = event.results[index]
    const transcript = result[0]?.transcript ?? ''
    if (result.isFinal) {
      final += transcript
    } else {
      interim += transcript
    }
  }
  return { interim, final }
}

function normalizeSpace(value: string): string {
  return value.replace(/\s+/g, ' ').trim()
}

/**
 * Append `segment` to `committed` without duplicating it.
 *
 * Recognition can re-emit a final result after a restart, and an interim
 * fragment can overlap an already-finalized one. A re-emitted whole phrase or
 * exact repeat is recognized and ignored; genuinely new digit groups are joined
 * with a single space. Every digit is preserved verbatim, including leading
 * zeros.
 */
function mergeTranscript(committed: string, segment: string): string {
  const base = normalizeSpace(committed)
  const addition = normalizeSpace(segment)
  if (!addition) {
    return base
  }
  if (!base) {
    return addition
  }
  if (base === addition || base.endsWith(addition)) {
    return base
  }
  if (addition.startsWith(base) || addition.includes(base)) {
    return addition
  }
  return `${base} ${addition}`
}

export function useSpeechRecognition(
  options: UseSpeechRecognitionOptions = {},
): UseSpeechRecognitionResult {
  const { onTranscript, captureMode = false } = options
  const [supported] = useState(() => getSpeechRecognitionConstructor() !== null)
  const [listening, setListening] = useState(false)
  const [restarting, setRestarting] = useState(false)
  const [interimTranscript, setInterimTranscript] = useState('')
  const [transcript, setTranscript] = useState('')
  const [error, setError] = useState<string | null>(null)

  const recognitionRef = useRef<SpeechRecognitionLike | null>(null)
  const onTranscriptRef = useRef(onTranscript)
  const captureModeRef = useRef(captureMode)
  const committedRef = useRef('')
  const interimRef = useRef('')
  const lastEmittedRef = useRef('')
  const userStoppedRef = useRef(false)
  const fatalErrorRef = useRef(false)
  const restartTimerRef = useRef<number | null>(null)
  const restartCountRef = useRef(0)
  const mountedRef = useRef(true)
  // A ref indirection breaks the begin <-> restart dependency cycle.
  const beginRef = useRef<() => void>(() => {})

  useEffect(() => {
    onTranscriptRef.current = onTranscript
  }, [onTranscript])

  useEffect(() => {
    captureModeRef.current = captureMode
  }, [captureMode])

  const clearRestartTimer = useCallback(() => {
    if (restartTimerRef.current !== null) {
      window.clearTimeout(restartTimerRef.current)
      restartTimerRef.current = null
    }
  }, [])

  const emit = useCallback((value: string) => {
    const next = normalizeSpace(value)
    if (!next || next === lastEmittedRef.current) {
      return
    }
    lastEmittedRef.current = next
    onTranscriptRef.current?.(next)
  }, [])

  const updateTranscript = useCallback((committed: string, interim: string) => {
    setTranscript(normalizeSpace(`${committed} ${interim}`))
  }, [])

  const scheduleRestart = useCallback(() => {
    if (restartCountRef.current >= MAX_CONSECUTIVE_RESTARTS) {
      setRestarting(false)
      return
    }
    restartCountRef.current += 1
    clearRestartTimer()
    setRestarting(true)
    restartTimerRef.current = window.setTimeout(() => {
      restartTimerRef.current = null
      if (!mountedRef.current || userStoppedRef.current || fatalErrorRef.current) {
        return
      }
      beginRef.current()
    }, RESTART_DELAY_MS)
  }, [clearRestartTimer])

  const beginRecognition = useCallback(() => {
    const Constructor = getSpeechRecognitionConstructor()
    if (!Constructor) {
      setError('Voice input is not supported in this browser.')
      return
    }

    const recognition = new Constructor()
    recognition.lang = navigator.language || 'en-US'
    recognition.continuous = captureModeRef.current
    recognition.interimResults = true
    recognition.maxAlternatives = 1

    recognition.onstart = () => {
      setError(null)
      setRestarting(false)
      setInterimTranscript('')
      interimRef.current = ''
      setListening(true)
    }
    recognition.onresult = (event) => {
      const { interim, final } = collectTranscript(event)
      if (final.trim() || interim.trim()) {
        // Speech arrived, so consecutive-restart counting can reset.
        restartCountRef.current = 0
      }
      if (final.trim()) {
        committedRef.current = mergeTranscript(committedRef.current, final)
        emit(committedRef.current)
      }
      interimRef.current = interim
      setInterimTranscript(interim)
      updateTranscript(committedRef.current, interim)
    }
    recognition.onerror = (event: SpeechRecognitionErrorEventLike) => {
      const message = describeSpeechError(event.error)
      if (message) {
        setError(message)
      }
      setInterimTranscript('')
      interimRef.current = ''
      setListening(false)
      if (FATAL_ERRORS.has(event.error)) {
        fatalErrorRef.current = true
        setRestarting(false)
        clearRestartTimer()
      }
    }
    recognition.onend = () => {
      recognitionRef.current = null
      setListening(false)
      if (!captureModeRef.current) {
        setInterimTranscript('')
        interimRef.current = ''
        return
      }
      if (userStoppedRef.current || fatalErrorRef.current) {
        setRestarting(false)
        return
      }
      // Preserve anything recognized as interim before the pause ended the
      // session; otherwise the last digit group would be lost.
      if (interimRef.current.trim()) {
        committedRef.current = mergeTranscript(committedRef.current, interimRef.current)
        interimRef.current = ''
        setInterimTranscript('')
        emit(committedRef.current)
        updateTranscript(committedRef.current, '')
      }
      scheduleRestart()
    }

    recognitionRef.current = recognition
    try {
      recognition.start()
    } catch {
      recognitionRef.current = null
      setListening(false)
      setRestarting(false)
      setError('Voice input could not be started. Please try again.')
    }
  }, [clearRestartTimer, emit, scheduleRestart, updateTranscript])

  useEffect(() => {
    beginRef.current = beginRecognition
  }, [beginRecognition])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      clearRestartTimer()
      const recognition = recognitionRef.current
      recognitionRef.current = null
      if (recognition) {
        recognition.onstart = null
        recognition.onresult = null
        recognition.onerror = null
        recognition.onend = null
        recognition.abort()
      }
    }
  }, [clearRestartTimer])

  const start = useCallback(() => {
    if (!getSpeechRecognitionConstructor()) {
      setError('Voice input is not supported in this browser.')
      return
    }
    // A recognition instance is already active; ignore a second start.
    if (recognitionRef.current) {
      return
    }
    // Do not let a spoken assistant response talk over the user.
    const synthesis = window.speechSynthesis
    if (synthesis && typeof synthesis.cancel === 'function') {
      synthesis.cancel()
    }
    committedRef.current = ''
    interimRef.current = ''
    lastEmittedRef.current = ''
    userStoppedRef.current = false
    fatalErrorRef.current = false
    restartCountRef.current = 0
    setError(null)
    setTranscript('')
    setInterimTranscript('')
    beginRef.current()
  }, [])

  const stop = useCallback(() => {
    userStoppedRef.current = true
    clearRestartTimer()
    setRestarting(false)
    if (interimRef.current.trim()) {
      committedRef.current = mergeTranscript(committedRef.current, interimRef.current)
      interimRef.current = ''
      setInterimTranscript('')
    }
    emit(committedRef.current)
    updateTranscript(committedRef.current, '')
    const recognition = recognitionRef.current
    if (recognition) {
      try {
        recognition.stop()
      } catch {
        setListening(false)
      }
    } else {
      setListening(false)
    }
  }, [clearRestartTimer, emit, updateTranscript])

  const reset = useCallback(() => {
    userStoppedRef.current = true
    fatalErrorRef.current = true
    clearRestartTimer()
    const recognition = recognitionRef.current
    recognitionRef.current = null
    if (recognition) {
      recognition.onstart = null
      recognition.onresult = null
      recognition.onerror = null
      recognition.onend = null
      try {
        recognition.abort()
      } catch {
        // Ignore: the instance is already being discarded.
      }
    }
    committedRef.current = ''
    interimRef.current = ''
    lastEmittedRef.current = ''
    setTranscript('')
    setInterimTranscript('')
    setListening(false)
    setRestarting(false)
  }, [clearRestartTimer])

  const clearError = useCallback(() => setError(null), [])

  return {
    supported,
    listening,
    restarting,
    interimTranscript,
    transcript,
    error,
    start,
    stop,
    reset,
    clearError,
  }
}
