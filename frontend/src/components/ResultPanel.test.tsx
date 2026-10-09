import { render, screen, within } from '@testing-library/react'
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
  it('renders the authoritative backend fields for a success result', () => {
    const { container } = render(<ResultPanel result={makeResult()} />)

    expect(badge(container)).toHaveTextContent('Success')
    expect(
      screen.getByText(
        'Your ₦5,000 MTN airtime purchase for 08030000001 was completed successfully through Vendor A.',
      ),
    ).toBeInTheDocument()

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
  ])('renders the %s outcome', (status, label) => {
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
    expect(fieldValue('Outcome')).toBe(label)
    expect(fieldValue('Reason')).toBe('Insufficient balance')
  })

  it('labels UNKNOWN as "Outcome unconfirmed" without success styling or wording', () => {
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
    expect(fieldValue('Outcome')).toBe('Outcome unconfirmed')
    expect(screen.queryByText('Success')).not.toBeInTheDocument()

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
    expect(screen.getByText('status: submitting')).toBeInTheDocument()
  })

  it('shows an unfamiliar status as unrecognized, never as success', () => {
    const { container } = render(
      <ResultPanel result={makeResult({ status: 'frobnicated' })} />,
    )

    expect(badge(container)).toHaveTextContent('Unrecognized status')
    expect(fieldValue('Outcome')).toBe('Unrecognized status')

    const panel = container.querySelector('.result-panel')
    expect(panel).toHaveAttribute('data-outcome', 'unrecognized')
    expect(badge(container)).toHaveClass('status-badge--neutral')
    expect(badge(container)).not.toHaveClass('status-badge--success')
    expect(screen.queryByText('Success')).not.toBeInTheDocument()
  })

  it('shows the raw backend response verbatim', () => {
    const result = makeResult({ status: 'unknown' })
    render(<ResultPanel result={result} />)

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
