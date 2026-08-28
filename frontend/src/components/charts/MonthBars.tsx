import { niceMax, formatMoney } from './chartScale'

export interface BarSeries {
  label: string
  values: number[]
  // Which token to draw with; the bars use `currentColor`.
  tone: 'accent' | 'negative' | 'muted'
}

const identity = (key: string) => key

const TONE_CLASS: Record<BarSeries['tone'], string> = {
  accent: 'text-(--color-accent)',
  negative: 'text-(--color-negative)',
  muted: 'text-(--color-text-muted)',
}

// Hand-rolled grouped/single vertical bar chart. Theme-aware: bars inherit
// `currentColor` from a per-series text-color utility, structure uses
// `--color-border` / `--color-text-muted`. No hardcoded colors, no
// getComputedStyle — works in every theme automatically.
export function MonthBars({
  months,
  series,
  height = 170,
  formatLabel = identity,
}: {
  months: string[]
  series: BarSeries[]
  height?: number
  formatLabel?: (key: string) => string
}) {
  const width = Math.max(320, months.length * 56)
  const padBottom = 22
  const padTop = 8
  const plot = height - padBottom - padTop
  const max = niceMax(series.flatMap((s) => s.values))

  const groupWidth = width / months.length
  const barGap = 4
  const barWidth = Math.max(6, (groupWidth * 0.62) / series.length - barGap)

  return (
    <figure className="overflow-x-auto">
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} role="img" aria-label="Monthly chart">
        {/* baseline */}
        <line
          x1={0}
          x2={width}
          y1={padTop + plot}
          y2={padTop + plot}
          className="stroke-(--color-border)"
          strokeWidth={1}
        />
        {months.map((month, index) => {
          const groupX = index * groupWidth
          return (
            <g key={month}>
              {series.map((s, si) => {
                const value = s.values[index] ?? 0
                const barHeight = max === 0 ? 0 : (Math.max(0, value) / max) * plot
                const x = groupX + groupWidth / 2 - (series.length * (barWidth + barGap)) / 2 + si * (barWidth + barGap)
                return (
                  <g key={s.label} className={TONE_CLASS[s.tone]}>
                    <title>
                      {formatLabel(month)} · {s.label}: {formatMoney(value)}
                    </title>
                    <rect
                      x={x}
                      y={padTop + plot - barHeight}
                      width={barWidth}
                      height={barHeight}
                      rx={2}
                      fill="currentColor"
                    />
                  </g>
                )
              })}
              <text
                x={groupX + groupWidth / 2}
                y={height - 6}
                textAnchor="middle"
                className="fill-(--color-text-muted) text-[10px]"
              >
                {formatLabel(month)}
              </text>
            </g>
          )
        })}
      </svg>
      {series.length > 1 && (
        <figcaption className="mt-2 flex flex-wrap gap-4 text-xs text-(--color-text-muted)">
          {series.map((s) => (
            <span key={s.label} className={`inline-flex items-center gap-1.5 ${TONE_CLASS[s.tone]}`}>
              <span className="inline-block h-2 w-2 rounded-sm bg-current" />
              <span className="text-(--color-text-muted)">{s.label}</span>
            </span>
          ))}
        </figcaption>
      )}
    </figure>
  )
}
