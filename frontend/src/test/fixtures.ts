import type {
  ChatResult,
  ConversationDraft,
  ConversationResponse,
  Scenario,
} from '../types'

export function makeResult(overrides: Partial<ChatResult> = {}): ChatResult {
  return {
    transaction_id: '11111111-1111-1111-1111-111111111111',
    status: 'success',
    service_type: 'airtime',
    product_type: 'airtime',
    network: 'MTN',
    beneficiary: '08030000001',
    amount: '5000.00',
    vendor_code: 'vendor_a',
    vendor_reference: 'VA-REF-1',
    action: 'allow',
    reason: null,
    message: 'Transaction completed successfully',
    planner_candidate_vendor: 'vendor_a',
    explanation:
      'Your ₦5,000 MTN airtime purchase for 08030000001 was completed successfully through Vendor A.',
    ...overrides,
  }
}

export function makeDraft(
  overrides: Partial<ConversationDraft> = {},
): ConversationDraft {
  return {
    service_type: 'airtime',
    product_type: 'airtime',
    network: null,
    beneficiary: null,
    amount: null,
    ...overrides,
  }
}

export function makeConversation(
  overrides: Partial<ConversationResponse> = {},
): ConversationResponse {
  return {
    conversation_id: '22222222-2222-2222-2222-222222222222',
    step: 'clarify',
    prompt: 'Which network should I use?',
    missing_fields: ['network'],
    draft: makeDraft(),
    result: null,
    ...overrides,
  }
}

export function makeScenario(overrides: Partial<Scenario> = {}): Scenario {
  return {
    scenario: 'NORMAL',
    vendor_a_available: true,
    vendor_b_available: true,
    account_balance_override: null,
    vendor_simulation: {},
    description: 'Vendor A available and preferred; normal account balance.',
    ...overrides,
  }
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}
