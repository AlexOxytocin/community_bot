const FULLSCREEN_STORAGE_KEY = "community_bot_fullscreen_enabled";
const PLATFORM_INSET_EVENTS = Object.freeze([
  "safeAreaChanged",
  "contentSafeAreaChanged",
  "fullscreenChanged",
  "viewportChanged",
]);
let viewportListenersInstalled = false;

const insetValue = (inset, edge) => {
  const value = Number(inset?.[edge]);
  return Number.isFinite(value) && value > 0 ? value : 0;
};

function syncPlatformInsets(webApp) {
  const root = document.documentElement;
  const safeArea = webApp?.safeAreaInset;
  const contentSafeArea = webApp?.contentSafeAreaInset;
  for (const edge of ["top", "right", "bottom", "left"]) {
    const value = Math.max(
      insetValue(safeArea, edge),
      insetValue(contentSafeArea, edge),
    );
    root.style.setProperty(`--app-safe-area-inset-${edge}`, `${value}px`);
  }
  root.dataset.telegramFullscreen = String(webApp?.isFullscreen === true);
}

function syncVisualViewport() {
  const viewport = globalThis.visualViewport;
  const width = Number(viewport?.width) || globalThis.innerWidth || 0;
  const height = Number(viewport?.height) || globalThis.innerHeight || 0;
  const offsetLeft = Number(viewport?.offsetLeft) || 0;
  const offsetTop = Number(viewport?.offsetTop) || 0;
  const layoutHeight = globalThis.innerHeight || document.documentElement.clientHeight || height;
  const keyboardInset = Math.max(0, layoutHeight - height - offsetTop);
  const root = document.documentElement;
  root.style.setProperty("--app-visual-viewport-width", `${width}px`);
  root.style.setProperty("--app-visual-viewport-height", `${height}px`);
  root.style.setProperty("--app-visual-viewport-offset-left", `${offsetLeft}px`);
  root.style.setProperty("--app-visual-viewport-offset-top", `${offsetTop}px`);
  root.style.setProperty("--app-visual-viewport-center-x", `${offsetLeft + (width / 2)}px`);
  root.style.setProperty("--app-keyboard-inset", `${keyboardInset}px`);
  root.dataset.keyboardOpen = String(keyboardInset > 80);
}

function installVisualViewportListeners() {
  if (viewportListenersInstalled) return;
  viewportListenersInstalled = true;
  const refresh = () => requestAnimationFrame(syncVisualViewport);
  globalThis.visualViewport?.addEventListener?.("resize", refresh);
  globalThis.visualViewport?.addEventListener?.("scroll", refresh);
  globalThis.addEventListener?.("resize", refresh);
  document.addEventListener("focusin", (event) => {
    if (!(event.target instanceof HTMLElement)) return;
    if (!event.target.closest('[role="dialog"]')) return;
    requestAnimationFrame(() => {
      syncVisualViewport();
      event.target.scrollIntoView({ block: "nearest", inline: "nearest" });
    });
  });
  syncVisualViewport();
}

export function getFullscreenPreference() {
  try {
    return localStorage.getItem(FULLSCREEN_STORAGE_KEY) !== "false";
  } catch {
    return true;
  }
}

function applyFullscreenMode(enabled, webApp) {
  const method = enabled ? "requestFullscreen" : "exitFullscreen";
  if (enabled ? webApp?.isFullscreen === true : webApp?.isFullscreen !== true) return;
  if (typeof webApp?.[method] !== "function") return;
  try {
    webApp[method]();
  } catch { /* Telegram clients before Bot API 8.0 keep the expanded fallback. */ }
}

export function setFullscreenPreference(enabled, webApp = globalThis.Telegram?.WebApp) {
  const normalized = enabled === true;
  try {
    localStorage.setItem(FULLSCREEN_STORAGE_KEY, String(normalized));
  } catch { /* The preference remains active for the current document. */ }
  applyFullscreenMode(normalized, webApp);
  return normalized;
}

export function applyPlatformTheme(webApp = globalThis.Telegram?.WebApp) {
  if (document.documentElement.dataset.uiThemeScope !== "next") {
    document.documentElement.style.colorScheme = "dark";
  }
  webApp?.ready?.();
  webApp?.expand?.();
  installVisualViewportListeners();
  syncPlatformInsets(webApp);
  for (const event of PLATFORM_INSET_EVENTS) {
    webApp?.onEvent?.(event, () => syncPlatformInsets(webApp));
  }
  applyFullscreenMode(getFullscreenPreference(), webApp);
}

const THEME_STORAGE_KEY = "community_bot_ui_theme";
export const PREVIEW_THEME_PREFERENCES = Object.freeze(["system", "light", "dark"]);

const validThemePreference = (value) => (
  PREVIEW_THEME_PREFERENCES.includes(value) ? value : "system"
);

export function getPreviewThemePreference() {
  const fromDocument = document.documentElement.dataset.themePreference;
  if (PREVIEW_THEME_PREFERENCES.includes(fromDocument)) return fromDocument;
  try {
    return validThemePreference(localStorage.getItem(THEME_STORAGE_KEY));
  } catch {
    return "system";
  }
}

function resolvePreviewTheme(preference, webApp) {
  if (preference !== "system") return preference;
  if (webApp?.colorScheme === "light" || webApp?.colorScheme === "dark") {
    return webApp.colorScheme;
  }
  return globalThis.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function syncTelegramChrome(webApp) {
  const styles = getComputedStyle(document.documentElement);
  const background = styles.getPropertyValue("--app-background").trim();
  const surface = styles.getPropertyValue("--app-surface").trim();
  for (const [method, color] of [
    ["setHeaderColor", background],
    ["setBackgroundColor", background],
    ["setBottomBarColor", surface],
  ]) {
    if (typeof webApp?.[method] !== "function") continue;
    try {
      webApp[method](color);
    } catch { /* Older Telegram clients can reject unsupported chrome methods. */ }
  }
}

export function applyPreviewTheme(
  preference = getPreviewThemePreference(),
  webApp = globalThis.Telegram?.WebApp,
) {
  const normalized = validThemePreference(preference);
  const resolved = resolvePreviewTheme(normalized, webApp);
  const root = document.documentElement;
  root.dataset.uiThemeScope = "next";
  root.dataset.themePreference = normalized;
  root.dataset.theme = resolved;
  root.style.colorScheme = resolved;
  try {
    localStorage.setItem(THEME_STORAGE_KEY, normalized);
  } catch { /* Theme remains active for the current document. */ }
  syncTelegramChrome(webApp);
  return { preference: normalized, resolved };
}

export function watchSystemPreviewTheme(webApp = globalThis.Telegram?.WebApp) {
  const refresh = () => {
    if (getPreviewThemePreference() === "system") applyPreviewTheme("system", webApp);
  };
  webApp?.onEvent?.("themeChanged", refresh);
  const media = globalThis.matchMedia?.("(prefers-color-scheme: light)");
  media?.addEventListener?.("change", refresh);
  return () => {
    webApp?.offEvent?.("themeChanged", refresh);
    media?.removeEventListener?.("change", refresh);
  };
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
