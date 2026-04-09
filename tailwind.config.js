/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"DM Sans"', 'system-ui', 'sans-serif'],
      },
      colors: {
        aurora: {
          bg: '#0a0a1a',
          surface: '#12122a',
          card: 'rgba(255, 255, 255, 0.04)',
          border: 'rgba(255, 255, 255, 0.08)',
          text: '#e2e8f0',
          muted: '#8892a6',
          accent: '#7c5bf0',
          'accent-light': '#a78bfa',
          success: '#34d399',
          warning: '#fbbf24',
          danger: '#f87171',
          pink: '#f472b6',
          cyan: '#22d3ee',
          orange: '#fb923c',
        },
      },
      backdropBlur: {
        glass: '20px',
      },
    },
  },
  plugins: [],
}
