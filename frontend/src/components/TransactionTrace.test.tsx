import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { makeConversation, makeDraft, makeResult } from '../test/fixtures'
import { TransactionTrace } from './TransactionTrace'

function completedResponse(result = makeResult()) {
  return makeConversation({
    step: 'complete',
    prompt: 'Confirmed. Submitting the transaction.',
    missing_fields: [],
    draft: makeDraft({
      network: 'MTN',
      beneficiary: '08030000001',
      amount: '5000.00',
    }),
    result,
  })
}

function detailsRegion(): HTMLElement | null {
  return document.querySelector('.result-details')
}

describe('TransactionTrace', () => {
  it('shows a compact idle line before any request', () => {
    render(<TransactionTrace response={null} />)

    const trace = screen.getByLabelText('Transaction trace')
    expect(within(trace).getByText(/trace will appear here/i)).toBeInTheDocument()
    expect(within(trace).queryByLabelText('Transaction result')).not.toBeInTheDocument()
  })

  it('shows a compact collecting summary and no transaction card', () => {
    render(
      <TransactionTrace
        response={makeConversation({
          step: 'clarify',
          prompt: 'Which network?',
          missing_fields: ['network'],
          result: null,
        })}
      />,
    )

    const trace = screen.getByLabelText('Transaction trace')
    const collecting = trace.querySelector('[data-trace-state="collecting"]')
    expect(collecting).not.toBeNull()
    expect(within(collecting as HTMLElement).getByText('Collecting details')).toBeInTheDocument()
    // No populated result card is rendered while details are being collected.
    expect(within(trace).queryByLabelText('Transaction result')).not.toBeInTheDocument()
  })

  it('shows an awaiting-confirmation summary before the user confirms', () => {
    render(
      <TransactionTrace
        response={makeConversation({
          step: 'confirm',
          prompt: 'Confirm?',
          missing_fields: [],
        })}
      />,
    )

    const trace = screen.getByLabelText('Transaction trace')
    expect(within(trace).getByText('Awaiting your confirmation')).toBeInTheDocument()
    expect(within(trace).queryByLabelText('Transaction result')).not.toBeInTheDocument()
  })

  it('shows a cancelled summary when the conversation stops before execution', () => {
    render(
      <TransactionTrace
        response={makeConversation({
          step: 'cancelled',
          prompt: 'Cancelled.',
          missing_fields: [],
        })}
      />,
    )

    const trace = screen.getByLabelText('Transaction trace')
    expect(within(trace).getByText('Cancelled')).toBeInTheDocument()
    expect(within(trace).queryByLabelText('Transaction result')).not.toBeInTheDocument()
  })

  it('shows the status line and the actual outcome message while collapsed', () => {
    render(<TransactionTrace response={completedResponse()} />)

    const trace = screen.getByLabelText('Transaction trace')
    // The compact status line stays visible: the outcome badge plus raw status.
    expect(
      within(trace).getByText('Success', { selector: '.status-badge' }),
    ).toBeVisible()
    expect(within(trace).getByText('status: success')).toBeVisible()
    // The backend's own outcome message is visible before expanding.
    expect(
      within(trace).getByText(
        'Your ₦5,000 MTN airtime purchase for 08030000001 was completed successfully through Vendor A.',
        { selector: '.result-outcome' },
      ),
    ).toBeVisible()
    expect(
      within(trace).getByRole('button', { name: /show full trace/i }),
    ).toBeVisible()
    // The evidence region itself is hidden.
    expect(detailsRegion()).toHaveAttribute('hidden')
  })

  it('keeps the outcome message visible and restores technical detail on expansion', async () => {
    const user = userEvent.setup()
    render(<TransactionTrace response={completedResponse()} />)

    const trace = screen.getByLabelText('Transaction trace')
    const summaryLabels = [
      'Outcome',
      'Selected vendor',
      'Reason',
      'Status',
      'Amount',
      'Network',
      'Beneficiary',
      'Action',
      'Planner candidate',
      'Transaction ID',
    ]
    const explanation =
      'Your ₦5,000 MTN airtime purchase for 08030000001 was completed successfully through Vendor A.'

    // Technical detail is hidden while collapsed, but the outcome message is not.
    for (const label of summaryLabels) {
      expect(
        within(trace).getByText(label, { selector: 'dt' }),
      ).not.toBeVisible()
    }
    expect(
      within(trace).getByText(explanation, { selector: '.result-outcome' }),
    ).toBeVisible()

    await user.click(
      within(trace).getByRole('button', { name: /show full trace/i }),
    )

    // The full trace is restored on demand.
    for (const label of summaryLabels) {
      expect(within(trace).getByText(label, { selector: 'dt' })).toBeVisible()
    }
    expect(
      within(trace).getByText(explanation, { selector: '.result-outcome' }),
    ).toBeVisible()
    expect(
      within(trace).getByText('Vendor reference', { selector: 'dt' }),
    ).toBeVisible()
  })

  it('renders an accurate populated summary from the backend result', async () => {
    const user = userEvent.setup()
    render(<TransactionTrace response={completedResponse()} />)

    const trace = screen.getByLabelText('Transaction trace')
    expect(
      within(trace).getByText('Success', { selector: '.status-badge' }),
    ).toBeInTheDocument()
    expect(within(trace).getByLabelText('Transaction result')).toBeInTheDocument()

    await user.click(
      within(trace).getByRole('button', { name: /show full trace/i }),
    )

    const value = (label: string) => {
      const term = within(trace).getByText(label, { selector: 'dt' })
      return term.nextElementSibling?.textContent ?? ''
    }
    expect(value('Outcome')).toBe('Success')
    expect(value('Status')).toBe('success')
    expect(value('Selected vendor')).toBe('Vendor A (vendor_a)')
    expect(value('Planner candidate')).toBe('Vendor A (vendor_a)')
    expect(value('Action')).toBe('allow')
    expect(value('Transaction ID')).toBe('11111111-1111-1111-1111-111111111111')
    expect(value('Amount')).toBe('₦5,000')
    expect(value('Network')).toBe('MTN')
    expect(value('Beneficiary')).toBe('08030000001')
  })

  it('starts collapsed behind an accessible disclosure and toggles the evidence', async () => {
    const user = userEvent.setup()
    render(<TransactionTrace response={completedResponse()} />)

    const toggle = screen.getByRole('button', { name: /show full trace/i })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')

    const details = detailsRegion()
    expect(details).not.toBeNull()
    expect(details).toHaveAttribute('hidden')
    expect(details).not.toBeVisible()
    // The disclosure control points at the region it reveals.
    expect(toggle).toHaveAttribute('aria-controls', (details as HTMLElement).id)

    await user.click(toggle)

    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(toggle).toHaveTextContent(/hide full trace/i)
    expect(detailsRegion()).not.toHaveAttribute('hidden')
    expect(detailsRegion()).toBeVisible()
    // Deeper evidence that is not in the compact summary becomes available.
    expect(
      within(detailsRegion() as HTMLElement).getByText('Vendor reference'),
    ).toBeInTheDocument()
    expect(
      within(detailsRegion() as HTMLElement).getByText('Raw backend response'),
    ).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /hide full trace/i }))
    expect(screen.getByRole('button', { name: /show full trace/i })).toHaveAttribute(
      'aria-expanded',
      'false',
    )
    expect(detailsRegion()).toHaveAttribute('hidden')
    expect(detailsRegion()).not.toBeVisible()
  })

  it('preserves the collapse state across ordinary result updates', async () => {
    const user = userEvent.setup()
    const { rerender } = render(
      <TransactionTrace response={completedResponse()} />,
    )

    await user.click(screen.getByRole('button', { name: /show full trace/i }))
    expect(detailsRegion()).not.toHaveAttribute('hidden')

    // A new backend result arrives; the panel must not reset the disclosure.
    rerender(
      <TransactionTrace
        response={completedResponse(makeResult({ vendor_reference: 'VA-REF-2' }))}
      />,
    )

    expect(
      screen.getByRole('button', { name: /hide full trace/i }),
    ).toHaveAttribute('aria-expanded', 'true')
    expect(detailsRegion()).not.toHaveAttribute('hidden')
  })

  it('never presents a planner candidate as the selected vendor', () => {
    render(
      <TransactionTrace
        response={completedResponse(
          makeResult({
            status: 'denied',
            action: 'deny',
            vendor_code: null,
            vendor_reference: null,
            transaction_id: null,
            planner_candidate_vendor: 'vendor_a',
            reason: 'Insufficient balance',
            message: 'Denied by policy',
          }),
        )}
      />,
    )

    const trace = screen.getByLabelText('Transaction trace')
    const selected = within(trace).getByText('Selected vendor', { selector: 'dt' })
    expect(selected.nextElementSibling).toHaveTextContent('—')

    const planner = within(trace).getByText('Planner candidate', { selector: 'dt' })
    expect(planner.nextElementSibling).toHaveTextContent('Vendor A (vendor_a)')
  })

  it.each([
    ['unknown', 'Outcome unconfirmed'],
    ['failed', 'Failed'],
    ['denied', 'Policy denied'],
  ])('represents the %s outcome without inventing success', (status, label) => {
    render(
      <TransactionTrace
        response={completedResponse(
          makeResult({
            status,
            transaction_id: null,
            vendor_code: null,
            vendor_reference: null,
            planner_candidate_vendor: 'vendor_a',
            reason: status === 'denied' ? 'Insufficient balance' : null,
          }),
        )}
      />,
    )

    const trace = screen.getByLabelText('Transaction trace')
    const outcome = within(trace).getByText('Outcome', { selector: 'dt' })
    expect(outcome.nextElementSibling).toHaveTextContent(label)
    expect(within(trace).queryByText('Success')).not.toBeInTheDocument()
  })
})
