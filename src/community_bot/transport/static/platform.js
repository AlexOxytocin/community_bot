const palettes = {
  dark: { "--app-background": "#05060a", "--app-surface": "#0c0f17", "--app-text": "#f6f8fc", "--app-text-muted": "#a9b1c4", "--app-accent": "#2ee6d6", "--app-accent-text": "#05060a" },
  light: { "--app-background": "#f6f8fc", "--app-surface": "#ffffff", "--app-text": "#171b26", "--app-text-muted": "#687187", "--app-accent": "#08766f", "--app-accent-text": "#ffffff" },
};

const mapping = {
  "--app-background": "bg_color",
  "--app-surface": "secondary_bg_color",
  "--app-text": "text_color",
  "--app-text-muted": "hint_color",
  "--app-accent": "button_color",
  "--app-accent-text": "button_text_color",
};

const validColor = (value) => typeof value === "string" && /^#[0-9a-f]{6}$/i.test(value);

const contrastPairs = [
  ["--app-text", "--app-background", 4.5],
  ["--app-text-muted", "--app-background", 4.5],
  ["--app-text", "--app-surface", 4.5],
  ["--app-text-muted", "--app-surface", 4.5],
  ["--app-accent-text", "--app-accent", 4.5],
  ["--app-accent", "--app-background", 4.5],
  ["--app-accent", "--app-surface", 4.5],
];

const luminance = (color) => {
  const channels = color.slice(1).match(/../g).map((part) => parseInt(part, 16) / 255);
  const linear = channels.map((value) => value <= 0.04045
    ? value / 12.92
    : ((value + 0.055) / 1.055) ** 2.4);
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
};

const hasRequiredContrast = (palette) => contrastPairs.every(([foreground, background, minimum]) => {
  const light = Math.max(luminance(palette[foreground]), luminance(palette[background]));
  const dark = Math.min(luminance(palette[foreground]), luminance(palette[background]));
  return (light + 0.05) / (dark + 0.05) >= minimum;
});

export function applyPlatformTheme(webApp = globalThis.Telegram?.WebApp) {
  const fallback = palettes[webApp?.colorScheme === "light" ? "light" : "dark"];
  const values = Object.fromEntries(
    Object.entries(mapping).map(([token, key]) => [token, webApp?.themeParams?.[key]]),
  );
  const palette = Object.values(values).every(validColor) && hasRequiredContrast(values)
    ? values
    : fallback;
  for (const [name, value] of Object.entries(palette)) {
    document.documentElement.style.setProperty(name, value);
  }
  webApp?.ready?.();
  webApp?.expand?.();
  return palette;
}
