/**
 * Column sort for the summary table. Clicking a header cycles ascending → descending → off,
 * mirroring the leaderboard's nextSort. Sorting applies to the top-level model rows only; the
 * drill-down children keep their natural (grouped) order so a sort never scrambles the tree.
 */
import type { RenderRow } from './tree'
import type { TierKey } from './types'

export type SortKey = 'ttft_mape' | 'ttft_shape' | 'tpot_mape' | 'tpot_shape'
export interface SortSpec {
  key: SortKey
  dir: 1 | -1
}

export function nextSort(current: SortSpec | null, key: SortKey): SortSpec | null {
  if (!current || current.key !== key) return { key, dir: 1 }
  if (current.dir === 1) return { key, dir: -1 }
  return null
}

function valueOf(row: RenderRow, key: SortKey, tier: TierKey): number | null {
  const b = row.metrics[tier]
  switch (key) {
    case 'ttft_mape':
      return b.mape.ttft
    case 'ttft_shape':
      return b.shape.ttft
    case 'tpot_mape':
      return b.mape.tpot
    case 'tpot_shape':
      return b.shape.tpot
  }
}

/** Sort the model-level rows by the spec; null values always sink to the bottom. */
export function sortModelKeys(modelRows: RenderRow[], spec: SortSpec | null, tier: TierKey): string[] {
  const keyed = modelRows.map((r, i) => ({ r, i }))
  if (spec) {
    keyed.sort((a, b) => {
      const va = valueOf(a.r, spec.key, tier)
      const vb = valueOf(b.r, spec.key, tier)
      if (va == null && vb == null) return a.i - b.i
      if (va == null) return 1
      if (vb == null) return -1
      if (va !== vb) return (va - vb) * spec.dir
      return a.i - b.i
    })
  }
  return keyed.map((k) => k.r.label)
}
