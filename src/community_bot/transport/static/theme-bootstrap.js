(() => {
  const parameters = new URLSearchParams(location.search);

  const allowed = new Set(["system", "light", "dark"]);
  const storageKey = "community_bot_ui_theme";
  const requested = parameters.get("theme");
  let stored = null;
  try {
    stored = localStorage.getItem(storageKey);
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
  const root = document.documentElement;
  root.dataset.uiThemeScope = "next";
  root.dataset.themePreference = preference;
  root.dataset.theme = resolved;
  root.style.colorScheme = resolved;
})();
