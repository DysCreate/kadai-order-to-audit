import type { OrderState } from './salesApi'

export interface TimelineStep {
  state: OrderState
  done: boolean
  current: boolean
}

const HAPPY_PATH: OrderState[] = ['SUBMITTED', 'APPROVED', 'INVOICED', 'DISPATCHED']

/**
 * Build the order status timeline for the My Orders screen.
 *
 * A rejected order stops after SUBMITTED and shows REJECTED as its current
 * step; every other state lights up the steps that have happened and marks the
 * latest one as current. Pure, so it is unit-tested without a browser.
 */
export function orderTimeline(state: OrderState): TimelineStep[] {
  if (state === 'REJECTED') {
    return [
      { state: 'SUBMITTED', done: true, current: false },
      { state: 'REJECTED', done: true, current: true }
    ]
  }

  const index = HAPPY_PATH.indexOf(state)
  return HAPPY_PATH.map((step, position) => ({
    state: step,
    done: position <= index,
    current: position === index
  }))
}

export function isTerminal(state: OrderState): boolean {
  return state === 'DISPATCHED' || state === 'REJECTED'
}

export function canApprove(state: OrderState): boolean {
  return state === 'SUBMITTED'
}

export function canInvoice(state: OrderState): boolean {
  return state === 'APPROVED'
}
