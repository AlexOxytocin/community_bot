export function applyPlatformTheme(webApp = globalThis.Telegram?.WebApp) {
  document.documentElement.style.colorScheme = "dark";
  webApp?.ready?.();
  webApp?.expand?.();
}
