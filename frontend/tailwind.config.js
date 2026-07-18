/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        // Deep obsidian-green estate surfaces
        estate: {
          950: "#050e09",
          900: "#07130c",
          800: "#0d1b12",
          700: "#112419",
          line: "#1c3527",
        },
        // Muted gold / champagne bronze accent
        gilt: {
          DEFAULT: "#C5A059",
          bright: "#D4AF37",
          dim: "#b08d4a",
        },
      },
      fontFamily: {
        display: ['"Playfair Display"', '"Cormorant Garamond"', "Georgia", "serif"],
        sans: ['"Inter"', "system-ui", "sans-serif"],
      },
      keyframes: {
        fadeIn: {
          from: { opacity: "0", transform: "translateY(8px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "fade-in": "fadeIn 0.7s ease-out forwards",
      },
    },
  },
  plugins: [],
};