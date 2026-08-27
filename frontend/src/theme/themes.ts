// Theme identifiers. 'system' follows the OS `prefers-color-scheme`; the
// rest map 1:1 to an `html[data-theme="..."]` block in src/index.css.
export type ThemeChoice = 'system' | 'light' | 'dark' | 'dark-dim' | 'dark-ocean'
export type ResolvedTheme = Exclude<ThemeChoice, 'system'>

export const STORAGE_KEY = 'bz.theme'

// Kept in sync with the pre-paint script in index.html.
export function resolveTheme(choice: ThemeChoice): ResolvedTheme {
  if (choice !== 'system') return choice
  if (typeof window === 'undefined' || !window.matchMedia) return 'dark'
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

export function isLightTheme(resolved: ResolvedTheme): boolean {
  return resolved === 'light'
}

// Grouping + labels for the header picker.
export const THEME_OPTIONS: { id: ThemeChoice; label: string; group: 'System' | 'Light' | 'Dark' }[] = [
  { id: 'system', label: 'System', group: 'System' },
  { id: 'light', label: 'Light', group: 'Light' },
  { id: 'dark', label: 'Dark', group: 'Dark' },
  { id: 'dark-dim', label: 'Dark dim', group: 'Dark' },
  { id: 'dark-ocean', label: 'Dark ocean', group: 'Dark' },
]

export function isThemeChoice(value: string): value is ThemeChoice {
  return THEME_OPTIONS.some((option) => option.id === value)
}
