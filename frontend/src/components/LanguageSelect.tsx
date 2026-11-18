import { languages, type Language, type SourceLanguage } from '../lib/types'
import { languageRegistry } from '../lib/languageRegistry'

type Props = {
  label: string
  value: SourceLanguage
  onChange: (language: SourceLanguage) => void
  allowAuto?: boolean
  disabled?: boolean
  id: string
}

export function LanguageSelect({ label, value, onChange, allowAuto = false, disabled, id }: Props) {
  const selectLanguage = (code: string) => {
    if (code === 'auto' && allowAuto) onChange('auto')
    else if (languages.some((item) => item.code === code)) onChange(code as Language)
  }

  return <label htmlFor={id} className="block min-w-0">
    <span className="mb-2 block text-xs font-semibold uppercase tracking-[.12em] text-muted">{label}</span>
    <select id={id} value={value} onChange={(event) => selectLanguage(event.target.value)} disabled={disabled} className="field w-full appearance-none pr-9 font-medium">
      <option value="auto" hidden={!allowAuto} disabled={!allowAuto}>Detect automatically</option>
      {languageRegistry.map((language) => <option key={language.code} value={language.code} disabled={!language.api_enabled}>
        {language.name} · {language.native}{language.api_enabled ? '' : ' (planned)'}
      </option>)}
    </select>
  </label>
}
