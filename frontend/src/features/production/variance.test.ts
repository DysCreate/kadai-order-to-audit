import { describe, expect, it } from 'vitest'
import { formatPct, previewVariance } from './variance'

// Requirement: AGENTS.md 4.6 – the live chip must agree with the stored snapshot.
describe('previewVariance', () => {
  it('does not flag the exact -3% pouch boundary', () => {
    const result = previewVariance('200', 194, 0.03)
    expect(result.flagged).toBe(false)
    expect(result.pct).toBe(-0.03)
    expect(result.direction).toBe('favourable')
  })

  it('flags an adverse over-use of oil', () => {
    const result = previewVariance('10', 10.5, 0.03)
    expect(result.flagged).toBe(true)
    expect(result.direction).toBe('adverse')
  })

  it('treats a shortfall in output as adverse yield', () => {
    const result = previewVariance('200', 188, 0.03, true)
    expect(result.flagged).toBe(true)
    expect(result.direction).toBe('adverse')
  })

  it('treats fewer cartons used as favourable', () => {
    const result = previewVariance('10', 9, 0.03)
    expect(result.flagged).toBe(true)
    expect(result.direction).toBe('favourable')
  })

  it('flags any usage against a zero plan', () => {
    expect(previewVariance('0', 0.5, 0.03)).toEqual({
      pct: null,
      flagged: true,
      direction: 'adverse'
    })
    expect(previewVariance('0', 0, 0.03).flagged).toBe(false)
  })

  it('ignores unusable input while typing', () => {
    expect(previewVariance('40', Number.NaN, 0.03).flagged).toBe(false)
    expect(previewVariance('', 10, 0.03).flagged).toBe(false)
  })
})

describe('formatPct', () => {
  it('renders signed percentages', () => {
    expect(formatPct(-0.03)).toBe('-3.0%')
    expect(formatPct(0.05)).toBe('+5.0%')
    expect(formatPct(0)).toBe('0.0%')
    expect(formatPct(null)).toBe('—')
  })
})
