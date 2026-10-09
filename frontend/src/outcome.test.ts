import { describe, expect, it } from 'vitest'

import {
  classifyOutcome,
  formatAmount,
  humanizeStatus,
  vendorName,
} from './outcome'

describe('classifyOutcome', () => {
  it.each([
    ['success', 'success', 'Success'],
    ['failed', 'failed', 'Failed'],
    ['denied', 'denied', 'Policy denied'],
    ['unknown', 'unknown', 'Outcome unconfirmed'],
  ])('classifies %s', (status, kind, label) => {
    const outcome = classifyOutcome(status)
    expect(outcome.kind).toBe(kind)
    expect(outcome.label).toBe(label)
  })

  it('never presents unknown with success styling or success wording', () => {
    const outcome = classifyOutcome('unknown')
    expect(outcome.label).toBe('Outcome unconfirmed')
    expect(outcome.tone).not.toBe('success')
    expect(`${outcome.label} ${outcome.detail}`.toLowerCase()).not.toContain(
      'success',
    )
  })

  it.each([
    ['created', 'Created'],
    ['validating', 'Validating'],
    ['validated', 'Validated'],
    ['submitting', 'Submitting'],
    ['submitted', 'Submitted'],
    ['investigating', 'Investigating'],
    ['status_resolved', 'Status Resolved'],
  ])(
    'treats the recognized intermediate status %s as neutral in-progress',
    (status, label) => {
      const outcome = classifyOutcome(status)
      expect(outcome.kind).toBe('in_progress')
      expect(outcome.tone).toBe('neutral')
      expect(outcome.label).toBe(label)
    },
  )

  it('treats an unfamiliar status as unrecognized, never as success', () => {
    const outcome = classifyOutcome('frobnicated')
    expect(outcome.kind).toBe('unrecognized')
    expect(outcome.tone).toBe('neutral')
    expect(outcome.label).toBe('Unrecognized status')
    expect(outcome.detail.toLowerCase()).toContain('cannot be determined')
    expect(`${outcome.label} ${outcome.detail}`.toLowerCase()).not.toContain(
      'success',
    )
  })
})

describe('humanizeStatus', () => {
  it('title-cases underscore-separated statuses', () => {
    expect(humanizeStatus('status_resolved')).toBe('Status Resolved')
  })
})

describe('vendorName', () => {
  it('maps known vendor codes to display names', () => {
    expect(vendorName('vendor_a')).toBe('Vendor A')
    expect(vendorName('vendor_b')).toBe('Vendor B')
  })

  it('returns null for missing vendor codes and preserves unknown codes', () => {
    expect(vendorName(null)).toBeNull()
    expect(vendorName('')).toBeNull()
    expect(vendorName('vendor_c')).toBe('Vendor C')
  })
})

describe('formatAmount', () => {
  it('formats backend amounts without inventing precision', () => {
    expect(formatAmount('5000.00')).toBe('₦5,000')
    expect(formatAmount('12.5')).toBe('₦12.5')
    expect(formatAmount(1000)).toBe('₦1,000')
  })

  it('passes through values that are not numeric', () => {
    expect(formatAmount('not-a-number')).toBe('not-a-number')
  })
})
