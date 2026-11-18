import { render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { LanguageSelect } from '../components/LanguageSelect'
import { apiLanguages, languageRegistry } from '../lib/languageRegistry'

it('keeps ten consistent codes available to the API', () => {
  expect(languageRegistry.map((entry) => entry.code)).toEqual(['en', 'hi', 'mr', 'es', 'de', 'fr', 'ja', 'ru', 'zh-CN', 'ko'])
  expect(new Set(languageRegistry.map((entry) => entry.code)).size).toBe(10)
  expect(apiLanguages.map((entry) => entry.code)).toEqual(['en', 'hi', 'mr', 'es', 'de', 'fr', 'ja', 'ru', 'zh-CN', 'ko'])
  expect(languageRegistry.find((entry) => entry.code === 'zh-CN')?.whisper_code).toBe('zh')
})

it('offers all languages and automatic source detection', () => {
  render(<LanguageSelect id="source-test" label="Source" value="auto" allowAuto onChange={vi.fn()} />)
  expect(screen.getByRole('option', { name: /Japanese/ })).toBeEnabled()
  expect(screen.getByRole('option', { name: /Chinese/ })).toBeEnabled()
  expect(screen.getByRole('option', { name: /Hindi/ })).toBeEnabled()
  expect(screen.getByRole('option', { name: 'Detect automatically' })).toBeEnabled()
})
