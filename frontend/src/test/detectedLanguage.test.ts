import { expect, it } from 'vitest'
import { detectedLanguageLabel, detectedLanguageTag } from '../lib/detectedLanguage'

it('labels registry languages, extra provider codes, and unavailable metadata honestly', () => {
  expect(detectedLanguageLabel('en', 'stt')).toBe('English')
  expect(detectedLanguageLabel('hi', 'stt')).toBe('Hindi')
  expect(detectedLanguageLabel('mr', 'stt')).toBe('Marathi')
  expect(detectedLanguageLabel('it', 'stt')).toBe('Italian')
  expect(detectedLanguageLabel(null, 'unknown')).toBe('Unknown language')
  expect(detectedLanguageLabel('not-a-language', 'stt')).toBe('Unknown language')
  expect(detectedLanguageTag('hi')).toBe('hi-IN')
  expect(detectedLanguageTag('mr')).toBe('mr-IN')
})
