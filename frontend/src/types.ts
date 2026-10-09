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

/** Response body of `POST /api/chat`. */
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
