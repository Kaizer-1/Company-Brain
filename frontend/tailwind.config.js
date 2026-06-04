/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    // Override default font sizes so 14px = base, 12px = sm (dense tool aesthetic)
    fontSize: {
      '2xs': ['11px', { lineHeight: '16px' }],
      xs:    ['12px', { lineHeight: '18px' }],
      sm:    ['13px', { lineHeight: '20px' }],
      base:  ['14px', { lineHeight: '22px' }],
      md:    ['15px', { lineHeight: '24px' }],
      lg:    ['16px', { lineHeight: '24px' }],
      xl:    ['18px', { lineHeight: '28px' }],
      '2xl': ['20px', { lineHeight: '28px' }],
      '3xl': ['24px', { lineHeight: '32px' }],
    },
    extend: {
      colors: {
        // Core palette — 7 colors, neutral dark carries all the weight
        bg:       '#0C0E12',
        surface:  '#131720',
        's2':     '#1B2131',
        border: {
          DEFAULT: '#252D3D',
          strong:  '#334155',
        },
        txt: {
          DEFAULT: '#E2E8F0',
          muted:   '#64748B',
          faint:   '#3F4E66',
        },
        accent: {
          DEFAULT: '#3B82F6',
          hover:   '#2563EB',
          faint:   '#1D3461',
        },
        // Node-type colors — desaturated, accessible on dark bg
        node: {
          decision: '#D97706',
          service:  '#3B82F6',
          system:   '#71717A',
          person:   '#34D399',
          team:     '#A78BFA',
          message:  '#94A3B8',
        },
        // Status indicators — only used for status dots, not backgrounds
        status: {
          active:     '#34D399',
          merged:     '#64748B',
          superseded: '#F59E0B',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'sans-serif'],
        mono: ['"JetBrains Mono"', '"Fira Code"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      spacing: {
        topbar: '44px',
      },
      height: {
        topbar: '44px',
        page:   'calc(100vh - 44px)',
      },
      maxWidth: {
        content: '720px',
      },
      animation: {
        'progress': 'progress 1.5s ease-in-out infinite',
        'skeleton': 'skeleton 1.5s ease-in-out infinite',
      },
      keyframes: {
        progress: {
          '0%':   { transform: 'translateX(-100%)' },
          '100%': { transform: 'translateX(400%)' },
        },
        skeleton: {
          '0%, 100%': { opacity: '0.4' },
          '50%':      { opacity: '0.8' },
        },
      },
    },
  },
  plugins: [],
};
