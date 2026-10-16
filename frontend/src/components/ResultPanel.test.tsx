import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { makeResult } from '../test/fixtures'
import { ResultPanel } from './ResultPanel'

function fieldValue(label: string): string {
  const term = screen.getByText(label, { selector: 'dt' })
  return term.nextElementSibling?.textContent ?? ''
}

function badge(container: HTMLElement): HTMLElement {
  const element = container.querySelector('.status-badge')
  if (!element) {
    throw new Error('Status badge not rendered')
  }
  return element as HTMLElement
}

describe('ResultPanel', () => {
  it('shows the status line and outcome message before expansion', () => {
    render(<ResultPanel result={makeResult()} />)

    // The compact status line is visible while collapsed.
    expect(screen.getByText('Success', { selector: '.status-badge' })).toBeVisible()
    expect(screen.getByText('status: success')).toBeVisible()
    // The backend's own outcome message is visible while collapsed too.
    expect(
      screen.getByText(
        'Your ₦5,000 MTN airtime purchase for 08030000001 was completed successfully through Vendor A.',
        { selector: '.result-outcome' },
      ),
    ).toBeVisible()
    expect(
      screen.getByRole('button', { name: /show full trace/i }),
    ).toBeVisible()

    // Technical detail is still hidden behind the disclosure.
    for (const label of ['Outcome', 'Status', 'Amount', 'Transaction ID']) {
      expect(screen.getByText(label, { selector: 'dt' })).not.toBeVisible()
    }
  })

  it.each([
    [
      'failed',
      'allow',
      'Your ₦5,000 MTN airtime purchase for 08030000001 could not be completed. Declined by the vendor.',
    ],
    [
      'denied',
      'deny',
      "I couldn't complete your ₦5,000 MTN airtime purchase for 08030000001. Reason: Insufficient balance.",
    ],
    [
      'unknown',
      null,
      'The transaction could not be confirmed yet. Its status is still uncertain.',
    ],
  ])(
    'shows a truthful, non-success outcome message for %s before expansion',
    (status, action, explanation) => {
      const { container } = render(
        <ResultPanel
          result={makeResult({
            status,
            action: action as 'allow' | 'deny' | null,
            explanation,
          })}
        />,
      )

      const message = screen.getByText(explanation, { selector: '.result-outcome' })
      expect(message).toBeVisible()
      // No success wording is ever shown for an unsuccessful or uncertain result.
      expect(message).not.toHaveTextContent(/success/i)
      expect(badge(container)).not.toHaveClass('status-badge--success')
    },
  )

  it('renders the authoritative backend fields for a success result', async () => {
    const user = userEvent.setup()
    const { container } = render(<ResultPanel result={makeResult()} />)

    expect(badge(container)).toHaveTextContent('Success')
    expect(
      screen.getByText(
        'Your ₦5,000 MTN airtime purchase for 08030000001 was completed successfully through Vendor A.',
        { selector: '.result-outcome' },
      ),
    ).toBeVisible()

    await user.click(screen.getByRole('button', { name: /show full trace/i }))

    expect(fieldValue('Status')).toBe('success')
    expect(fieldValue('Transaction ID')).toBe(
      '11111111-1111-1111-1111-111111111111',
    )
    expect(fieldValue('Service / Product')).toBe('airtime / airtime')
    expect(fieldValue('Amount')).toBe('₦5,000')
    expect(fieldValue('Network')).toBe('MTN')
    expect(fieldValue('Beneficiary')).toBe('08030000001')
    expect(fieldValue('Selected vendor')).toBe('Vendor A (vendor_a)')
    expect(fieldValue('Planner candidate')).toBe('Vendor A (vendor_a)')
    expect(fieldValue('Action')).toBe('allow')
    expect(fieldValue('Vendor reference')).toBe('VA-REF-1')
  })

  it.each([
    ['failed', 'Failed'],
    ['denied', 'Policy denied'],
  ])('renders the %s outcome', async (status, label) => {
    const user = userEvent.setup()
    const { container } = render(
      <ResultPanel
        result={makeResult({
          status,
          action: status === 'denied' ? 'deny' : 'allow',
          reason: 'Insufficient balance',
        })}
      />,
    )

    expect(badge(container)).toHaveTextContent(label)

    await user.click(screen.getByRole('button', { name: /show full trace/i }))

    expect(fieldValue('Outcome')).toBe(label)
    expect(fieldValue('Reason')).toBe('Insufficient balance')
  })

  it('labels UNKNOWN as "Outcome unconfirmed" without success styling or wording', async () => {
    const user = userEvent.setup()
    const { container } = render(
      <ResultPanel
        result={makeResult({
          status: 'unknown',
          vendor_code: null,
          vendor_reference: null,
          message: 'Transaction outcome is unknown',
          explanation:
            'The transaction could not be confirmed yet. Its status is still uncertain.',
        })}
      />,
    )

    expect(badge(container)).toHaveTextContent('Outcome unconfirmed')
    expect(screen.queryByText('Success')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /show full trace/i }))

    expect(fieldValue('Outcome')).toBe('Outcome unconfirmed')

    const panel = container.querySelector('.result-panel')
    expect(panel).toHaveAttribute('data-outcome', 'unknown')
    expect(badge(container)).not.toHaveClass('status-badge--success')
    expect(badge(container)).toHaveClass('status-badge--neutral')
  })

  it('renders intermediate statuses as neutral in-progress states', () => {
    const { container } = render(
      <ResultPanel result={makeResult({ status: 'submitting' })} />,
    )

    expect(badge(container)).toHaveTextContent('Submitting')

    const panel = container.querySelector('.result-panel')
    expect(panel).toHaveAttribute('data-outcome', 'in_progress')
    expect(badge(container)).toHaveClass('status-badge--neutral')
    expect(screen.getByText('status: submitting')).toBeVisible()
  })

  it('shows an unfamiliar status as unrecognized, never as success', async () => {
    const user = userEvent.setup()
    const { container } = render(
      <ResultPanel result={makeResult({ status: 'frobnicated' })} />,
    )

    expect(badge(container)).toHaveTextContent('Unrecognized status')
    expect(screen.queryByText('Success')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /show full trace/i }))

    expect(fieldValue('Outcome')).toBe('Unrecognized status')

    const panel = container.querySelector('.result-panel')
    expect(panel).toHaveAttribute('data-outcome', 'unrecognized')
    expect(badge(container)).toHaveClass('status-badge--neutral')
    expect(badge(container)).not.toHaveClass('status-badge--success')
  })

  it('shows the raw backend response verbatim', async () => {
    const user = userEvent.setup()
    const result = makeResult({ status: 'unknown' })
    render(<ResultPanel result={result} />)

    await user.click(screen.getByRole('button', { name: /show full trace/i }))

    const raw = screen.getByText('Raw backend response').closest('details')
    expect(raw).not.toBeNull()
    expect(
      within(raw as HTMLElement).getByText(/"status": "unknown"/),
    ).toBeInTheDocument()

    // The raw block must contain the exact JSON string the backend returned.
    expect(
      within(raw as HTMLElement).getByText(/11111111-1111-1111-1111-111111111111/),
    ).toBeInTheDocument()
  })
})
