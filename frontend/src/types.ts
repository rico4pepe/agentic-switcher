/**
 * TypeScript mirrors of the authoritative backend HTTP contracts.
 *
 * These types intentionally describe exactly what the backend returns. The
 * browser never fabricates transaction outcomes; it only renders these values.
 */

export type AgentTransactionStatus =
  | 'created'
  | 'validating'
  | 'validated'
  | 'submitting'
  | 'submitted'
  | 'success'
  | 'failed'
  | 'unknown'
  | 'investigating'
  | 'status_resolved'
  | 'denied'

/**
 * One real MCP tool invocation, sanitized by the backend before it leaves the
 * server. The browser only renders these; it never invents a call, an argument,
 * or a duration.
 */
export interface MCPToolCallEvent {
  sequence: number
  tool: string
  status: 'succeeded' | 'failed'
  arguments: Record<string, unknown>
  result: Record<string, unknown> | null
  error: string | null
  duration_ms: number | null
  transaction_id: string | null
}

/** Response body of `POST /api/chat` in the default execution mode. */
export interface ChatResult {
  transaction_id: string | null
  status: AgentTransactionStatus | string
  service_type: string
  product_type: string
  network: string | null
  beneficiary: string
  amount: string | number
  vendor_code: string | null
  vendor_reference: string | null
  action: 'allow' | 'deny' | null
  reason: string | null
  message: string
  planner_candidate_vendor: string | null
  explanation: string
  /**
   * The real MCP tool calls made while producing this result, in order. Absent
   * only from responses predating this field; an empty array means the backend
   * reported no MCP calls. Never inferred by the browser.
   */
  mcp_events?: MCPToolCallEvent[]
}

/** The bounded conversation steps returned by `POST /api/chat`. */
export type ConversationStep = 'clarify' | 'confirm' | 'complete' | 'cancelled'

/**
 * The airtime fields collected so far. Every value is parser-derived; the
 * browser never invents or edits them.
 */
export interface ConversationDraft {
  service_type: string | null
  product_type: string | null
  network: string | null
  beneficiary: string | null
  amount: string | number | null
}

/**
 * Response body of `POST /api/chat` in conversation mode.
 *
 * `result` is the only place an authoritative transaction outcome appears and
 * is `null` until execution completes. Conversation progress is never encoded
 * as a transaction status.
 */
export interface ConversationResponse {
  conversation_id: string
  step: ConversationStep
  prompt: string
  missing_fields: string[]
  draft: ConversationDraft | null
  result: ChatResult | null
}

/**
 * The five demo scenario names supported by the backend.
 *
 * This mirrors the backend's `DemoScenarioName` enum so scenario types and API
 * calls stay consistent. The backend remains authoritative: it rejects unknown
 * names, and this union does not replace that validation.
 */
export type DemoScenarioName =
  | 'NORMAL'
  | 'VENDOR_A_UNAVAILABLE'
  | 'POLICY_DENIED'
  | 'TIMEOUT'
  | 'PLANNER_A_A_UNAVAILABLE'

/** Vendor simulation conditions armed by a demo scenario. */
export interface VendorSimulation {
  vendor_a_timeout?: boolean
  vendor_b_timeout?: boolean
}

/** The backend conditions armed by a single demo scenario. */
export interface Scenario {
  scenario: DemoScenarioName
  vendor_a_available: boolean
  vendor_b_available: boolean
  account_balance_override: string | null
  vendor_simulation: VendorSimulation
  description: string
}

/** Response body of `GET /api/demo/scenarios`. */
export interface ScenarioListResponse {
  current: Scenario
  available: Scenario[]
}

/** Structured error returned by FastAPI (`{"detail": ...}`). */
export interface ErrorDetail {
  detail?: string | Array<{ msg?: string }>
}
