(() => {
  const parameters = new URLSearchParams(location.search);

  const allowed = new Set(["system", "light", "dark"]);
  const allowedPresets = new Set(["acid", "neon"]);
  const storageKey = "community_bot_ui_theme";
  const presetStorageKey = "community_bot_ui_theme_preset";
  const requested = parameters.get("theme");
  const requestedPreset = parameters.get("preset");
  let stored = null;
  let storedPreset = null;
  try {
    stored = localStorage.getItem(storageKey);
    storedPreset = localStorage.getItem(presetStorageKey);
  } catch { /* Storage can be unavailable inside hardened webviews. */ }
  const preference = allowed.has(requested)
    ? requested
    : allowed.has(stored)
      ? stored
      : "system";
  if (allowed.has(requested)) {
    try {
      localStorage.setItem(storageKey, preference);
    } catch { /* The in-memory preference still applies for this document. */ }
  }
  const telegramScheme = globalThis.Telegram?.WebApp?.colorScheme;
  const systemScheme = telegramScheme === "light" || telegramScheme === "dark"
    ? telegramScheme
    : globalThis.matchMedia?.("(prefers-color-scheme: light)").matches
      ? "light"
      : "dark";
  const resolved = preference === "system" ? systemScheme : preference;
  const preset = allowedPresets.has(requestedPreset)
    ? requestedPreset
    : allowedPresets.has(storedPreset)
      ? storedPreset
      : resolved === "dark" ? "acid" : "neon";
  if (allowedPresets.has(requestedPreset)) {
    try {
      localStorage.setItem(presetStorageKey, preset);
    } catch { /* The in-memory preset still applies for this document. */ }
  }
  const root = document.documentElement;
  root.dataset.uiThemeScope = "next";
  root.dataset.themePreset = preset;
  root.dataset.themePreference = preference;
  root.dataset.theme = resolved;
  root.style.colorScheme = resolved;
})();
