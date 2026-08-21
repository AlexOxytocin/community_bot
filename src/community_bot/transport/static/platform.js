export function applyPlatformTheme(webApp = globalThis.Telegram?.WebApp) {
  document.documentElement.style.colorScheme = "dark";
  webApp?.ready?.();
  webApp?.expand?.();
}

export function openExternalLink(url, { telegram = false } = {}, webApp = globalThis.Telegram?.WebApp) {
  if (telegram && typeof webApp?.openTelegramLink === "function") {
    try {
      webApp.openTelegramLink(url);
      return true;
    } catch { /* Continue through the safe fallback chain. */ }
  }
  if (typeof webApp?.openLink === "function") {
    try {
      webApp.openLink(url);
      return true;
    } catch { /* Continue to the browser fallback. */ }
  }
  try {
    return globalThis.open(url, "_blank", "noopener,noreferrer") !== null;
  } catch {
    return false;
  }
}
