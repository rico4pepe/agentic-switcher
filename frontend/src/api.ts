/**
 * Thin HTTP client for the Agentic Switcher backend.
 *
 * The browser may only send a natural-language `message` to `/api/chat` and a
 * bounded scenario name to `/api/demo/scenarios`. It never sends vendor
 * choices, idempotency keys, balances, or statuses.
 *
 * Requests use relative `/api/...` paths so Vite's development proxy forwards
 * them to FastAPI on port 8000. `VITE_API_BASE_URL` is only needed when the
 * app is served separately from the backend.
 */

import type {
  ChatResult,
  DemoScenarioName,
  ErrorDetail,
  Scenario,
  ScenarioListResponse,
} from './types'

const API_BASE_URL: string = (import.meta.env.VITE_API_BASE_URL ?? '').replace(
  /\/+$/,
  '',
)

/** Raised when the backend could not be reached at all. */
export class NetworkError extends Error {
  constructor(message = 'Could not reach the backend service.') {
    super(message)
    this.name = 'NetworkError'
  }
}

/** Raised when the backend responds with a non-2xx status. */
export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

function apiUrl(path: string): string {
  return `${API_BASE_URL}${path}`
}

async function extractErrorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as ErrorDetail
    const detail = body.detail
    if (typeof detail === 'string' && detail.trim()) {
      return detail
    }
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) =>
          item && typeof item.msg === 'string' ? item.msg : null,
        )
        .filter((message): message is string => Boolean(message))
      if (messages.length > 0) {
        return messages.join(' ')
      }
    }
  } catch {
    // Fall through to a generic message when the body is not JSON.
  }
  return `The backend rejected the request (status ${response.status}).`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(apiUrl(path), {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    })
  } catch {
    throw new NetworkError()
  }

  if (!response.ok) {
    throw new ApiError(response.status, await extractErrorMessage(response))
  }

  try {
    return (await response.json()) as T
  } catch {
    throw new ApiError(
      response.status,
      'The backend returned an unexpected response.',
    )
  }
}

/** Submit a natural-language transaction request. */
export function submitChat(message: string): Promise<ChatResult> {
  return request<ChatResult>('/api/chat', {
    method: 'POST',
    body: JSON.stringify({ message }),
  })
}

/** Read the active demo scenario and the bounded set of available scenarios. */
export function getScenarios(): Promise<ScenarioListResponse> {
  return request<ScenarioListResponse>('/api/demo/scenarios', {
    method: 'GET',
  })
}

/** Arm a demo scenario by its bounded name. */
export function selectScenario(scenario: DemoScenarioName): Promise<Scenario> {
  return request<Scenario>('/api/demo/scenarios', {
    method: 'POST',
    body: JSON.stringify({ scenario }),
  })
}

/** Restore normal demo conditions. */
export function resetScenario(): Promise<Scenario> {
  return request<Scenario>('/api/demo/scenarios/reset', { method: 'POST' })
}
