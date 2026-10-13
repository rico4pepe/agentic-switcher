/**
 * Minimal, dependency-free bindings for the browser's Web Speech API
 * speech-recognition surface.
 *
 * `SpeechRecognition` is non-standard: TypeScript's DOM lib does not declare
 * it, and the constructor is still vendor-prefixed (`webkitSpeechRecognition`)
 * in Chromium. This module isolates feature detection, the small structural
 * types we rely on, and error-code translation so the rest of the app never
 * touches the vendor surface directly.
 *
 * Voice input is an input adapter only: it converts speech to text and hands
 * that text to the existing request field and conversation flow. It never
 * calls the backend, makes routing/policy decisions, or invents outcomes.
 */

export interface SpeechRecognitionAlternativeLike {
  readonly transcript: string
  readonly confidence: number
}

export interface SpeechRecognitionResultLike {
  readonly isFinal: boolean
  readonly length: number
  item(index: number): SpeechRecognitionAlternativeLike
  [index: number]: SpeechRecognitionAlternativeLike
}

export interface SpeechRecognitionResultListLike {
  readonly length: number
  item(index: number): SpeechRecognitionResultLike
  [index: number]: SpeechRecognitionResultLike
}

export interface SpeechRecognitionEventLike extends Event {
  readonly resultIndex: number
  readonly results: SpeechRecognitionResultListLike
}

export interface SpeechRecognitionErrorEventLike extends Event {
  readonly error: string
  readonly message: string
}

export interface SpeechRecognitionLike extends EventTarget {
  lang: string
  continuous: boolean
  interimResults: boolean
  maxAlternatives: number
  start(): void
  stop(): void
  abort(): void
  onstart: ((this: SpeechRecognitionLike, event: Event) => void) | null
  onresult:
    | ((this: SpeechRecognitionLike, event: SpeechRecognitionEventLike) => void)
    | null
  onerror:
    | ((
        this: SpeechRecognitionLike,
        event: SpeechRecognitionErrorEventLike,
      ) => void)
    | null
  onend: ((this: SpeechRecognitionLike, event: Event) => void) | null
}

export interface SpeechRecognitionConstructor {
  new (): SpeechRecognitionLike
}

interface SpeechRecognitionWindow {
  SpeechRecognition?: SpeechRecognitionConstructor
  webkitSpeechRecognition?: SpeechRecognitionConstructor
}

/**
 * Return the vendor speech-recognition constructor.
 *
 * Prefers the standard name and falls back to the Chromium-prefixed one.
 * Returns `null` when the browser does not support voice input, so callers can
 * degrade to typed input instead of failing.
 */
export function getSpeechRecognitionConstructor(): SpeechRecognitionConstructor | null {
  if (typeof window === 'undefined') {
    return null
  }
  const candidate = window as unknown as SpeechRecognitionWindow
  return candidate.SpeechRecognition ?? candidate.webkitSpeechRecognition ?? null
}

/**
 * Translate a Web Speech API error code into a short, user-facing message.
 *
 * Returns `null` for codes that should stay silent. `aborted` is produced when
 * we deliberately stop recognition and is not an error worth surfacing.
 */
export function describeSpeechError(code: string): string | null {
  switch (code) {
    case 'aborted':
      return null
    case 'not-allowed':
    case 'service-not-allowed':
      return 'Microphone access was denied. Allow microphone permission and try again.'
    case 'no-speech':
      return 'No speech was detected. Try speaking again.'
    case 'audio-capture':
      return 'No microphone was found. Check that a microphone is connected.'
    case 'network':
      return 'Voice recognition needs a network connection and could not reach the service.'
    default:
      return 'Voice input stopped unexpectedly. Please try again.'
  }
}
