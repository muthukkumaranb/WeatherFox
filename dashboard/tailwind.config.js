// Theme from the WeatherFox Stitch design. Used to build vendor/tailwind.css (see tailwind.input.css).
const path = require('path');
module.exports = Object.assign({
      darkMode: "class",
      theme: {
        extend: {
          colors: {
            "inverse-on-surface": "#2a3040",
            "outline": "#86948a",
            "on-primary-container": "#00422b",
            "on-background": "#dce2f6",
            "surface-tint": "#4edea3",
            "primary-container": "#10b981",
            "surface-container-highest": "#2e3544",
            "primary-fixed": "#6ffbbe",
            "on-primary": "#003824",
            "on-error": "#690005",
            "inverse-primary": "#006c49",
            "outline-variant": "#3c4a42",
            "secondary": "#ffb690",
            "on-primary-fixed-variant": "#005236",
            "on-surface": "#dce2f6",
            "secondary-container": "#ec6a06",
            "primary": "#4edea3",
            "error": "#ffb4ab",
            "surface-variant": "#2e3544",
            "primary-fixed-dim": "#4edea3",
            "on-secondary-fixed-variant": "#783200",
            "on-tertiary-fixed": "#07006c",
            "surface-bright": "#323949",
            "on-tertiary-container": "#1d17b2",
            "on-surface-variant": "#bbcabf",
            "tertiary-container": "#9699ff",
            "on-primary-fixed": "#002113",
            "surface-container-low": "#151b2a",
            "background": "#0c1321",
            "on-tertiary": "#1000a9",
            "surface-container-high": "#232a39",
            "surface-container": "#19202e",
            "surface": "#0c1321",
            "on-secondary": "#552100",
            "tertiary-fixed": "#e1e0ff",
            "tertiary": "#c0c1ff",
            "secondary-fixed": "#ffdbca",
            "tertiary-fixed-dim": "#c0c1ff",
            "on-error-container": "#ffdad6",
            "on-secondary-fixed": "#341100",
            "surface-dim": "#0c1321",
            "on-secondary-container": "#4a1c00",
            "inverse-surface": "#dce2f6",
            "on-tertiary-fixed-variant": "#2f2ebe",
            "error-container": "#93000a",
            "secondary-fixed-dim": "#ffb690",
            "surface-container-lowest": "#070e1c"
          },
          borderRadius: {
            "DEFAULT": "0.25rem",
            "lg": "0.5rem",
            "xl": "0.75rem",
            "full": "9999px"
          },
          spacing: {
            "gutter": "0.5rem",
            "margin": "0.75rem",
            "space-md": "0.75rem",
            "space-xs": "0.25rem",
            "space-lg": "1rem",
            "space-sm": "0.5rem",
            "space-xl": "1.5rem"
          },
          fontFamily: {
            "headline-lg": ["Space Grotesk", "sans-serif"],
            "headline-md": ["Space Grotesk", "sans-serif"],
            "display-lg": ["Space Grotesk", "sans-serif"],
            "label-mono-bold": ["Space Mono", "monospace"],
            "label-mono-regular": ["Space Mono", "monospace"],
            "body-lg": ["Space Mono", "monospace"],
            "body-md": ["Space Mono", "monospace"],
            "telemetry-micro": ["Space Mono", "monospace"]
          },
          fontSize: {
            "headline-lg": ["22px", { lineHeight: "28px", fontWeight: "600" }],
            "headline-md": ["18px", { lineHeight: "24px", fontWeight: "600" }],
            "display-lg": ["32px", { lineHeight: "40px", fontWeight: "700" }],
            "body-lg": ["15px", { lineHeight: "22px", fontWeight: "400" }],
            "body-md": ["13px", { lineHeight: "20px", fontWeight: "400" }],
            "label-mono-bold": ["12px", { lineHeight: "16px", fontWeight: "700" }],
            "label-mono-regular": ["11px", { lineHeight: "14px", fontWeight: "400" }],
            "telemetry-micro": ["9px", { lineHeight: "12px", fontWeight: "400" }]
          }
        }
      }
    }, {
  content: [path.join(__dirname, 'index.html'), path.join(__dirname, 'app/*.js')],
});
