import { useTheme } from '../theme/ThemeContext'
import { THEME_OPTIONS, isThemeChoice } from '../theme/themes'

const GROUPS = ['System', 'Light', 'Dark'] as const

export function ThemePicker() {
  const { choice, setChoice } = useTheme()

  return (
    <select
      aria-label="Theme"
      value={choice}
      onChange={(event) => {
        if (isThemeChoice(event.target.value)) setChoice(event.target.value)
      }}
      className="rounded-md border border-(--color-border) bg-(--color-bg) px-2 py-1.5 text-sm text-(--color-text-muted) outline-none transition-colors hover:text-(--color-text) focus:border-(--color-accent-border) focus:ring-2 focus:ring-(--color-accent-bg)"
    >
      {GROUPS.map((group) => {
        const options = THEME_OPTIONS.filter((option) => option.group === group)
        if (group === 'System') {
          return options.map((option) => (
            <option key={option.id} value={option.id}>
              {option.label}
            </option>
          ))
        }
        return (
          <optgroup key={group} label={group}>
            {options.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </optgroup>
        )
      })}
    </select>
  )
}
