/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        canvas: 'var(--color-bg)',
        sidebar: 'var(--color-sidebar)',
        surface: 'var(--color-surface)',
        raised: 'var(--color-surface-raised)',
        line: 'var(--color-border)',
        accent: 'var(--color-primary)',
        foreground: 'var(--color-text)',
        muted: 'var(--color-muted)',
        ink: '#161f22',
        cream: '#f7f7f2',
        mint: '#0f8c75',
        lime: '#c8f271',
      },
      fontFamily: { sans: ['Inter', 'ui-sans-serif', 'system-ui'] },
      boxShadow: { soft: '0 18px 60px -28px rgba(15, 35, 31, .26)' },
    },
  },
  plugins: [],
}
