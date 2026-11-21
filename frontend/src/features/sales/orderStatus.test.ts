import { describe, expect, it } from 'vitest'
import { canApprove, canInvoice, isTerminal, orderTimeline } from './orderStatus'

describe('orderTimeline', () => {
  it('marks the happy path up to the current state', () => {
    const steps = orderTimeline('INVOICED')

    expect(steps.map((step) => step.state)).toEqual([
      'SUBMITTED',
      'APPROVED',
      'INVOICED',
      'DISPATCHED'
    ])
    expect(steps.filter((step) => step.done).map((step) => step.state)).toEqual([
      'SUBMITTED',
      'APPROVED',
      'INVOICED'
    ])
    expect(steps.find((step) => step.current)?.state).toBe('INVOICED')
  })

  it('stops a rejected order after submit', () => {
    expect(orderTimeline('REJECTED')).toEqual([
      { state: 'SUBMITTED', done: true, current: false },
      { state: 'REJECTED', done: true, current: true }
    ])
  })

  it('shows a freshly submitted order at the first step', () => {
    const steps = orderTimeline('SUBMITTED')

    expect(steps.filter((step) => step.done)).toHaveLength(1)
    expect(steps[0].current).toBe(true)
  })
})

describe('order guards', () => {
  it('allows approval only while submitted', () => {
    expect(canApprove('SUBMITTED')).toBe(true)
    expect(canApprove('APPROVED')).toBe(false)
    expect(canApprove('REJECTED')).toBe(false)
  })

  it('allows invoicing only after approval', () => {
    expect(canInvoice('APPROVED')).toBe(true)
    expect(canInvoice('SUBMITTED')).toBe(false)
  })

  it('treats dispatched and rejected orders as terminal', () => {
    expect(isTerminal('DISPATCHED')).toBe(true)
    expect(isTerminal('REJECTED')).toBe(true)
    expect(isTerminal('INVOICED')).toBe(false)
  })
})
