import { formatMoney } from './chartScale'

export interface HBarRow {
  label: string
  value: number
  sublabel?: string
}

// Horizontal proportional bars — plain divs, not SVG. Used for top merchants
// and category totals. Bar fill is `--color-accent`; theme-aware by default.
export function HBarList({ rows }: { rows: HBarRow[] }) {
  const max = Math.max(1, ...rows.map((r) => r.value))
  if (rows.length === 0) {
    return <p className="text-sm text-(--color-text-faint)">No spending in this range.</p>
  }
  return (
    <ul className="space-y-2">
      {rows.map((row) => (
        <li key={row.label} className="grid grid-cols-[1fr_auto] items-center gap-x-3">
          <div className="flex items-center gap-2 text-sm text-(--color-text)">
            <span className="truncate">{row.label}</span>
            {row.sublabel && <span className="text-xs text-(--color-text-faint)">{row.sublabel}</span>}
          </div>
          <span className="tabular-nums text-sm text-(--color-text-muted)">{formatMoney(row.value)}</span>
          <div className="col-span-2 h-1.5 rounded-full bg-(--color-surface-hover)">
            <div
              className="h-1.5 rounded-full bg-(--color-accent)"
              style={{ width: `${(row.value / max) * 100}%` }}
            />
          </div>
        </li>
      ))}
    </ul>
  )
}
