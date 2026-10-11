/**
 * Build the assistant's final transcript message for a terminal conversation.
 *
 * The message is derived entirely from the authoritative backend response; the
 * browser never invents an outcome. The backend's `result.explanation` already
 * states the outcome with the amount, network, beneficiary, and vendor, so it
 * is reused verbatim and only extended with facts the response itself proves
 * (for example, that a denial never reached a vendor). An `unknown` outcome is
 * always framed as unresolved and is never described as a success.
 */

import type { ConversationResponse } from './types'

/**
 * Decide whether a terminal response should append a final assistant message.
 *
 * Appending once per conversation keeps a repeated confirmation or a replayed
 * result from cluttering the transcript with the same terminal message.
 */
export function shouldAppendFinalMessage(
  finalizedConversationId: string | null,
  response: ConversationResponse,
): boolean {
  const isTerminal = response.step === 'complete' || response.step === 'cancelled'
  return isTerminal && response.conversation_id !== finalizedConversationId
}

export function finalAssistantMessage(
  response: ConversationResponse,
): string | null {
  if (response.step === 'cancelled') {
    return 'Conversation cancelled. No purchase was submitted to a vendor.'
  }

  if (response.step !== 'complete' || response.result === null) {
    return null
  }

  const result = response.result
  const explanation = result.explanation.trim()

  if (result.status === 'denied' || result.action === 'deny') {
    const vendorNotContacted =
      result.transaction_id === null && result.vendor_code === null
    return vendorNotContacted
      ? `${explanation} No transaction was submitted to a vendor.`
      : explanation
  }

  if (result.status === 'unknown') {
    return (
      `${explanation} Treat this outcome as unconfirmed and investigate it ` +
      'before any further action.'
    )
  }

  return explanation
}