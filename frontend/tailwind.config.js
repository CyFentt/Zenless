export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#050505",
          900: "#090909",
          850: "#0b0b0b",
          800: "#0d0d0d",
          750: "#0f0f0f",
          700: "#121212",
          650: "#161616",
          600: "#1a1a1a",
          550: "#202020",
          500: "#242424",
          450: "#2a2a2a",
          400: "#777777",
          300: "#999999",
          250: "#555555",
          200: "#6a6a6a",
          150: "#858585",
          100: "#a0a0a0",
          50: "#c4c4c4",
          25: "#e0e0e0",
          0: "#f2f2f2",
        },
        zen: {
          ok: "#153222",
          okBright: "#62c68c",
          warn: "#3d3014",
          warnBright: "#e5b84f",
          err: "#4b1117",
          errBright: "#ff3344",
          red: "#c51f2c",
          redBright: "#ff3344",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      fontSize: {
        "2xs": ["0.625rem", { lineHeight: "0.9rem" }],
      },
      animation: {
        "fade-in": "fadeIn 200ms ease-out",
        "fade-in-slow": "fadeIn 350ms ease-out",
        "slide-up": "slideUp 200ms ease-out",
        "slide-right": "slideRight 200ms ease-out",
        "pulse-soft": "pulseSoft 2s ease-in-out infinite",
        "spin-slow": "spin 1.2s linear infinite",
      },
      keyframes: {
        fadeIn: { from: { opacity: "0" }, to: { opacity: "1" } },
        slideUp: {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        slideRight: {
          from: { opacity: "0", transform: "translateX(-4px)" },
          to: { opacity: "1", transform: "translateX(0)" },
        },
        pulseSoft: { "0%,100%": { opacity: "0.5" }, "50%": { opacity: "1" } },
      },
    },
  },
  plugins: [],
};
