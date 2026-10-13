import { describe, expect, it } from 'vitest'

import { findPhoneNumber, normalizeSpokenText } from './numberWords'

describe('normalizeSpokenText', () => {
  it('converts spoken digit words into a phone number with leading zero', () => {
    expect(
      normalizeSpokenText('zero eight zero three zero zero zero zero zero zero one'),
    ).toBe('08030000001')
  })

  it('preserves a numeric number spoken in groups verbatim', () => {
    expect(normalizeSpokenText('0803 000 0001')).toBe('0803 000 0001')
    expect(normalizeSpokenText('080-300-00001')).toBe('080-300-00001')
  })

  it('joins mixed digit-word and numeric groups', () => {
    expect(normalizeSpokenText('0803 zero zero zero zero zero zero zero one')).toBe(
      '080300000001',
    )
  })

  it('expands double and triple forms', () => {
    expect(normalizeSpokenText('double three zero zero zero zero zero zero')).toBe(
      '33000000',
    )
    expect(normalizeSpokenText('triple zero nine nine nine nine nine nine nine')).toBe(
      '0009999999',
    )
  })

  it('converts spoken amounts to digits', () => {
    expect(normalizeSpokenText('buy five thousand naira airtime')).toBe(
      'buy 5000 naira airtime',
    )
    expect(normalizeSpokenText('mtn airtime for one thousand two hundred')).toBe(
      'mtn airtime for 1200',
    )
  })

  it('keeps the full sentence while normalizing the number', () => {
    expect(
      normalizeSpokenText(
        'buy five thousand naira mtn airtime for zero eight zero three zero zero zero zero zero zero one',
      ),
    ).toBe('buy 5000 naira mtn airtime for 08030000001')
  })

  it('leaves ordinary words and short numbers untouched', () => {
    expect(normalizeSpokenText('buy one airtime for me')).toBe('buy one airtime for me')
    expect(normalizeSpokenText('please confirm')).toBe('please confirm')
  })

  it('is idempotent', () => {
    const once = normalizeSpokenText('for zero eight zero three zero zero zero zero zero zero one')
    expect(normalizeSpokenText(once)).toBe(once)
  })
})

describe('findPhoneNumber', () => {
  it('finds a phone number spoken as words', () => {
    expect(
      findPhoneNumber('for zero eight zero three zero zero zero zero zero zero one'),
    ).toBe('08030000001')
  })

  it('finds a grouped numeric phone number', () => {
    expect(findPhoneNumber('airtime for 0803 000 0001')).toBe('08030000001')
  })

  it('ignores amounts', () => {
    expect(findPhoneNumber('buy 5000 airtime')).toBeNull()
  })
})
