/**
 * Thin HTTP client for the Agentic Switcher backend.
 *
 * The browser may only send a natural-language `message` (plus a conversation
 * mode and an opaque conversation id), an explicit `action` control signal that
 * the Confirm/Cancel buttons emit, or a bounded scenario name to
 * `/api/demo/scenarios`. It never sends vendor choices, idempotency keys,
 * balances, or statuses.
 *
 * Requests use relative `/api/...` paths so Vite's development proxy forwards
 * them to FastAPI on port 8000. `VITE_API_BASE_URL` is only needed when the
 * app is served separately from the backend.
 */

import type {
  ConversationResponse,
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

/**
 * Submit a natural-language message in conversation mode.
 *
 * The frontend always opts into conversation mode explicitly; the backend's
 * legacy immediate-execution mode is preserved for other clients. A
 * `conversationId` continues an existing conversation; `null` starts a new one.
 */
export function submitChat(
  message: string,
  conversationId: string | null = null,
): Promise<ConversationResponse> {
  const body: Record<string, string> = { message, mode: 'conversation' }
  if (conversationId) {
    body.conversation_id = conversationId
  }
  return request<ConversationResponse>('/api/chat', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

/** The explicit, button-only control actions for a pending confirmation. */
export type ChatAction = 'confirm' | 'cancel'

/**
 * Send an explicit control action for the pending transaction.
 *
 * This is a distinct channel from `submitChat`: it carries no free text, so a
 * typed message can never be mistaken for a button press. The backend rejects
 * the action unless the conversation is genuinely awaiting confirmation.
 */
function submitAction(
  action: ChatAction,
  conversationId: string,
): Promise<ConversationResponse> {
  return request<ConversationResponse>('/api/chat', {
    method: 'POST',
    body: JSON.stringify({
      action,
      mode: 'conversation',
      conversation_id: conversationId,
    }),
  })
}

/** Confirm the pending transaction (Confirm purchase button). */
export function confirmConversation(
  conversationId: string,
): Promise<ConversationResponse> {
  return submitAction('confirm', conversationId)
}

/** Cancel the pending transaction (Cancel button). */
export function cancelConversation(
  conversationId: string,
): Promise<ConversationResponse> {
  return submitAction('cancel', conversationId)
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
