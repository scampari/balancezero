// Calendar dates from the *viewer's local clock*, never UTC.
//
// `new Date().toISOString().slice(0, 10)` looks convenient but it is the UTC
// date: for anyone west of Greenwich it rolls the day (and, at a month
// boundary, the month) over hours early. The budget's "current month" and the
// transactions window are both anchored to the user's wall clock, so they must
// be built from the local getters.

function pad2(n: number): string {
  return String(n).padStart(2, '0')
}

/** `"YYYY-MM"` for the given (default: now) date, in local time. */
export function localMonthKey(d: Date = new Date()): string {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}`
}

/** `"YYYY-MM-DD"` for the given (default: now) date, in local time. */
export function localDateKey(d: Date = new Date()): string {
  return `${localMonthKey(d)}-${pad2(d.getDate())}`
}

/** `"YYYY-MM-DD"` for `days` days before now, in local time. */
export function localDateDaysAgo(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() - days)
  return localDateKey(d)
}
