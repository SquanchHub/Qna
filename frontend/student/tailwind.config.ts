import type { Config } from 'tailwindcss';

// Values live in ../shared/tokens.css; see frontend/README.md "Theming".
const token = (name: string) => `rgb(var(--color-${name}) / <alpha-value>)`;

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: ['selector', '[data-theme="dark"]'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', 'Helvetica', 'Arial', 'sans-serif'],
      },
      colors: {
        surface: {
          DEFAULT: token('surface'),
          raised: token('surface-raised'),
          sunken: token('surface-sunken'),
        },
        border: {
          DEFAULT: token('border'),
          strong: token('border-strong'),
        },
        accent: {
          DEFAULT: token('accent'),
          contrast: token('accent-contrast'),
        },
        danger: token('danger'),
        success: token('success'),
        warning: token('warning'),
        info: token('info'),
        'focus-ring': token('focus-ring'),
        ai: token('ai'),
      },
      textColor: {
        primary: token('text-primary'),
        secondary: token('text-secondary'),
        muted: token('text-muted'),
      },
    },
  },
  plugins: [],
} satisfies Config;
