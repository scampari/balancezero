import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { STORAGE_KEY, resolveTheme, type ThemeChoice, isThemeChoice } from './themes'

interface ThemeContextValue {
  // The raw choice, including 'system'.
  choice: ThemeChoice
  // What 'system' currently resolves to — what's actually on <html>.
  resolved: Exclude<ThemeChoice, 'system'>
  setChoice: (choice: ThemeChoice) => void
}

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined)

function readStoredChoice(): ThemeChoice {
  // A remembered theme is a display preference, not a credential — unlike the
  // access token (see AuthContext), localStorage is the right home for it.
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (stored && isThemeChoice(stored)) return stored
  } catch {
    // Private mode / storage disabled — fall through to the default.
  }
  return 'system'
}

function applyTheme(resolved: Exclude<ThemeChoice, 'system'>): void {
  document.documentElement.dataset.theme = resolved
  document.documentElement.style.colorScheme = resolved === 'light' ? 'light' : 'dark'
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [choice, setChoiceState] = useState<ThemeChoice>(() => readStoredChoice())
  const [resolved, setResolved] = useState(() => resolveTheme(choice))

  const setChoice = useCallback((next: ThemeChoice) => {
    setChoiceState(next)
    try {
      window.localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // Non-fatal — the choice still applies for this session.
    }
  }, [])

  // Apply the resolved theme to <html> whenever it changes.
  useEffect(() => {
    applyTheme(resolved)
  }, [resolved])

  // Recompute `resolved` when the choice changes, and — while on 'system' —
  // when the OS scheme flips.
  useEffect(() => {
    setResolved(resolveTheme(choice))
    if (choice !== 'system' || !window.matchMedia) return

    const media = window.matchMedia('(prefers-color-scheme: light)')
    const onChange = () => setResolved(resolveTheme('system'))
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [choice])

  const value = useMemo(() => ({ choice, resolved, setChoice }), [choice, resolved, setChoice])
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider')
  return ctx
}
