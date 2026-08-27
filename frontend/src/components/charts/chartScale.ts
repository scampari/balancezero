// Round a max value up to a "nice" number (1/2/5 x 10^n) for chart axes.
export function niceMax(values: number[]): number {
  const max = Math.max(0, ...values)
  if (max === 0) return 1
  const pow = 10 ** Math.floor(Math.log10(max))
  const norm = max / pow
  const nice = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10
  return nice * pow
}

export function formatMoney(value: number): string {
  return value.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
}

// "2026-03" -> "Mar"
export function shortMonth(key: string): string {
  const [year, month] = key.split('-').map(Number)
  return new Date(year, month - 1, 1).toLocaleString('en-US', { month: 'short' })
}
