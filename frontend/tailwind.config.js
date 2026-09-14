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
          400: "#333333",
          300: "#484848",
          250: "#555555",
          200: "#6a6a6a",
          150: "#858585",
          100: "#a0a0a0",
          50: "#c4c4c4",
          25: "#e0e0e0",
          0: "#f2f2f2",
        },
        zen: {
          ok: "#d0d0d0",
          okBright: "#f2f2f2",
          warn: "#242424",
          warnBright: "#a0a0a0",
          err: "#181818",
          errBright: "#e0e0e0",
        },
      },
      fontFamily: {
        sans: ["Segoe UI Variable Text", "Segoe UI", "system-ui", "sans-serif"],
        mono: ["Cascadia Mono", "Consolas", "ui-monospace", "monospace"],
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
        "page-in": "pageIn 240ms cubic-bezier(0.16, 1, 0.3, 1)",
        "panel-in": "panelIn 260ms cubic-bezier(0.16, 1, 0.3, 1)",
        "reveal": "reveal 180ms ease-out",
        "nav-line": "navLine 180ms ease-out",
        "loader-frame": "loaderFrame 3.2s cubic-bezier(0.65, 0, 0.35, 1) infinite",
        "loader-frame-reverse": "loaderFrameReverse 2.4s cubic-bezier(0.65, 0, 0.35, 1) infinite",
        "loading-bar": "loadingBar 1.4s ease-in-out infinite",
        "scan": "scan 2.2s ease-in-out infinite",
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
        pageIn: {
          from: { opacity: "0", transform: "translateY(3px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        panelIn: {
          from: { opacity: "0", transform: "translateX(12px)" },
          to: { opacity: "1", transform: "translateX(0)" },
        },
        reveal: {
          from: { opacity: "0", transform: "translateY(-2px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        navLine: {
          from: { opacity: "0", transform: "scaleY(0)" },
          to: { opacity: "1", transform: "scaleY(1)" },
        },
        loaderFrame: {
          "0%,100%": { transform: "rotate(0deg) scale(1)" },
          "50%": { transform: "rotate(45deg) scale(0.86)" },
        },
        loaderFrameReverse: {
          "0%,100%": { transform: "rotate(45deg) scale(0.88)" },
          "50%": { transform: "rotate(0deg) scale(1)" },
        },
        loadingBar: {
          from: { transform: "translateX(-110%)" },
          to: { transform: "translateX(410%)" },
        },
        scan: {
          "0%,100%": { opacity: "0", transform: "translateY(-42px)" },
          "50%": { opacity: "1", transform: "translateY(42px)" },
        },
      },
      boxShadow: {
        panel: "-16px 0 40px rgba(0,0,0,0.45)",
      },
    },
  },
  plugins: [],
};
