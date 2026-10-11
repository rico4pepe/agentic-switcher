import { describe, expect, it } from 'vitest'

import {
  finalAssistantMessage,
  shouldAppendFinalMessage,
} from './conversation'
import { makeConversation, makeDraft, makeResult } from './test/fixtures'

const draft = makeDraft({
  network: 'MTN',
  beneficiary: '08030000001',
  amount: '5000.00',
})

const completed = makeConversation({
  step: 'complete',
  draft,
  result: makeResult(),
})

const cancelled = makeConversation({ step: 'cancelled', draft, result: null })

describe('shouldAppendFinalMessage', () => {
  it('returns false for non-terminal steps', () => {
    expect(
      shouldAppendFinalMessage(null, makeConversation({ step: 'clarify' })),
    ).toBe(false)
    expect(
      shouldAppendFinalMessage(null, makeConversation({ step: 'confirm' })),
    ).toBe(false)
  })

  it('returns true the first time a conversation terminates', () => {
    expect(shouldAppendFinalMessage(null, completed)).toBe(true)
    expect(shouldAppendFinalMessage(null, cancelled)).toBe(true)
  })

  it('returns false when the same terminal result is replayed', () => {
    const id = completed.conversation_id
    expect(shouldAppendFinalMessage(id, completed)).toBe(false)
    expect(shouldAppendFinalMessage(id, cancelled)).toBe(false)
  })

  it('returns true when a different conversation terminates', () => {
    expect(
      shouldAppendFinalMessage(
        completed.conversation_id,
        makeConversation({
          conversation_id: '33333333-3333-3333-3333-333333333333',
          step: 'complete',
          draft,
          result: makeResult(),
        }),
      ),
    ).toBe(true)
  })
})

describe('finalAssistantMessage', () => {
  it('returns null for non-terminal steps', () => {
    expect(
      finalAssistantMessage(makeConversation({ step: 'clarify' })),
    ).toBeNull()
    expect(
      finalAssistantMessage(makeConversation({ step: 'confirm' })),
    ).toBeNull()
  })

  it('returns null for a complete step without an authoritative result', () => {
    expect(
      finalAssistantMessage(
        makeConversation({ step: 'complete', draft, result: null }),
      ),
    ).toBeNull()
  })

  it('confirms a successful purchase using the backend explanation', () => {
    const explanation =
      'Your ₦5,000 MTN airtime purchase for 08030000001 was completed successfully through Vendor B.'

    expect(
      finalAssistantMessage(
        makeConversation({
          step: 'complete',
          draft,
          result: makeResult({
            status: 'success',
            vendor_code: 'vendor_b',
            explanation,
          }),
        }),
      ),
    ).toBe(explanation)
  })

  it('reports a denial and that no vendor was contacted', () => {
    const message = finalAssistantMessage(
      makeConversation({
        step: 'complete',
        draft,
        result: makeResult({
          status: 'denied',
          action: 'deny',
          transaction_id: null,
          vendor_code: null,
          vendor_reference: null,
          reason: 'Insufficient balance',
          explanation:
            'I couldn’t complete your ₦5,000 MTN airtime purchase for 08030000001. Reason: Insufficient balance.',
        }),
      }),
    )

    expect(message).toContain('Reason: Insufficient balance')
    expect(message).toContain('No transaction was submitted to a vendor.')
  })

  it('never claims success for an unconfirmed outcome', () => {
    const message = finalAssistantMessage(
      makeConversation({
        step: 'complete',
        draft,
        result: makeResult({
          status: 'unknown',
          transaction_id: null,
          vendor_code: null,
          vendor_reference: null,
          action: null,
          explanation:
            'The transaction could not be confirmed yet. Its status is still uncertain.',
        }),
      }),
    )

    expect(message).toContain('could not be confirmed')
    expect(message?.toLowerCase()).toContain('unconfirmed')
    expect(message?.toLowerCase()).not.toContain('success')
    expect(message?.toLowerCase()).not.toContain('completed successfully')
  })

  it('announces cancellation without implying execution', () => {
    const message = finalAssistantMessage(
      makeConversation({ step: 'cancelled', draft, result: null }),
    )

    expect(message).toMatch(/cancelled/i)
    expect(message).toContain('No purchase was submitted to a vendor.')
  })
})
