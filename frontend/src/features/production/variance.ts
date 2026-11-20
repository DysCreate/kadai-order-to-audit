import type { VarianceDirection } from './productionApi'

/**
 * Live variance preview for the supervisor's screen.
 *
 * This mirrors `apps/production/variance.py` so the chip beside an input shows
 * the same answer the server will store. Only quantities pass through here –
 * never money – and the percentage is rounded to six places before the
 * comparison so the -3.0% pouch boundary does not flip on a float artefact.
 */

const SIX_PLACES = 1e6

export interface VariancePreview {
  pct: number | null
  flagged: boolean
  direction: VarianceDirection
}

export function previewVariance(
  planned: string,
  actual: number,
  tolerance: number,
  higherIsBetter = false
): VariancePreview {
  const trimmed = planned.trim()
  const plannedQty = trimmed === '' ? Number.NaN : Number(trimmed)

  if (!Number.isFinite(plannedQty) || !Number.isFinite(actual) || plannedQty < 0) {
    return { pct: null, flagged: false, direction: 'none' }
  }
  if (plannedQty === 0) {
    return actual === 0
      ? { pct: 0, flagged: false, direction: 'none' }
      : { pct: null, flagged: true, direction: 'adverse' }
  }

  const pct = Math.round(((actual - plannedQty) / plannedQty) * SIX_PLACES) / SIX_PLACES
  const flagged = Math.abs(pct) > tolerance
  const direction: VarianceDirection =
    actual === plannedQty ? 'none' : actual > plannedQty !== higherIsBetter ? 'adverse' : 'favourable'

  return { pct, flagged, direction }
}

export function formatPct(pct: number | null): string {
  if (pct === null) return '—'
  const value = Math.round(pct * 1000) / 10
  return `${value > 0 ? '+' : ''}${value.toFixed(1)}%`
}
