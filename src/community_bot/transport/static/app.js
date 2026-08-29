const assetRelease = new URL(import.meta.url).searchParams.get("release") || "local";
const {
  applyPlatformTheme,
  applyPreviewTheme,
  applyThemePreset,
  getFullscreenPreference,
  getPreviewThemePreference,
  getPreviewThemePreset,
  openExternalLink,
  setFullscreenPreference,
  watchSystemPreviewTheme,
} = await import(
  `/mini-assets/platform.js?release=${encodeURIComponent(assetRelease)}&api=themes-v1`
);

applyPlatformTheme();
applyThemePreset();
applyPreviewTheme();
watchSystemPreviewTheme();

const content = document.getElementById("content");
const title = document.getElementById("screen-title");
const back = document.getElementById("back");
const shell = document.getElementById("app");
const appLoader = document.getElementById("app-loader");
const primaryNavigation = document.getElementById("primary-navigation");
const revealApplication = () => {
  appLoader.hidden = true;
  shell.hidden = false;
  shell.removeAttribute("aria-hidden");
  document.body.classList.remove("app-booting");
};
const anchorShellScroll = () => {
  if (shell.scrollTop || shell.scrollLeft) shell.scrollTo({ top: 0, left: 0, behavior: "instant" });
};
shell.addEventListener("scroll", anchorShellScroll, { passive: true });
anchorShellScroll();
const catalogNav = document.getElementById("catalog-nav");
const profileNav = document.getElementById("profile-nav");
const participantsNav = document.getElementById("participants-nav");
const moderationNav = document.getElementById("moderation-nav");
const heading = title.parentElement;
let tasks = [];
let assignments = [];
let ownedTasks = [];
let ownedReviews = [];
let takenTasksQuery = "";
let createdTasksQuery = "";
let archivedTasksQuery = "";
let ownedTaskListScope = "active";
let ownedArchiveRole = "created";
let takenTasksSort = "created_desc";
let createdTasksSort = "created_desc";
let archivedTasksSort = "archive_desc";
const archiveTaskSortOptions = [
  ["Недавно в архиве", "archive_desc"],
  ["Давно в архиве", "archive_asc"],
  ["Срок ближе", "deadline_asc"],
  ["Срок дальше", "deadline_desc"],
];
const emptyOwnedArchiveFilters = () => ({ status: "", performers: "", archivedUntil: "" });
let ownedArchiveFilters = emptyOwnedArchiveFilters();
const emptyCatalogFilters = () => ({
  query: "",
  taskKind: "",
  format: "",
  category: "",
  timeSize: "",
  minSlots: "",
  minReward: "",
  deadlineUntil: "",
  city: "",
});
let catalogFilters = emptyCatalogFilters();
let takenTasksFilters = emptyCatalogFilters();
let createdTasksFilters = emptyCatalogFilters();
let catalogSort = "created_desc";
const catalogSortOptions = [
  ["Создано позже", "created_desc"],
  ["Создано раньше", "created_asc"],
  ["Срок ближе", "deadline_asc"],
  ["Срок дальше", "deadline_desc"],
  ["Награда выше", "reward_desc"],
  ["Награда ниже", "reward_asc"],
];
const pendingAcceptKeys = new Map();
let pendingTaskCreation = null;
let returnFocusTaskId = null;
let returnFocusAssignmentId = null;
let returnFocusReviewId = null;
let returnFocusOwnedTaskId = null;
let returnFocusModeration = false;
let returnFocusModerationCaseId = null;
let returnFocusProfile = false;
let returnFocusLeaderboardTab = false;
let screenRevision = 0;
let currentMemberId = null;
let currentMemberTimezone = "UTC";
let activeProfileState = null;
let memberProfileHasInternalHistory = false;
let headerBackAction = null;
let canGrantCredits = false;
let administratorPermissions = [];
let creditGrantDraft = null;

const element = (tag, text, className) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
};

const trashIcon = () => {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML = '<path d="M4 7h16M9 7V4h6v3m3 0-1 13H7L6 7m4 4v5m4-5v5"/>';
  return svg;
};

const cameraIcon = () => {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML = '<path d="M4 8.5h3l1.5-2h7l1.5 2h3v10H4z"/><circle cx="12" cy="13.5" r="3.25"/>';
  return svg;
};

const markTransition = (node, id, trigger) => {
  node.dataset.transitionId = id;
  node.dataset.transitionTrigger = trigger;
  return node;
};

const resetScrollPosition = () => {
  const options = { top: 0, left: 0, behavior: "instant" };
  content.closest(".screen")?.scrollTo(options);
  shell.scrollTo(options);
  document.scrollingElement?.scrollTo({ top: 0, left: 0, behavior: "instant" });
  globalThis.scrollTo({ top: 0, left: 0, behavior: "instant" });
};

const replaceContent = (...nodes) => {
  shell.querySelector(
    ".catalog-sort-backdrop, .catalog-filter-backdrop, .task-size-backdrop, .assignment-action-backdrop, .profile-editor-backdrop, .admin-sheet-backdrop, .theme-picker-backdrop",
  )?.remove();
  content.replaceChildren(...nodes);
  revealApplication();
  resetScrollPosition();
  queueMicrotask(resetScrollPosition);
  requestAnimationFrame(resetScrollPosition);
};

const connectedScreenIds = new Set(`
T01 T02 T03 T03A T04B T05 T06 T08
P01 P02 P03 P04 P05 P06 P07 P08
M01 M02 M03 M04 M05 M06 M07 M08 M09 M10 M11 M12 M13 M14 M15
S01 S02 S03 S04
`.trim().split(/\s+/));
const productRouteFor = (id) => {
  if (["T01", "T02"].includes(id)) return "#/catalog";
  if (["T03", "T03A"].includes(id)) return "#/tasks/:task_id";
  if (id.startsWith("T")) return "#/compose/tasks/:draft_id?";
  if (["M01", "M02", "M09"].includes(id)) return "#/work";
  if (id.startsWith("M")) return "#/work/:resource_id";
  if (["P01", "P05", "P08"].includes(id)) return "#/members";
  if (["P02", "P03", "P04"].includes(id)) return "#/members/:member_id";
  if (id.startsWith("P")) return "#/profile";
  return "#/moderation/:case_id?";
};
const resourceRoute = (pattern, resourceId) => {
  const required = pattern.match(/:\w+(?!\?)/g) || [];
  if (required.length && !resourceId) return null;
  const values = [resourceId].filter(Boolean).map(encodeURIComponent);
  let index = 0;
  return pattern
    .replace(/\/:(\w+)\?/g, () => values[index] ? `/${values[index++]}` : "")
    .replace(/:(\w+)/g, () => values[index++] || "");
};

const presentationLocationFor = (id, resourceId) => {
  const pattern = productRouteFor(id);
  const route = resourceRoute(pattern, resourceId);
  return route ? `${route}?view_state=${id.toLowerCase()}` : null;
};
const presentationScreen = (id) => connectedScreenIds.has(id) ? { id } : null;
const presentationFromLocation = () => {
  const [path, query = ""] = location.hash.split("?", 2);
  const id = new URLSearchParams(query).get("view_state")?.toUpperCase();
  const screen = presentationScreen(id);
  if (!screen) return null;
  const expected = productRouteFor(id).split("/");
  const actual = path.split("/");
  const requiredLength = expected.filter((part) => !part.startsWith(":") || !part.endsWith("?")).length;
  if (actual.length < requiredLength || actual.length > expected.length) return null;
  const resources = [];
  for (let index = 0; index < actual.length; index += 1) {
    if (expected[index]?.startsWith(":")) {
      let resource;
      try {
        resource = decodeURIComponent(actual[index]);
      } catch {
        return null;
      }
      if (!/^[A-Za-z0-9._~-]+$/.test(resource)) return null;
      resources.push(resource);
    }
    else if (expected[index] !== actual[index]) return null;
  }
  return { screen, resourceId: resources.at(-1) || null };
};

const section = (heading, value) => {
  const node = element("section", undefined, "section");
  node.append(element("h3", heading), element("p", value, "muted"));
  return node;
};

const memberProfileButton = (memberId, displayName, role) => {
  const button = element("button", displayName, "assignment-detail-person-button");
  button.type = "button";
  button.setAttribute("aria-label", `Открыть профиль ${role} ${displayName}`);
  button.addEventListener("click", () => showMemberProfile(memberId));
  return button;
};

const setHeaderControl = (
  kind = null,
  { label = null, screenLabel = null, hideTitle = false, onBack = null } = {},
) => {
  const normalized = kind === "back" || kind === "close" ? kind : null;
  const titleless = normalized === "close" || hideTitle;
  headerBackAction = normalized && onBack ? onBack : null;
  back.classList.toggle("hidden", normalized === null);
  back.dataset.navigationKind = normalized || "none";
  back.textContent = normalized === "close" ? "×" : "‹";
  back.setAttribute("aria-label", label || (normalized === "close" ? "Закрыть" : "Назад"));
  heading.classList.toggle("navigation-close", normalized === "close");
  heading.classList.toggle("navigation-titleless", titleless);
  if (titleless) {
    const screenNode = content.closest(".screen");
    screenNode.removeAttribute("aria-labelledby");
    screenNode.setAttribute("aria-label", screenLabel || "Экран");
  }
};

const setNavigation = (screen, context) => {
  if (screen !== "profile") activeProfileState = null;
  heading.querySelector(".heading-action")?.remove();
  heading.classList.remove("admin-rights-heading", "credit-grant-heading");
  const screenNode = content.closest(".screen");
  if (screen === "settings") {
    screenNode.removeAttribute("aria-labelledby");
    screenNode.setAttribute("aria-label", "Параметры");
  } else {
    screenNode.removeAttribute("aria-label");
    screenNode.setAttribute("aria-labelledby", "screen-title");
  }
  shell.classList.toggle("context-screen", context);
  shell.classList.toggle("catalog-screen", screen === "catalog");
  shell.classList.toggle("participants-screen", screen === "participants");
  shell.classList.toggle("profile-screen", screen === "profile");
  shell.classList.toggle("settings-screen", screen === "settings");
  shell.classList.toggle("task-home-screen", screen === "task-home");
  shell.classList.toggle("onboarding-screen", screen === "onboarding");
  shell.classList.toggle("moderation-screen", screen === "moderation" && !context);
  primaryNavigation.hidden = screen === "onboarding" || context;
  shell.classList.remove("catalog-filter-screen", "task-creation-screen");
  document.body.classList.toggle("ui-next-tasks-home", screen === "task-home");
  shell.classList.remove("task-detail-screen", "assignment-detail-screen", "assignment-review-screen");
  catalogNav.setAttribute("aria-pressed", String(screen === "catalog" || screen === "task-home"));
  profileNav.setAttribute("aria-pressed", String(screen === "profile" || screen === "settings"));
  participantsNav.setAttribute("aria-pressed", String(screen === "participants"));
  moderationNav.setAttribute("aria-pressed", String(screen === "moderation"));
  setHeaderControl(context ? "back" : null);
};

const setHeadingAction = (action) => {
  heading.querySelector(".heading-action")?.remove();
  action.classList.add("heading-action");
  heading.append(action);
};

const searchIcon = () => {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML = '<circle cx="11" cy="11" r="6"/><path d="m16 16 4 4"/>';
  return svg;
};

const slidersIcon = () => {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML = '<path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/>';
  return svg;
};

const sortIcon = () => {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML = '<path d="M8 5v14M5 8l3-3 3 3M16 19V5m-3 11 3 3 3-3"/>';
  return svg;
};

const calendarIcon = () => {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML = '<path d="M6 3v3M18 3v3M4 9h16M5 5h14a1 1 0 0 1 1 1v14H4V6a1 1 0 0 1 1-1Z"/>';
  return svg;
};

const settingsRowIcon = (name) => {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML = name === "profile"
    ? '<path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM5 20a7 7 0 0 1 14 0"/>'
    : name === "fullscreen"
      ? '<path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"/>'
      : '<path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6 7 7M17 17l1.4 1.4M18.4 5.6 17 7M7 17l-1.4 1.4M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z"/>';
  return svg;
};

const connectedBoundary = (screenId, state, ...nodes) => {
  const boundary = element("section", undefined, "state-view concept-screen");
  boundary.dataset.screenId = screenId;
  boundary.dataset.state = state;
  boundary.dataset.uiEngine = "concept-05";
  boundary.append(...nodes);
  return boundary;
};

const showActionConfirmation = ({
  screenId,
  headingText,
  description,
  confirmLabel,
  onConfirm,
  onEdit,
  transitionId,
  transitionTrigger,
  hideHeading = false,
  showEdit = true,
  onBack = null,
}) => {
  title.textContent = headingText;
  if (hideHeading) {
    setHeaderControl("back", { screenLabel: headingText, hideTitle: true, onBack });
  }
  const card = element("article", undefined, "card detail route-accent confirm-screen");
  card.append(element("p", "Подтверждение", "badge"), element("p", description, "muted"));
  const actions = element("div", undefined, "confirm-actions");
  let edit = null;
  if (showEdit) {
    edit = element("button", "Изменить", "secondary");
    edit.type = "button";
    edit.addEventListener("click", onEdit);
    actions.append(edit);
  }
  const confirm = element("button", confirmLabel, "primary");
  confirm.type = "button";
  if (transitionId) markTransition(confirm, transitionId, transitionTrigger);
  const status = element("p", "", "status hidden");
  status.setAttribute("aria-live", "polite");
  confirm.addEventListener("click", () => onConfirm({ confirm, edit, status }));
  actions.append(confirm);
  card.append(actions, status);
  replaceContent(connectedBoundary(screenId, "confirm", card));
  confirm.focus({ preventScroll: true });
};

const GET_CACHE_TTL_MS = 60_000;
const jsonCache = new Map();
const jsonRequests = new Map();
let jsonCacheGeneration = 0;

const jsonCacheKey = (path) => {
  const url = new URL(path, location.origin);
  url.searchParams.sort();
  return `GET ${url.pathname}${url.search}`;
};

const clearJsonCache = () => {
  jsonCache.clear();
  jsonRequests.clear();
  jsonCacheGeneration += 1;
};
const cachedJson = (path) => jsonCache.get(jsonCacheKey(path))?.data;
const storeJson = (path, data) => {
  jsonCache.set(jsonCacheKey(path), { data, storedAt: Date.now() });
  return data;
};

const apiFetch = async (path, options = {}) => {
  const response = await fetch(path, options);
  const method = (options.method || "GET").toUpperCase();
  if (response.status === 401) clearJsonCache();
  else if (response.ok && method !== "GET") {
    clearJsonCache();
  }
  return response;
};

const configureRoleNavigation = async () => {
  try {
    const overview = await getJson("/api/v1/administration");
    canGrantCredits = Boolean(overview.can_grant_credits);
    administratorPermissions = overview.actor_permissions || [];
    for (const tabs of document.querySelectorAll(".admin-tabs")) {
      const count = tabs.dataset.disputeCount === undefined ? null : Number(tabs.dataset.disputeCount);
      tabs.replaceWith(moderationTabs(tabs.dataset.active, count));
    }
    moderationNav.hidden = false;
  } catch {
    try {
      await getJson("/api/v1/moderation/cases?limit=1");
      moderationNav.hidden = false;
    } catch {
      moderationNav.hidden = true;
    }
  }
};

const restoreModerationFocus = () => {
  if (returnFocusModeration) moderationNav.focus({ preventScroll: true });
  returnFocusModeration = false;
};

const restoreProfileFocus = () => {
  if (returnFocusProfile) profileNav.focus({ preventScroll: true });
  returnFocusProfile = false;
};

const validTimezone = (value) => {
  try {
    new Intl.DateTimeFormat("en", { timeZone: value }).format();
    return value;
  } catch {
    return "UTC";
  }
};
const setMemberTimezone = (value) => {
  currentMemberTimezone = validTimezone(value || "UTC");
};
const timezoneOffsetLabel = (timezone, value = new Date()) => {
  try {
    const offset = new Intl.DateTimeFormat("en", {
      timeZone: validTimezone(timezone || "UTC"),
      timeZoneName: "longOffset",
    }).formatToParts(value).find((part) => part.type === "timeZoneName")?.value || "GMT";
    if (offset === "GMT") return "UTC+00:00";
    return offset.replace(/^GMT/, "UTC").replace("-", "−");
  } catch {
    return "UTC+00:00";
  }
};
const memberDateFormatter = (options = {}) => new Intl.DateTimeFormat("ru", {
  ...options,
  timeZone: options.timeZone || currentMemberTimezone,
});
const memberDateParts = (value) => Object.fromEntries(
  new Intl.DateTimeFormat("en-CA", {
    timeZone: currentMemberTimezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(value))
    .filter((part) => part.type !== "literal")
    .map((part) => [part.type, part.value]),
);
const memberDateKey = (value) => {
  const parts = memberDateParts(value);
  return `${parts.year}-${parts.month}-${parts.day}`;
};
const memberTimeKey = (value) => {
  const parts = memberDateParts(value);
  return `${parts.hour}:${parts.minute}`;
};
const memberDateTimeValue = (value) => `${memberDateKey(value)}T${memberTimeKey(value)}`;
const memberWallTimeToDate = (value) => {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/);
  if (!match) return null;
  const desired = match.slice(1).map(Number);
  const desiredEpoch = Date.UTC(desired[0], desired[1] - 1, desired[2], desired[3], desired[4]);
  let candidate = desiredEpoch;
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const parts = memberDateParts(candidate);
    const observed = Date.UTC(
      Number(parts.year),
      Number(parts.month) - 1,
      Number(parts.day),
      Number(parts.hour),
      Number(parts.minute),
    );
    const correction = desiredEpoch - observed;
    candidate += correction;
    if (!correction) break;
  }
  const finalParts = memberDateParts(candidate);
  const finalValue = `${finalParts.year}-${finalParts.month}-${finalParts.day}T${finalParts.hour}:${finalParts.minute}`;
  return finalValue === value ? new Date(candidate) : null;
};

const formatDate = (value) => memberDateFormatter({
  dateStyle: "medium",
  timeStyle: "short",
}).format(new Date(value));

const time = (value) => {
  const node = element("time", formatDate(value));
  node.dateTime = value;
  return node;
};

const dateSection = (heading, value) => {
  const node = element("section", undefined, "section");
  node.append(element("h3", heading), time(value));
  return node;
};

const requestError = (response) => {
  if (response.status === 401) return "session_expired";
  if (response.status === 403) return "account_unavailable";
  if (response.status === 404) return "not_found";
  return "request_failed";
};

const fetchJson = (path) => {
  const key = jsonCacheKey(path);
  if (jsonRequests.has(key)) return jsonRequests.get(key);
  const generation = jsonCacheGeneration;
  let request;
  request = apiFetch(path, { credentials: "same-origin" })
    .then(async (response) => {
      if (!response.ok) throw new Error(requestError(response));
      if (!response.headers.get("content-type")?.includes("application/json")) {
        throw new Error("request_failed");
      }
      const data = await response.json();
      if (generation !== jsonCacheGeneration) throw new Error("request_obsolete");
      return storeJson(path, data);
    })
    .finally(() => {
      if (jsonRequests.get(key) === request) jsonRequests.delete(key);
    });
  jsonRequests.set(key, request);
  return request;
};

const getJson = (path, onRefresh) => {
  const entry = jsonCache.get(jsonCacheKey(path));
  if (!entry) return fetchJson(path);
  if (Date.now() - entry.storedAt >= GET_CACHE_TTL_MS) {
    const refresh = fetchJson(path);
    if (onRefresh) void refresh.then(onRefresh).catch(() => {});
    else void refresh.catch(() => {});
  }
  return Promise.resolve(entry.data);
};

const assignmentError = (code, retry) => {
  if (code === "session_expired") {
    return [element("p", "Сессия истекла. Закройте и снова откройте Mini App.", "status")];
  }
  if (code === "account_unavailable") {
    return [element("p", "Назначения недоступны для этого аккаунта.", "status")];
  }
  if (code === "not_found") {
    return [element("p", "Назначение больше не входит в активные.", "status")];
  }
  const nodes = [element("p", "Не удалось загрузить активные назначения.", "status")];
  if (retry) nodes.push(retry);
  return nodes;
};

const assignmentStatus = (value) => ({
  accepted: "Принято",
  submitted: "Результат отправлен",
  rejected_pending_dispute: "Ожидает решения",
  disputed: "Открыт спор",
  reviewer_required: "Нужен проверяющий",
  approved: "Принято",
  partially_approved: "Принято частично",
}[value] || value);

const newOperationKey = () => {
  const words = new Uint32Array(2);
  crypto.getRandomValues(words);
  const value = ((BigInt(words[0]) << 32n) | BigInt(words[1])) & 0x7fffffffffffffffn;
  return (value || 1n).toString();
};

function showCatalogSortSheet(
  trigger,
  {
    sortOptions = catalogSortOptions,
    selectedSort = catalogSort,
    onSelect = (value) => {
      catalogSort = value;
      showCatalog();
    },
  } = {},
) {
  shell.querySelector(".catalog-sort-backdrop, .catalog-filter-backdrop")?.remove();
  const backdrop = element("section", undefined, "catalog-sort-backdrop");
  const dialog = element("div", undefined, "catalog-sort-sheet");
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.setAttribute("aria-labelledby", "catalog-sort-title");
  const header = element("div", undefined, "catalog-sort-heading");
  const sortTitle = element("h2", "Сортировка");
  sortTitle.id = "catalog-sort-title";
  const close = element("button", "×", "catalog-sort-close");
  close.type = "button";
  close.setAttribute("aria-label", "Закрыть сортировку");
  header.append(sortTitle, close);
  const options = element("div", undefined, "catalog-sort-options");
  options.setAttribute("role", "radiogroup");
  options.setAttribute("aria-label", "Способ сортировки");
  let selectedOption = null;
  const dismiss = (restoreFocus = true) => {
    backdrop.remove();
    if (restoreFocus) trigger.focus({ preventScroll: true });
  };
  for (const [label, value] of sortOptions) {
    const option = element("button", undefined, "catalog-sort-option");
    option.type = "button";
    option.setAttribute("role", "radio");
    option.setAttribute("aria-checked", String(value === selectedSort));
    option.append(element("span", label), element("span", value === selectedSort ? "✓" : "", "catalog-sort-check"));
    if (value === selectedSort) {
      option.classList.add("is-selected");
      selectedOption = option;
    }
    option.addEventListener("click", () => {
      dismiss(false);
      onSelect(value);
      queueMicrotask(() => content.querySelector(".catalog-sort-button")?.focus({ preventScroll: true }));
    });
    options.append(option);
  }
  close.addEventListener("click", () => dismiss());
  backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop) dismiss();
  });
  dialog.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      dismiss();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = [close, ...options.querySelectorAll("button")];
    const first = focusable[0];
    const last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
  dialog.append(header, options);
  backdrop.append(dialog);
  shell.append(backdrop);
  queueMicrotask(() => (selectedOption || close).focus({ preventScroll: true }));
}

function buildCatalogFilterForm({
  onApply,
  onReset,
  filters = catalogFilters,
  sourceTasks = tasks,
  onChange = (value) => { catalogFilters = value; },
}) {
  const form = element("form", undefined, "task-form catalog-filter-form");
  const labeledInput = (labelText, name, type = "text") => {
    const label = element("label", labelText);
    const input = element("input");
    input.name = name;
    input.type = type;
    input.setAttribute("aria-label", labelText);
    label.append(input);
    return { label, input };
  };
  const labeledSelect = (labelText, name, options) => {
    const label = element("label", labelText);
    const select = element("select");
    select.name = name;
    select.setAttribute("aria-label", labelText);
    for (const [text, value] of options) select.append(new Option(text, value));
    label.append(select);
    return { label, select };
  };
  const row = (...fields) => {
    const grid = element("div", undefined, "form-grid two-columns");
    grid.append(...fields);
    return grid;
  };
  const kindField = labeledSelect("Тип задания", "taskKind", [
    ["Любой", ""], ["Личное", "solo"], ["Групповое", "group"],
  ]);
  kindField.select.value = filters.taskKind;
  const formatField = labeledSelect("Формат", "format", [
    ["Любой", ""], ["Онлайн", "online"], ["Офлайн", "offline"],
  ]);
  formatField.select.value = filters.format;
  const categories = [...new Set(sourceTasks.map((task) => task.category_name).filter(Boolean))]
    .sort((left, right) => left.localeCompare(right, "ru"));
  const categoryField = labeledSelect("Категория", "category", [
    ["Любая", ""], ...categories.map((category) => [category, category]),
  ]);
  categoryField.select.value = filters.category;
  const sizeField = labeledSelect("Размер", "timeSize", [
    ["Любой", ""], ["XS", "xs"], ["S", "s"], ["M", "m"], ["L", "l"], ["XL", "xl"],
  ]);
  sizeField.select.value = filters.timeSize;
  const slotsField = labeledInput("Мест от", "minSlots", "number");
  slotsField.input.min = "1";
  slotsField.input.inputMode = "numeric";
  slotsField.input.value = filters.minSlots;
  const rewardField = labeledInput("Награда от", "minReward", "number");
  rewardField.input.min = "1";
  rewardField.input.inputMode = "numeric";
  rewardField.input.value = filters.minReward;
  const deadlineField = labeledInput("Срок до", "deadlineUntil", "date");
  deadlineField.input.value = filters.deadlineUntil;
  const cityField = labeledInput("Город", "city");
  cityField.label.classList.add("catalog-city-filter");
  cityField.input.placeholder = "Начните вводить город";
  cityField.input.value = filters.city;
  const updateCityVisibility = () => cityField.label.classList.toggle(
    "hidden", formatField.select.value !== "offline",
  );
  formatField.select.addEventListener("change", updateCityVisibility);
  updateCityVisibility();
  const reset = element("button", "Сбросить", "secondary");
  reset.type = "button";
  const apply = element("button", "Применить", "primary");
  apply.type = "submit";
  const filterActions = element("div", undefined, "catalog-filter-actions");
  filterActions.append(reset, apply);
  form.append(
    row(kindField.label, formatField.label),
    categoryField.label,
    row(sizeField.label, slotsField.label),
    row(rewardField.label, deadlineField.label),
    cityField.label,
    filterActions,
  );
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    onChange({
      query: filters.query,
      taskKind: kindField.select.value,
      format: formatField.select.value,
      category: categoryField.select.value,
      timeSize: sizeField.select.value,
      minSlots: slotsField.input.value,
      minReward: rewardField.input.value,
      deadlineUntil: deadlineField.input.value,
      city: formatField.select.value === "offline" ? cityField.input.value.trim() : "",
    });
    onApply();
  });
  reset.addEventListener("click", () => {
    onChange({ ...emptyCatalogFilters(), query: filters.query });
    onReset();
  });
  return { form, initialFocus: kindField.select };
}

function showCatalogFilterSheet(trigger, {
  filters = catalogFilters,
  sourceTasks = tasks,
  onChange = (value) => { catalogFilters = value; },
  refresh = () => showCatalog(),
} = {}) {
  shell.querySelector(".catalog-sort-backdrop, .catalog-filter-backdrop")?.remove();
  const backdrop = element("section", undefined, "catalog-filter-backdrop");
  const dialog = element("div", undefined, "catalog-filter-sheet");
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.setAttribute("aria-labelledby", "catalog-filter-title");
  const header = element("div", undefined, "catalog-sort-heading");
  const filterTitle = element("h2", "Активные фильтры");
  filterTitle.id = "catalog-filter-title";
  const close = element("button", "×", "catalog-sort-close");
  close.type = "button";
  close.setAttribute("aria-label", "Закрыть фильтры");
  header.append(filterTitle, close);
  const dismiss = (restoreFocus = true) => {
    backdrop.remove();
    if (restoreFocus) trigger.focus({ preventScroll: true });
  };
  const refreshCatalogAndFocusFilter = () => {
    dismiss(false);
    refresh();
    queueMicrotask(() => content.querySelector(".catalog-filter-button")?.focus({ preventScroll: true }));
  };
  const { form, initialFocus } = buildCatalogFilterForm({
    onApply: refreshCatalogAndFocusFilter,
    onReset: refreshCatalogAndFocusFilter,
    filters,
    sourceTasks,
    onChange,
  });
  close.addEventListener("click", () => dismiss());
  backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop) dismiss();
  });
  dialog.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      dismiss();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = [close, ...form.querySelectorAll("button, input, select")]
      .filter((node) => !node.closest(".hidden"));
    const first = focusable[0];
    const last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
  dialog.append(header, form);
  backdrop.append(dialog);
  shell.append(backdrop);
  queueMicrotask(() => initialFocus.focus({ preventScroll: true }));
}

const taskMatchesFilters = (task, filters) => (
  (!filters.taskKind || task.task_kind === filters.taskKind)
  && (!filters.format || task.format === filters.format)
  && (!filters.category || task.category_name === filters.category)
  && (!filters.timeSize || task.time_size === filters.timeSize)
  && (!filters.minSlots || task.performer_slots >= Number(filters.minSlots))
  && (
    !filters.minReward
    || task.credit_reward_per_performer >= Number(filters.minReward)
  )
  && (
    !filters.deadlineUntil
    || (task.deadline_at && memberDateKey(task.deadline_at) <= filters.deadlineUntil)
  )
  && (
    !filters.city
    || String(task.city || "").toLocaleLowerCase("ru")
      .includes(filters.city.trim().toLocaleLowerCase("ru"))
  )
);

const sortTaskLikeItems = (items, selectedSort) => {
  const originalOrder = new Map(items.map((item, index) => [item.id, index]));
  const byOriginalOrder = (left, right) => originalOrder.get(left.id) - originalOrder.get(right.id);
  const finiteDate = (value, fallback) => {
    const parsed = Date.parse(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  };
  const comparators = {
    created_desc: (left, right) => finiteDate(right.created_at, 0) - finiteDate(left.created_at, 0) || byOriginalOrder(left, right),
    created_asc: (left, right) => finiteDate(left.created_at, Number.POSITIVE_INFINITY) - finiteDate(right.created_at, Number.POSITIVE_INFINITY) || byOriginalOrder(left, right),
    deadline_asc: (left, right) => finiteDate(left.deadline_at, Number.POSITIVE_INFINITY) - finiteDate(right.deadline_at, Number.POSITIVE_INFINITY) || byOriginalOrder(left, right),
    deadline_desc: (left, right) => finiteDate(right.deadline_at, 0) - finiteDate(left.deadline_at, 0) || byOriginalOrder(left, right),
    reward_desc: (left, right) => (right.credit_reward_per_performer || 0) - (left.credit_reward_per_performer || 0) || byOriginalOrder(left, right),
    reward_asc: (left, right) => (left.credit_reward_per_performer || 0) - (right.credit_reward_per_performer || 0) || byOriginalOrder(left, right),
  };
  items.sort(comparators[selectedSort] || byOriginalOrder);
  return items;
};

function catalogTasksForView() {
  const query = catalogFilters.query.trim().toLocaleLowerCase("ru");
  const visibleTasks = tasks.filter((task) => {
    const searchable = [task.title, task.description]
      .filter(Boolean).join(" ").toLocaleLowerCase("ru");
    return (
      (!query || searchable.includes(query))
      && taskMatchesFilters(task, catalogFilters)
    );
  });
  return sortTaskLikeItems(visibleTasks, catalogSort);
}

function updateCatalogResults(boundary, results) {
  const visibleTasks = catalogTasksForView();
  boundary.dataset.state = visibleTasks.length ? "content" : "empty";
  const availableStatus = element(
    "p",
    visibleTasks.length ? `Доступно заданий: ${visibleTasks.length}` : "Доступных заданий нет",
    "visually-hidden",
  );
  availableStatus.setAttribute("role", "status");
  if (!visibleTasks.length) {
    results.replaceChildren(availableStatus, element("p", "Новые задания появятся здесь.", "compact-empty"));
    return null;
  }
  const list = element("div", undefined, "list");
  let focusTarget = null;
  for (const task of visibleTasks) {
    const button = taskListCard(task);
    button.addEventListener("click", () => showTaskDetail(task));
    if (task.id === returnFocusTaskId) focusTarget = button;
    list.append(button);
  }
  results.replaceChildren(availableStatus, list);
  return focusTarget;
}

function showCatalog(revision = ++screenRevision) {
  if (revision !== screenRevision) return;
  setNavigation("catalog", false);
  title.textContent = "Задания";
  back.classList.add("hidden");
  const boundary = element("section", undefined, "state-view catalog-view");
  boundary.dataset.screenId = "T01";
  boundary.dataset.uiEngine = "concept-05";
  boundary.dataset.template = "list";
  const activeFilterCount = Object.entries(catalogFilters)
    .filter(([key, value]) => key !== "query" && Boolean(value)).length;
  const actions = element("div", undefined, "catalog-actions");
  const filterTrigger = element("button", undefined, "secondary catalog-filter-button");
  filterTrigger.type = "button";
  filterTrigger.setAttribute("aria-label", "Фильтры");
  filterTrigger.append(slidersIcon());
  if (activeFilterCount) {
    filterTrigger.classList.add("is-active");
    filterTrigger.setAttribute("aria-label", `Фильтры, выбрано: ${activeFilterCount}`);
    filterTrigger.append(element("span", String(activeFilterCount), "catalog-filter-count"));
  }
  markTransition(filterTrigger, "PE-012", "open_filters");
  filterTrigger.addEventListener("click", () => showCatalogFilterSheet(filterTrigger));
  const catalogBack = element("button", "‹", "secondary catalog-back-button");
  catalogBack.type = "button";
  catalogBack.setAttribute("aria-label", "Назад к заданиям");
  catalogBack.addEventListener("click", () => void loadTaskHome());
  const search = element("label", undefined, "catalog-search");
  const searchInput = element("input");
  searchInput.type = "search";
  searchInput.placeholder = "Название или описание";
  searchInput.setAttribute("aria-label", "Поиск по названию и описанию");
  searchInput.value = catalogFilters.query;
  search.append(searchIcon(), searchInput);
  const actionEnd = element("div", undefined, "catalog-actions-end");
  const currentSortLabel = catalogSortOptions.find(([, value]) => value === catalogSort)?.[0] || "Создано позже";
  const sort = element("button", undefined, "secondary catalog-sort-button");
  sort.type = "button";
  sort.setAttribute("aria-label", `Сортировка: ${currentSortLabel}`);
  sort.setAttribute("aria-haspopup", "dialog");
  sort.append(sortIcon());
  sort.classList.toggle("is-active", catalogSort !== "created_desc");
  sort.addEventListener("click", () => showCatalogSortSheet(sort));
  actionEnd.append(filterTrigger, sort);
  actions.append(catalogBack, search, actionEnd);
  searchInput.addEventListener("input", () => {
    catalogFilters.query = searchInput.value;
    updateCatalogResults(boundary, results);
  });
  const results = element("div", undefined, "catalog-results");
  boundary.append(actions, results);
  const focusTarget = updateCatalogResults(boundary, results);
  replaceContent(boundary);
  focusTarget?.focus({ preventScroll: true });
  returnFocusTaskId = null;
  restoreModerationFocus();
  restoreProfileFocus();
}

async function loadCatalog(push = true) {
  const revision = ++screenRevision;
  const path = "/api/v1/tasks";
  const cached = cachedJson(path);
  if (push) history.replaceState({ screen: "catalog" }, "", presentationLocationFor("T01"));
  if (cached) {
    tasks = cached.items;
    showCatalog(revision);
  } else {
    setNavigation("catalog", false);
    title.textContent = "Задания";
    back.classList.add("hidden");
    replaceContent(element("p", "Загружаем задания…", "status muted"));
  }
  try {
    const page = await getJson(path, (refreshed) => {
      if (revision !== screenRevision) return;
      tasks = refreshed.items;
      showCatalog(revision);
    });
    if (revision !== screenRevision) return;
    if (cached) return;
    tasks = page.items;
    showCatalog(revision);
  } catch {
    if (revision !== screenRevision || cached) return;
    replaceContent(element("p", "Не удалось загрузить задания.", "status"));
  }
}

function taskListCard(task, { preview = false } = {}) {
  const card = element(preview ? "article" : "button", undefined, "card task-card");
  if (!preview) card.type = "button";
  if (preview) card.classList.add("preview-task-card");
  const chips = element("div", undefined, "card-chips");
  chips.append(element("span", preview ? "Предпросмотр" : "Открыто", "chip"));
  const category = task.category_name || (task.origin === "community" ? "Сообщество" : null);
  if (category) chips.append(element("span", category, "chip muted-chip"));
  if (task.origin === "community" && category !== "Сообщество") {
    chips.append(element("span", "Сообщество", "chip muted-chip"));
  }
  const meta = element("div", undefined, "task-meta");
  if (task.created_at) {
    meta.append(element("span", `создано ${compactListDate(task.created_at)}`));
  }
  meta.append(
    element("span", `✦ ${task.credit_reward_per_performer} кред.`),
    element("span", `${task.performer_slots} ${task.performer_slots === 1 ? "место" : "места"}`),
  );
  const deadline = element(
    "time",
    task.deadline_at
      ? `до ${memberDateFormatter({ day: "numeric", month: "short" }).format(new Date(task.deadline_at))}`
      : "Срок уточняется",
  );
  if (task.deadline_at) deadline.dateTime = task.deadline_at;
  meta.append(deadline);
  const label = element("div", undefined, "task-card-title");
  label.append(element("h3", task.title));
  if (!preview) label.append(element("span", "›", "chevron"));
  card.append(chips, label, element("p", task.description, "muted"), meta);
  return card;
}

async function taskCreationCommand(body) {
  pendingTaskCreation ||= { key: newOperationKey(), body: JSON.stringify(body) };
  const response = await apiFetch("/api/v1/task-creation", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": pendingTaskCreation.key,
    },
    credentials: "same-origin",
    body: pendingTaskCreation.body,
  });
  try {
    const result = await submissionResponse(response);
    pendingTaskCreation = null;
    return result;
  } catch (error) {
    if (!retryableSubmissionError(error)) pendingTaskCreation = null;
    throw error;
  }
}

function showTaskCreation(state, forceEdit = false) {
  let draft = state.draft || { id: null, revision: 0, values: {} };
  if (!forceEdit && state.preview && !state.needs_edit) {
    const values = draft.values;
    const category = state.categories.find((item) => item.id === values.category_id);
    const card = taskListCard({
      ...values,
      title: state.preview.title,
      description: state.preview.description,
      category_name: category?.name,
      credit_reward_per_performer: values.credit_reward_per_performer,
      performer_slots: values.performer_slots,
      deadline_at: values.deadline_at,
      origin: state.preview.origin,
    }, { preview: true });
    card.append(section("Критерии", state.preview.completion_criteria));
    const publish = element("button", "Опубликовать", "primary");
    publish.type = "button";
    markTransition(publish, "PE-021", "publish_task");
    const status = element("p", "", "status hidden");
    publish.addEventListener("click", async () => {
      publish.disabled = true;
      status.className = "status";
      status.textContent = "Публикуем задание…";
      try {
        await taskCreationCommand({ action: "publish", draft_id: draft.id, expected_revision: draft.revision });
        history.replaceState({ screen: "task-creation", draftId: draft.id }, "", presentationLocationFor("T08", draft.id));
        const home = element("button", "К заданиям", "primary");
        home.addEventListener("click", () => {
          history.replaceState({ screen: "catalog" }, "", presentationLocationFor("T01"));
          void loadCatalog(false);
        });
        replaceContent(connectedBoundary("T08", "success", element("p", "Задание опубликовано.", "status success"), home));
      } catch {
        status.textContent = "Не удалось опубликовать задание. Повторите запрос.";
        publish.disabled = false;
      }
    });
    card.append(publish, status);
    return replaceContent(connectedBoundary("T06", "content", card));
  }
  const localDraftKey = (draftId = draft.id) => (
    `community-bot:task-form:${currentMemberId || "current"}:${draftId || "new"}`
  );
  const localDraftKeys = new Set([localDraftKey()]);
  const readLocalDraft = () => {
    try {
      const parsed = JSON.parse(localStorage.getItem(localDraftKey()) || "null");
      return parsed?.revision === draft.revision && parsed.values ? parsed.values : null;
    } catch {
      return null;
    }
  };
  const localValues = readLocalDraft();
  const values = { ...draft.values };
  if (localValues) {
    for (const [name, value] of Object.entries(localValues)) {
      if (!["material_text", "materials_expanded", "city_input"].includes(name)) values[name] = value;
    }
    if (Object.hasOwn(localValues, "material_text")) {
      values.materials = localValues.material_text ? { text: localValues.material_text } : {};
    }
  }
  const form = element("form", undefined, "task-form");
  form.classList.add("creation-form");
  form.innerHTML = `
    <section class="creation-group" aria-label="Формат задания">
      <div class="creation-choice-row">
        <div class="section creation-choice-field">
          <span class="field-label">Тип задания *</span>
          <select class="visually-hidden" name="task_kind" aria-label="Тип задания *" required>
            <option value="solo">Личное</option><option value="group">Групповое</option>
          </select>
          <button class="creation-choice-trigger" type="button" data-kind-trigger aria-label="Выбрать тип задания" aria-haspopup="dialog">
            <span class="creation-choice-copy"><strong data-kind-label>Личное</strong><small data-kind-summary>Один исполнитель</small></span>
            <span class="creation-choice-chevron" aria-hidden="true">›</span>
          </button>
        </div>
        <div class="section creation-choice-field">
          <span class="field-label">Формат *</span>
          <select class="visually-hidden" name="format" aria-label="Формат *" required><option value="online">Онлайн</option><option value="offline">Офлайн</option></select>
          <button class="creation-choice-trigger" type="button" data-format-trigger aria-label="Выбрать формат задания" aria-haspopup="dialog">
            <span class="creation-choice-copy"><strong data-format-label>Онлайн</strong><small data-format-summary>Удалённо</small></span>
            <span class="creation-choice-chevron" aria-hidden="true">›</span>
          </button>
        </div>
      </div>
      <label class="section slots-field" data-slots-field>Число исполнителей *<input name="performer_slots" aria-label="Число исполнителей *" type="number" min="1" required></label>
      <span class="hidden" data-city-anchor></span>
      <div class="section category-choice-field">
        <span class="field-label">Категория *</span>
        <select class="visually-hidden" name="category_id" aria-label="Категория *" required></select>
        <button class="category-choice-trigger" type="button" data-category-trigger aria-label="Выбрать категорию" aria-haspopup="dialog">
          <span class="category-choice-icon" data-category-icon aria-hidden="true"></span>
          <span class="creation-choice-copy"><strong data-category-name>Выберите категорию</strong><small data-category-description></small></span>
          <span class="creation-choice-chevron" aria-hidden="true">›</span>
        </button>
      </div>
      <div class="terms-picker-stack">
        <div class="section size-picker-field">
          <span class="field-label">Размер *</span>
          <select class="visually-hidden" name="time_size" aria-label="Размер *" required></select>
          <button class="size-picker-trigger" type="button" aria-label="Выбрать размер задания" aria-haspopup="dialog">
            <span class="size-picker-copy"><strong data-size-name>—</strong><small data-size-duration>Выберите размер</small></span>
            <span class="size-picker-chevron" aria-hidden="true">›</span>
          </button>
        </div>
        <div class="section reward-picker-field">
          <div class="reward-picker-heading"><span class="field-label">Награда за исполнителя *</span><small data-reward-hint></small></div>
          <input class="visually-hidden" name="credit_reward_per_performer" aria-label="Награда за исполнителя *" type="number" min="1" required>
          <div class="reward-options" data-reward-options role="radiogroup" aria-label="Допустимая награда"></div>
          <div class="reward-stepper hidden" data-reward-stepper>
            <button type="button" data-reward-decrease aria-label="Уменьшить награду">−</button>
            <output data-reward-value aria-live="polite"></output>
            <button type="button" data-reward-increase aria-label="Увеличить награду">+</button>
          </div>
        </div>
      </div>
      <div class="reserve-summary" data-reserve-summary>
        <span data-reserve-formula>Будет зарезервировано</span>
        <strong data-reserve>—</strong>
        <span class="reserve-meter" data-reserve-meter role="progressbar" aria-label="Использование доступных кредитов" aria-valuemin="0">
          <span data-reserve-meter-fill></span>
        </span>
      </div>
    </section>
    <section class="creation-group" aria-labelledby="creation-content-title">
      <p class="creation-group-title" id="creation-content-title">Содержание</p>
      <div class="section content-choice-field" data-content-field="title">
        <textarea class="visually-hidden" name="title" aria-label="Название *" maxlength="80" required></textarea>
        <button class="content-choice-trigger" type="button" data-content-trigger="title" aria-label="Редактировать название" aria-haspopup="dialog">
          <span class="content-choice-copy"><strong>Название *</strong><small data-content-summary="title">Коротко опишите результат</small></span><span class="creation-choice-chevron" aria-hidden="true">›</span>
        </button>
        <small class="field-error hidden" data-content-error="title" aria-live="polite"></small>
      </div>
      <div class="section content-choice-field" data-content-field="description">
        <textarea class="visually-hidden" name="description" aria-label="Что нужно сделать *" maxlength="1200" required></textarea>
        <button class="content-choice-trigger" type="button" data-content-trigger="description" aria-label="Редактировать что нужно сделать" aria-haspopup="dialog">
          <span class="content-choice-copy"><strong>Что нужно сделать *</strong><small data-content-summary="description">Опишите действия исполнителя</small></span><span class="creation-choice-chevron" aria-hidden="true">›</span>
        </button>
        <small class="field-error hidden" data-content-error="description" aria-live="polite"></small>
      </div>
      <div class="section content-choice-field" data-content-field="material_text">
        <textarea class="visually-hidden" name="material_text" aria-label="Материалы" maxlength="1000"></textarea>
        <button class="content-choice-trigger" type="button" data-content-trigger="material_text" aria-label="Редактировать материалы" aria-haspopup="dialog">
          <span class="content-choice-copy"><strong>Материалы <span class="optional-label">(необязательно)</span></strong><small data-content-summary="material_text">Ссылка или короткий текст</small></span><span class="creation-choice-chevron" aria-hidden="true">›</span>
        </button>
        <small class="field-error hidden" data-content-error="material_text" aria-live="polite"></small>
      </div>
    </section>
    <section class="creation-group" aria-labelledby="creation-terms-title">
      <p class="creation-group-title" id="creation-terms-title">Условия</p>
      <div class="section content-choice-field" data-content-field="completion_criteria">
        <textarea class="visually-hidden" name="completion_criteria" aria-label="Критерии приёмки *" maxlength="700" required></textarea>
        <button class="content-choice-trigger" type="button" data-content-trigger="completion_criteria" aria-label="Редактировать критерии приёмки" aria-haspopup="dialog">
          <span class="content-choice-copy"><strong>Критерии приёмки *</strong><small data-content-summary="completion_criteria">Добавьте проверяемые условия</small></span><span class="creation-choice-chevron" aria-hidden="true">›</span>
        </button>
        <small class="field-error hidden" data-content-error="completion_criteria" aria-live="polite"></small>
      </div>
      <div class="section deadline-choice-field">
        <input class="visually-hidden" name="deadline_at" aria-label="Срок *" type="datetime-local" required>
        <button class="category-choice-trigger deadline-choice-trigger" type="button" data-deadline-trigger aria-label="Выбрать срок" aria-haspopup="dialog">
          <span class="category-choice-icon deadline-choice-icon" data-deadline-icon aria-hidden="true"></span>
          <span class="creation-choice-copy"><strong data-deadline-date>Выберите срок *</strong><small data-deadline-time>Дата и время</small></span>
          <span class="creation-choice-chevron" aria-hidden="true">›</span>
        </button>
        <small class="field-error hidden" data-deadline-error aria-live="polite"></small>
      </div>
    </section>`;
  const resizeAutoGrow = (field) => {
    if (!field?.isConnected || field.closest(".hidden")) return;
    const maximum = field.name === "title" ? 92 : field.name === "material_text" ? 156 : 184;
    field.style.height = "auto";
    const height = Math.min(field.scrollHeight, maximum);
    field.style.height = `${height}px`;
    field.style.overflowY = field.scrollHeight > maximum ? "auto" : "hidden";
  };
  const keepControlVisible = (control) => {
    requestAnimationFrame(() => {
      const viewport = globalThis.visualViewport;
      const box = control.getBoundingClientRect();
      if (viewport && box.bottom > viewport.height - 16) {
        control.scrollIntoView({ block: "center", behavior: "smooth" });
      }
    });
  };
  for (const item of state.categories) form.category_id.append(new Option(item.icon + " " + item.name, item.id));
  for (const item of state.time_sizes) form.time_size.append(new Option(item.value.toUpperCase() + " · " + item.label, item.value));
  for (const name of ["task_kind", "category_id", "time_size", "format"]) if (values[name]) form[name].value = values[name];
  const taskKindOptions = [
    { value: "solo", label: "Личное", description: "Один исполнитель и фиксированная награда." },
    { value: "group", label: "Групповое", description: "Несколько исполнителей и общий резерв." },
  ];
  const formatOptions = [
    { value: "online", label: "Онлайн", description: "Можно выполнить удалённо." },
    { value: "offline", label: "Офлайн", description: "Нужно присутствовать в указанном городе." },
  ];
  const categoryDescription = (category) => {
    if (category?.code === "other") {
      return "Если задача не подходит ни к одной из основных категорий.";
    }
    return category?.description || `Задания категории «${category?.name || "Другое"}».`;
  };
  const communityCategory = state.categories.find((item) => item.code === "community_development");
  const isCommunityTask = () => form.category_id.value === communityCategory?.id;
  const communityRewardMax = Number(state.community_reward_max || 10);
  const syncCategoryPresentation = () => {
    const category = state.categories.find((item) => item.id === form.category_id.value);
    form.querySelector("[data-category-icon]").textContent = category?.icon || "•";
    form.querySelector("[data-category-name]").textContent = category?.name || "Выберите категорию";
    form.querySelector("[data-category-description]").textContent = categoryDescription(category);
  };
  const syncFormatPresentation = () => {
    const option = formatOptions.find((item) => item.value === form.format.value);
    form.querySelector("[data-format-label]").textContent = option?.label || "Выберите";
    form.querySelector("[data-format-summary]").textContent = option?.value === "offline"
      ? "В городе" : "Удалённо";
  };
  let groupSlots = values.task_kind === "group" && Number(values.performer_slots) >= 2
    ? Number(values.performer_slots) : 2;
  let persistDraft = () => {};
  const syncTaskKind = () => {
    const group = form.task_kind.value === "group";
    const option = taskKindOptions.find((item) => item.value === form.task_kind.value);
    form.querySelector("[data-kind-label]").textContent = option?.label || "Выберите";
    form.querySelector("[data-kind-summary]").textContent = group ? "Несколько участников" : "Один исполнитель";
    form.performer_slots.disabled = !group;
    form.performer_slots.min = group ? "2" : "1";
    form.performer_slots.value = String(group ? groupSlots : 1);
    form.querySelector("[data-slots-field]").classList.toggle("hidden", !group);
    updateReserve();
  };
  for (const name of ["title", "description", "completion_criteria"]) form[name].value = values[name] || "";
  form.material_text.value = values.materials?.text || values.materials?.url || "";
  const contentEditorSpecs = {
    title: {
      title: "Название",
      hint: "Коротко и с понятным результатом.",
      placeholder: "Например: Проверить сценарий первого запуска",
      emptySummary: "Коротко опишите результат",
      rows: 2,
    },
    description: {
      title: "Что нужно сделать",
      hint: "Опишите конкретные действия исполнителя.",
      placeholder: "Что именно нужно сделать и какой результат приложить",
      emptySummary: "Опишите действия исполнителя",
      rows: 5,
    },
    completion_criteria: {
      title: "Критерии приёмки",
      hint: "Добавьте условия, по которым можно проверить результат.",
      placeholder: "Например: результат приложен и соответствует описанию",
      emptySummary: "Добавьте проверяемые условия",
      rows: 4,
    },
    material_text: {
      title: "Материалы",
      hint: "Добавьте ссылку или короткий текст, если исполнителю нужны исходные материалы.",
      placeholder: "Ссылка или короткий текст",
      emptySummary: "Ссылка или короткий текст",
      required: false,
      rows: 4,
    },
  };
  const syncContentPresentation = (name) => {
    const value = form[name].value.trim().replace(/\s+/g, " ");
    const summary = form.querySelector(`[data-content-summary="${name}"]`);
    summary.textContent = value || contentEditorSpecs[name].emptySummary;
    summary.classList.toggle("is-filled", Boolean(value));
  };
  for (const name of Object.keys(contentEditorSpecs)) {
    form[name].addEventListener("input", () => syncContentPresentation(name));
    syncContentPresentation(name);
  }
  form.credit_reward_per_performer.value = values.credit_reward_per_performer || "";
  const deadlineTrigger = form.querySelector("[data-deadline-trigger]");
  const deadlineError = form.querySelector("[data-deadline-error]");
  form.querySelector("[data-deadline-icon]").append(calendarIcon());
  const storedDeadline = String(values.deadline_at || "");
  form.deadline_at.value = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(storedDeadline)
    ? storedDeadline
    : storedDeadline ? memberDateTimeValue(storedDeadline) : "";
  const parseLocalDateTime = memberWallTimeToDate;
  const localDateKey = memberDateKey;
  const localTimeKey = memberTimeKey;
  const ceilToFiveMinutes = (date) => {
    const rounded = new Date(date);
    rounded.setSeconds(0, 0);
    const remainder = rounded.getMinutes() % 5;
    if (remainder) rounded.setMinutes(rounded.getMinutes() + 5 - remainder);
    return rounded;
  };
  let deadlineMin;
  const refreshDeadlineMinimum = () => {
    deadlineMin = ceilToFiveMinutes(new Date(Date.now() + 60_000));
    form.deadline_at.min = `${localDateKey(deadlineMin)}T${localTimeKey(deadlineMin)}`;
    return deadlineMin;
  };
  refreshDeadlineMinimum();
  const syncDeadlinePresentation = () => {
    const selected = parseLocalDateTime(form.deadline_at.value);
    form.querySelector("[data-deadline-date]").textContent = selected
      ? memberDateFormatter({ day: "numeric", month: "short", year: "numeric" }).format(selected)
      : "Выберите срок *";
    form.querySelector("[data-deadline-time]").textContent = selected
      ? memberDateFormatter({ hour: "2-digit", minute: "2-digit" }).format(selected)
      : "Дата и время";
  };
  syncDeadlinePresentation();
  form.performer_slots.value = values.performer_slots || 1;
  const submit = element("button", "Предварительный просмотр", "primary");
  submit.type = "submit";
  submit.setAttribute("aria-label", "Предварительный просмотр");
  const reserve = form.querySelector("[data-reserve]");
  const reserveFormula = form.querySelector("[data-reserve-formula]");
  const reserveSummary = form.querySelector("[data-reserve-summary]");
  const reserveMeter = form.querySelector("[data-reserve-meter]");
  const reserveMeterFill = form.querySelector("[data-reserve-meter-fill]");
  const cachedBalance = cachedJson("/api/v1/me")?.credit_balance;
  const availableCreditBalance = Number(state.credit_balance ?? cachedBalance);
  const hasCreditBalance = Number.isFinite(availableCreditBalance);
  const russianWord = (value, one, few, many) => {
    const absolute = Math.abs(value) % 100;
    const last = absolute % 10;
    if (absolute > 10 && absolute < 20) return many;
    if (last === 1) return one;
    if (last >= 2 && last <= 4) return few;
    return many;
  };
  const creditLabel = (value) => `${value} ${russianWord(value, "кредит", "кредита", "кредитов")}`;
  const availableCreditLabel = (value) => (
    `${value} ${russianWord(value, "кредита", "кредитов", "кредитов")}`
  );
  const performerLabel = (value) => `${value} ${russianWord(value, "исполнитель", "исполнителя", "исполнителей")}`;
  const updateReserve = () => {
    const slots = Number(form.performer_slots.value || 0);
    const reward = Number(form.credit_reward_per_performer.value || 0);
    if (!slots || !reward) {
      reserveFormula.textContent = "Будет зарезервировано";
      reserve.textContent = "—";
      reserveSummary.classList.remove("is-over-limit");
      reserveMeter.classList.toggle("hidden", !hasCreditBalance);
      reserveMeter.setAttribute("aria-valuemax", String(Math.max(availableCreditBalance, 1)));
      reserveMeter.setAttribute("aria-valuenow", "0");
      reserveMeter.setAttribute("aria-valuetext", "Резерв не рассчитан");
      reserveMeterFill.style.width = "0%";
      return;
    }
    const total = slots * reward;
    if (isCommunityTask()) {
      reserveFormula.textContent = form.task_kind.value === "group"
        ? `${performerLabel(slots)} × ${creditLabel(reward)}`
        : "Выплатит сообщество";
      reserve.textContent = creditLabel(total);
      reserveSummary.classList.remove("is-over-limit");
      reserveMeter.classList.add("hidden");
      reserveMeter.setAttribute("aria-valuenow", "0");
      reserveMeter.setAttribute("aria-valuetext", "Награда будет выпущена сообществом");
      reserveMeterFill.style.width = "0%";
      return;
    }
    reserveFormula.textContent = form.task_kind.value === "group"
      ? `${performerLabel(slots)} × ${creditLabel(reward)}`
      : "Будет зарезервировано";
    const exceedsBalance = hasCreditBalance && total > availableCreditBalance;
    reserve.textContent = hasCreditBalance
      ? `${total} из ${availableCreditLabel(availableCreditBalance)}`
      : creditLabel(total);
    reserveSummary.classList.toggle("is-over-limit", exceedsBalance);
    reserveMeter.classList.toggle("hidden", !hasCreditBalance);
    if (hasCreditBalance) {
      const meterMaximum = Math.max(availableCreditBalance, 1);
      const meterValue = Math.min(total, meterMaximum);
      reserveMeter.setAttribute("aria-valuemax", String(meterMaximum));
      reserveMeter.setAttribute("aria-valuenow", String(meterValue));
      reserveMeter.setAttribute(
        "aria-valuetext",
        exceedsBalance
          ? `Нужно ${creditLabel(total)}, доступно ${creditLabel(availableCreditBalance)}`
          : `Будет использовано ${creditLabel(total)} из ${availableCreditLabel(availableCreditBalance)}`,
      );
      reserveMeterFill.style.width = `${Math.min(100, (total / meterMaximum) * 100)}%`;
    }
  };
  form.performer_slots.addEventListener("input", updateReserve);
  form.performer_slots.addEventListener("input", () => {
    if (form.task_kind.value === "group" && Number(form.performer_slots.value) >= 2) {
      groupSlots = Number(form.performer_slots.value);
    }
  });
  const showDeadlineValidity = (force = false) => {
    const invalid = !form.deadline_at.validity.valid;
    const reveal = invalid && force;
    form.deadline_at.setAttribute("aria-invalid", String(reveal));
    deadlineTrigger.setAttribute("aria-invalid", String(reveal));
    deadlineError.textContent = reveal
      ? form.deadline_at.validity.rangeUnderflow ? "Выберите будущий срок." : "Выберите дату и время."
      : "";
    deadlineError.classList.toggle("hidden", !reveal);
  };
  const updateDeadlineValidity = () => {
    const expired = form.deadline_at.validity.rangeUnderflow;
    submit.disabled = expired;
    syncDeadlinePresentation();
    showDeadlineValidity(deadlineTrigger.getAttribute("aria-invalid") === "true" || expired);
  };
  form.deadline_at.addEventListener("input", updateDeadlineValidity);
  form.deadline_at.addEventListener("invalid", (event) => {
    event.preventDefault();
    showDeadlineValidity(true);
  });
  const saveStatus = element("p", "", "status hidden");
  saveStatus.setAttribute("aria-live", "polite");
  const localSaveStatus = element("small", "Автосохранение включено", "local-draft-status");
  localSaveStatus.setAttribute("aria-live", "polite");
  const submitBar = element("div", undefined, "creation-submit-bar");
  submitBar.append(localSaveStatus, submit, saveStatus);
  form.append(submitBar);
  for (const field of form.querySelectorAll("textarea.auto-grow")) {
    const counter = form.querySelector(`[data-counter-for="${field.name}"]`);
    const updateCounter = () => {
      const length = field.value.length;
      counter.textContent = `${length} / ${field.maxLength}`;
      counter.classList.toggle("hidden", length === 0);
      counter.classList.toggle("is-limit", length >= field.maxLength * 0.95);
    };
    field.addEventListener("input", () => {
      resizeAutoGrow(field);
      updateCounter();
      keepControlVisible(field);
    });
    field.addEventListener("focus", () => keepControlVisible(field));
    updateCounter();
    queueMicrotask(() => resizeAutoGrow(field));
  }
  const validationMessage = (control) => {
    if (control.validity.valueMissing) return "Заполните это поле.";
    if (control.name === "deadline_at" && control.validity.rangeUnderflow) {
      return "Выберите будущий срок.";
    }
    if (control.name === "performer_slots" && control.validity.rangeUnderflow) {
      return "Для группового задания нужно минимум 2 исполнителя.";
    }
    if (control.validity.badInput || control.validity.stepMismatch) return "Введите корректное число.";
    if (control.validity.rangeUnderflow) return `Минимальное значение: ${control.min}.`;
    if (control.validity.rangeOverflow) return `Максимальное значение: ${control.max}.`;
    if (control.validity.customError) return control.validationMessage;
    return "Проверьте введённое значение.";
  };
  const showFieldValidity = (control, force = false) => {
    if (control.disabled || control.closest(".hidden")) return;
    const invalid = !control.checkValidity();
    const reveal = invalid && force;
    control.setAttribute("aria-invalid", String(reveal));
    const error = control.parentElement.querySelector(":scope > .field-error");
    if (!error) return;
    error.textContent = reveal ? validationMessage(control) : "";
    error.classList.toggle("hidden", !reveal);
  };
  const attachFieldValidation = (control) => {
    const label = control.closest("label");
    if (!label || label.querySelector(":scope > .field-error")) return;
    const error = element("small", "", "field-error hidden");
    error.id = `field-error-${control.name}`;
    error.setAttribute("aria-live", "polite");
    label.append(error);
    const describedBy = [control.getAttribute("aria-describedby"), error.id].filter(Boolean).join(" ");
    control.setAttribute("aria-describedby", describedBy);
    control.addEventListener("blur", () => showFieldValidity(control, true));
    control.addEventListener("input", () => {
      const wasRevealed = control.getAttribute("aria-invalid") === "true";
      showFieldValidity(control, wasRevealed);
    });
    control.addEventListener("change", () => showFieldValidity(control, true));
    control.addEventListener("invalid", (event) => {
      event.preventDefault();
      showFieldValidity(control, true);
    });
    control.setAttribute("aria-invalid", "false");
  };
  for (const control of form.querySelectorAll("input, select, textarea")) {
    if (!control.classList.contains("visually-hidden")) attachFieldValidation(control);
  }
  const rewardHint = form.querySelector("[data-reward-hint]");
  const rewardOptions = form.querySelector("[data-reward-options]");
  const rewardStepper = form.querySelector("[data-reward-stepper]");
  const rewardOutput = form.querySelector("[data-reward-value]");
  const sizeTrigger = form.querySelector(".size-picker-trigger");
  const normalizedRewards = (spec) => (spec?.reward_options || [])
    .map(Number)
    .filter((value) => Number.isFinite(value))
    .filter((value) => !isCommunityTask() || value <= communityRewardMax);
  const rewardRangeLabel = (spec) => {
    const options = normalizedRewards(spec);
    if (!options.length) return `от ${Number(spec?.minimum_reward || 1)} кредитов`;
    if (options.length === 1) return creditLabel(options[0]);
    const contiguous = options.every((value, index) => index === 0 || value === options[index - 1] + 1);
    if (contiguous) {
      const last = options.at(-1);
      return `${options[0]}–${last} ${russianWord(last, "кредит", "кредита", "кредитов")}`;
    }
    return options.map(creditLabel).join(", ");
  };
  const syncSizePresentation = () => {
    const spec = state.time_sizes.find((item) => item.value === form.time_size.value);
    form.querySelector("[data-size-name]").textContent = spec?.value.toUpperCase() || "—";
    form.querySelector("[data-size-duration]").textContent = spec?.label || "Выберите размер";
  };
  const setRewardValue = (value) => {
    form.credit_reward_per_performer.value = String(value);
    rewardOutput.textContent = creditLabel(value);
    for (const option of rewardOptions.querySelectorAll("button")) {
      const selected = Number(option.dataset.reward) === value;
      option.classList.toggle("is-selected", selected);
      option.setAttribute("aria-checked", String(selected));
    }
    const minimum = Number(form.credit_reward_per_performer.min || 1);
    form.querySelector("[data-reward-decrease]").disabled = value <= minimum;
    updateReserve();
  };
  const syncRewardRules = () => {
    const spec = state.time_sizes.find((item) => item.value === form.time_size.value);
    const options = normalizedRewards(spec);
    const minimum = Number(spec?.minimum_reward || options[0] || 1);
    const current = Number(form.credit_reward_per_performer.value);
    form.credit_reward_per_performer.min = String(minimum);
    if (isCommunityTask()) form.credit_reward_per_performer.max = String(communityRewardMax);
    else form.credit_reward_per_performer.removeAttribute("max");
    form.credit_reward_per_performer.setCustomValidity("");
    rewardHint.textContent = `Для размера ${spec?.value.toUpperCase() || "—"} доступно ${rewardRangeLabel(spec)}`;
    rewardOptions.replaceChildren();
    rewardOptions.classList.toggle("hidden", !options.length);
    rewardStepper.classList.toggle("hidden", Boolean(options.length));
    if (options.length) {
      const selected = options.includes(current) ? current : options[0];
      for (const value of options) {
        const option = element("button", String(value), "reward-option");
        option.type = "button";
        option.dataset.reward = String(value);
        option.setAttribute("role", "radio");
        option.setAttribute("aria-label", creditLabel(value));
        option.addEventListener("click", () => {
          setRewardValue(value);
          persistDraft();
        });
        rewardOptions.append(option);
      }
      setRewardValue(selected);
    } else {
      const fallback = Number.isFinite(current) && current >= minimum ? current : minimum;
      setRewardValue(isCommunityTask() ? Math.min(communityRewardMax, fallback) : fallback);
    }
  };
  const changeSteppedReward = (delta) => {
    const minimum = Number(form.credit_reward_per_performer.min || 1);
    const current = Number(form.credit_reward_per_performer.value || minimum);
    const next = Math.max(minimum, current + delta);
    setRewardValue(isCommunityTask() ? Math.min(communityRewardMax, next) : next);
    persistDraft();
  };
  form.querySelector("[data-reward-decrease]").addEventListener("click", () => changeSteppedReward(-1));
  form.querySelector("[data-reward-increase]").addEventListener("click", () => changeSteppedReward(1));
  const showCreationChoiceSheet = ({ trigger, titleText, options: choices, currentValue, onSelect }) => {
    shell.querySelector(".catalog-sort-backdrop, .catalog-filter-backdrop, .task-size-backdrop")?.remove();
    const backdrop = element("section", undefined, "task-size-backdrop");
    const dialog = element("div", undefined, "task-size-sheet creation-choice-sheet");
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.setAttribute("aria-labelledby", "creation-choice-title");
    const header = element("div", undefined, "catalog-sort-heading");
    const sheetTitle = element("h2", titleText);
    sheetTitle.id = "creation-choice-title";
    const close = element("button", "×", "catalog-sort-close");
    close.type = "button";
    close.setAttribute("aria-label", `Закрыть выбор: ${titleText.toLocaleLowerCase("ru")}`);
    header.append(sheetTitle, close);
    const options = element("div", undefined, "creation-choice-options");
    let selectedOption = null;
    const dismiss = (restoreFocus = true) => {
      backdrop.remove();
      if (restoreFocus) trigger.focus({ preventScroll: true });
    };
    for (const choice of choices) {
      const option = element("button", undefined, "creation-choice-option");
      option.type = "button";
      option.setAttribute("aria-label", `${choice.label}, ${choice.description}`);
      const icon = element("span", choice.icon || "", "creation-choice-option-icon");
      icon.setAttribute("aria-hidden", "true");
      const copy = element("span", undefined, "creation-choice-option-copy");
      copy.append(element("strong", choice.label), element("small", choice.description));
      option.append(
        icon,
        copy,
        element("span", choice.value === currentValue ? "✓" : "", "creation-choice-option-check"),
      );
      if (choice.value === currentValue) {
        option.classList.add("is-selected");
        selectedOption = option;
      }
      option.addEventListener("click", () => {
        onSelect(choice.value);
        dismiss();
      });
      options.append(option);
    }
    close.addEventListener("click", () => dismiss());
    backdrop.addEventListener("click", (event) => {
      if (event.target === backdrop) dismiss();
    });
    dialog.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        dismiss();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = [close, ...options.querySelectorAll("button")];
      const first = focusable[0];
      const last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });
    dialog.append(header, options);
    backdrop.append(dialog);
    shell.append(backdrop);
    queueMicrotask(() => (selectedOption || close).focus({ preventScroll: true }));
  };
  const kindTrigger = form.querySelector("[data-kind-trigger]");
  const formatTrigger = form.querySelector("[data-format-trigger]");
  const categoryTrigger = form.querySelector("[data-category-trigger]");
  kindTrigger.addEventListener("click", () => showCreationChoiceSheet({
    trigger: kindTrigger,
    titleText: "Тип задания",
    options: taskKindOptions,
    currentValue: form.task_kind.value,
    onSelect: (value) => {
      if (form.task_kind.value === "group" && Number(form.performer_slots.value) >= 2) {
        groupSlots = Number(form.performer_slots.value);
      }
      form.task_kind.value = value;
      syncTaskKind();
      persistDraft();
    },
  }));
  formatTrigger.addEventListener("click", () => showCreationChoiceSheet({
    trigger: formatTrigger,
    titleText: "Формат задания",
    options: formatOptions,
    currentValue: form.format.value,
    onSelect: (value) => {
      form.format.value = value;
      syncFormatPresentation();
      syncFormat();
      persistDraft();
    },
  }));
  categoryTrigger.addEventListener("click", () => showCreationChoiceSheet({
    trigger: categoryTrigger,
    titleText: "Категория",
    options: state.categories.map((item) => ({
      value: item.id,
      label: item.name,
      description: categoryDescription(item),
      icon: item.icon,
    })),
    currentValue: form.category_id.value,
    onSelect: (value) => {
      form.category_id.value = value;
      syncCategoryPresentation();
      if (isCommunityTask() && form.time_size.value === "xl") {
        form.time_size.value = "l";
        syncSizePresentation();
      }
      syncRewardRules();
      updateReserve();
      persistDraft();
    },
  }));
  const showSizeSheet = () => {
    shell.querySelector(".catalog-sort-backdrop, .catalog-filter-backdrop, .task-size-backdrop")?.remove();
    const backdrop = element("section", undefined, "task-size-backdrop");
    const dialog = element("div", undefined, "task-size-sheet");
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.setAttribute("aria-labelledby", "task-size-title");
    const header = element("div", undefined, "catalog-sort-heading");
    const title = element("h2", "Размер задания");
    title.id = "task-size-title";
    const close = element("button", "×", "catalog-sort-close");
    close.type = "button";
    close.setAttribute("aria-label", "Закрыть выбор размера");
    header.append(title, close);
    const options = element("div", undefined, "task-size-options");
    let selectedOption = null;
    const dismiss = (restoreFocus = true) => {
      backdrop.remove();
      if (restoreFocus) sizeTrigger.focus({ preventScroll: true });
    };
    const availableSizes = isCommunityTask()
      ? state.time_sizes.filter((spec) => Number(spec.minimum_reward) <= communityRewardMax)
      : state.time_sizes;
    for (const spec of availableSizes) {
      const option = element("button", undefined, "task-size-option");
      option.type = "button";
      option.setAttribute("aria-label", `${spec.value.toUpperCase()}, ${spec.label}, награда ${rewardRangeLabel(spec)}`);
      option.append(
        element("strong", spec.value.toUpperCase()),
        element("span", spec.label),
        element("small", `Награда ${rewardRangeLabel(spec)}`),
        element("span", spec.value === form.time_size.value ? "✓" : "", "task-size-check"),
      );
      if (spec.value === form.time_size.value) {
        option.classList.add("is-selected");
        selectedOption = option;
      }
      option.addEventListener("click", () => {
        form.time_size.value = spec.value;
        syncSizePresentation();
        syncRewardRules();
        persistDraft();
        dismiss();
      });
      options.append(option);
    }
    close.addEventListener("click", () => dismiss());
    backdrop.addEventListener("click", (event) => {
      if (event.target === backdrop) dismiss();
    });
    dialog.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        dismiss();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = [close, ...options.querySelectorAll("button")];
      const first = focusable[0];
      const last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });
    dialog.append(header, options);
    backdrop.append(dialog);
    shell.append(backdrop);
    queueMicrotask(() => (selectedOption || close).focus({ preventScroll: true }));
  };
  sizeTrigger.addEventListener("click", showSizeSheet);
  form.time_size.addEventListener("change", () => {
    syncSizePresentation();
    syncRewardRules();
  });
  const showDeadlineSheet = () => {
    shell.querySelector(".catalog-sort-backdrop, .catalog-filter-backdrop, .task-size-backdrop")?.remove();
    const backdrop = element("section", undefined, "task-size-backdrop");
    const dialog = element("div", undefined, "task-size-sheet deadline-choice-sheet");
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.setAttribute("aria-labelledby", "deadline-choice-title");
    const header = element("div", undefined, "catalog-sort-heading");
    const title = element("h2", "Срок");
    title.id = "deadline-choice-title";
    const close = element("button", "×", "catalog-sort-close");
    close.type = "button";
    close.setAttribute("aria-label", "Закрыть выбор срока");
    header.append(title, close);

    const minimum = refreshDeadlineMinimum();
    const minimumDateKey = localDateKey(minimum);
    const minimumTime = localTimeKey(minimum);
    const selected = parseLocalDateTime(form.deadline_at.value);
    const normalizedSelection = selected
      ? selected >= minimum ? selected : minimum
      : null;
    let selectedDate = normalizedSelection ? localDateKey(normalizedSelection) : "";
    let selectedTime = normalizedSelection ? localTimeKey(normalizedSelection) : minimumTime;
    let timeNotice = selected && normalizedSelection.getTime() !== selected.getTime()
      ? `Установлено ближайшее допустимое время — ${selectedTime}.`
      : "";
    const monthSeed = memberDateParts(normalizedSelection || minimum);
    let monthCursor = new Date(Date.UTC(Number(monthSeed.year), Number(monthSeed.month) - 1, 1));
    const calendarDateKey = (date) => [
      date.getUTCFullYear(),
      String(date.getUTCMonth() + 1).padStart(2, "0"),
      String(date.getUTCDate()).padStart(2, "0"),
    ].join("-");

    const monthNavigation = element("div", undefined, "deadline-month-navigation");
    const previousMonth = element("button", "‹", "deadline-month-button");
    previousMonth.type = "button";
    previousMonth.setAttribute("aria-label", "Предыдущий месяц");
    const monthLabel = element("strong", "", "deadline-month-label");
    monthLabel.setAttribute("aria-live", "polite");
    const nextMonth = element("button", "›", "deadline-month-button");
    nextMonth.type = "button";
    nextMonth.setAttribute("aria-label", "Следующий месяц");
    monthNavigation.append(previousMonth, monthLabel, nextMonth);

    const calendar = element("div", undefined, "deadline-calendar");
    calendar.setAttribute("role", "grid");
    calendar.setAttribute("aria-label", "Календарь срока");
    const timeField = element("label", "Время", "deadline-time-field");
    const timeInput = element("input");
    timeInput.type = "time";
    timeInput.step = "60";
    timeInput.value = selectedTime;
    timeInput.setAttribute("aria-label", "Время срока");
    timeField.append(timeInput);
    const sheetError = element("small", "", "deadline-sheet-error hidden");
    const done = element("button", "Готово", "primary deadline-choice-done");
    done.type = "button";

    const selectedDateTime = () => (
      selectedDate && selectedTime ? parseLocalDateTime(`${selectedDate}T${selectedTime}`) : null
    );
    const syncDoneState = () => {
      selectedTime = timeInput.value;
      const candidate = selectedDateTime();
      const valid = Boolean(candidate && candidate >= minimum);
      done.disabled = !valid;
      if (selectedDate === minimumDateKey) {
        timeInput.min = minimumTime;
      } else {
        timeInput.removeAttribute("min");
      }
      const invalidMessage = selectedDate === minimumDateKey
        ? `Для сегодняшней даты выберите ${minimumTime} или позже.`
        : "Выберите будущие дату и время.";
      sheetError.textContent = timeNotice || invalidMessage;
      sheetError.classList.toggle("is-note", Boolean(timeNotice));
      sheetError.classList.toggle("hidden", !timeNotice && (!selectedDate || !selectedTime || valid));
    };
    const renderCalendar = () => {
      monthLabel.textContent = memberDateFormatter({
        month: "long",
        year: "numeric",
        timeZone: "UTC",
      }).format(monthCursor);
      calendar.replaceChildren();
      for (const weekday of ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]) {
        calendar.append(element("span", weekday, "deadline-weekday"));
      }
      const year = monthCursor.getUTCFullYear();
      const month = monthCursor.getUTCMonth();
      const leading = (new Date(Date.UTC(year, month, 1)).getUTCDay() + 6) % 7;
      const days = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
      for (let index = 0; index < leading; index += 1) {
        calendar.append(element("span", "", "deadline-day-placeholder"));
      }
      const todayKey = localDateKey(new Date());
      for (let day = 1; day <= days; day += 1) {
        const date = new Date(Date.UTC(year, month, day));
        const dateKey = calendarDateKey(date);
        const option = element("button", String(day), "deadline-day");
        option.type = "button";
        option.dataset.date = dateKey;
        option.setAttribute("role", "gridcell");
        option.setAttribute("aria-label", memberDateFormatter({
          weekday: "long",
          day: "numeric",
          month: "long",
          year: "numeric",
          timeZone: "UTC",
        }).format(date));
        option.disabled = dateKey < minimumDateKey;
        option.classList.toggle("is-today", dateKey === todayKey);
        option.classList.toggle("is-selected", dateKey === selectedDate);
        option.setAttribute("aria-selected", String(dateKey === selectedDate));
        option.addEventListener("click", () => {
          selectedDate = dateKey;
          if (selectedDate === minimumDateKey && selectedTime < form.deadline_at.min.slice(11, 16)) {
            selectedTime = minimumTime;
            timeInput.value = selectedTime;
            timeNotice = `Установлено ближайшее допустимое время — ${selectedTime}.`;
          }
          renderCalendar();
          syncDoneState();
          timeInput.focus({ preventScroll: true });
        });
        calendar.append(option);
      }
      const minimumParts = memberDateParts(minimum);
      const minimumMonth = Number(minimumParts.year) * 12 + Number(minimumParts.month) - 1;
      const currentMonth = monthCursor.getUTCFullYear() * 12 + monthCursor.getUTCMonth();
      previousMonth.disabled = currentMonth <= minimumMonth;
    };
    const dismiss = () => {
      backdrop.remove();
      deadlineTrigger.focus({ preventScroll: true });
    };
    previousMonth.addEventListener("click", () => {
      monthCursor = new Date(Date.UTC(monthCursor.getUTCFullYear(), monthCursor.getUTCMonth() - 1, 1));
      renderCalendar();
    });
    nextMonth.addEventListener("click", () => {
      monthCursor = new Date(Date.UTC(monthCursor.getUTCFullYear(), monthCursor.getUTCMonth() + 1, 1));
      renderCalendar();
    });
    timeInput.addEventListener("input", () => {
      timeNotice = "";
      syncDoneState();
    });
    timeInput.addEventListener("change", () => {
      if (selectedDate === minimumDateKey && timeInput.value && timeInput.value < minimumTime) {
        timeInput.value = minimumTime;
        selectedTime = minimumTime;
        timeNotice = `Установлено ближайшее допустимое время — ${minimumTime}.`;
      }
      syncDoneState();
    });
    done.addEventListener("click", () => {
      if (done.disabled) return;
      form.deadline_at.value = `${selectedDate}T${selectedTime}`;
      form.deadline_at.dispatchEvent(new Event("input", { bubbles: true }));
      form.deadline_at.dispatchEvent(new Event("change", { bubbles: true }));
      showDeadlineValidity(false);
      persistDraft();
      dismiss();
    });
    close.addEventListener("click", dismiss);
    backdrop.addEventListener("click", (event) => {
      if (event.target === backdrop) dismiss();
    });
    dialog.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        dismiss();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = [...dialog.querySelectorAll("button:not(:disabled), input:not(:disabled)")];
      const first = focusable[0];
      const last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });
    const deadlineContent = element("div", undefined, "deadline-choice-content");
    deadlineContent.append(monthNavigation, calendar, timeField, sheetError);
    dialog.append(header, deadlineContent, done);
    backdrop.append(dialog);
    shell.append(backdrop);
    renderCalendar();
    syncDoneState();
    queueMicrotask(() => {
      const selectedDay = calendar.querySelector(".deadline-day.is-selected");
      (selectedDay || calendar.querySelector(".deadline-day:not(:disabled)") || close)
        .focus({ preventScroll: true });
    });
  };
  deadlineTrigger.addEventListener("click", showDeadlineSheet);

  const showContentEditorSheet = (name) => {
    const spec = contentEditorSpecs[name];
    const source = form[name];
    const trigger = form.querySelector(`[data-content-trigger="${name}"]`);
    shell.querySelector(".catalog-sort-backdrop, .catalog-filter-backdrop, .task-size-backdrop")?.remove();
    const backdrop = element("section", undefined, "task-size-backdrop");
    const dialog = element("div", undefined, "task-size-sheet content-editor-sheet");
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.setAttribute("aria-labelledby", "content-editor-title");
    const header = element("div", undefined, "catalog-sort-heading");
    const title = element("h2", spec.title);
    title.id = "content-editor-title";
    const close = element("button", "×", "catalog-sort-close");
    close.type = "button";
    close.setAttribute("aria-label", `Закрыть редактор: ${spec.title.toLocaleLowerCase("ru")}`);
    header.append(title, close);
    const hint = element("p", spec.hint, "content-editor-hint");
    const editor = element("textarea", undefined, "content-editor-input");
    editor.value = source.value;
    editor.rows = spec.rows;
    editor.maxLength = source.maxLength;
    editor.placeholder = spec.placeholder;
    editor.setAttribute("aria-label", `${spec.title}: текст`);
    const counter = element("small", "", "content-editor-counter");
    counter.setAttribute("aria-live", "polite");
    const done = element("button", "Готово", "primary content-editor-done");
    done.type = "button";
    const resize = () => {
      editor.style.height = "auto";
      const maximum = name === "title" ? 112 : 260;
      editor.style.height = `${Math.min(editor.scrollHeight, maximum)}px`;
      editor.style.overflowY = editor.scrollHeight > maximum ? "auto" : "hidden";
    };
    const sync = () => {
      counter.textContent = `${editor.value.length} / ${editor.maxLength}`;
      counter.classList.toggle("is-limit", editor.value.length >= editor.maxLength * 0.95);
      done.disabled = spec.required !== false && !editor.value.trim();
      resize();
    };
    const dismiss = () => {
      backdrop.remove();
      trigger.focus({ preventScroll: true });
    };
    editor.addEventListener("input", sync);
    done.addEventListener("click", () => {
      if (done.disabled) return;
      source.value = editor.value.trim();
      source.dispatchEvent(new Event("input", { bubbles: true }));
      source.dispatchEvent(new Event("change", { bubbles: true }));
      source.setAttribute("aria-invalid", "false");
      trigger.setAttribute("aria-invalid", "false");
      form.querySelector(`[data-content-error="${name}"]`).classList.add("hidden");
      persistDraft();
      dismiss();
    });
    close.addEventListener("click", dismiss);
    backdrop.addEventListener("click", (event) => {
      if (event.target === backdrop) dismiss();
    });
    dialog.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        dismiss();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = [close, editor, done].filter((item) => !item.disabled);
      const first = focusable[0];
      const last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });
    dialog.append(header, hint, editor, counter, done);
    backdrop.append(dialog);
    shell.append(backdrop);
    sync();
    queueMicrotask(() => {
      editor.focus({ preventScroll: true });
      editor.setSelectionRange(editor.value.length, editor.value.length);
    });
  };
  for (const name of Object.keys(contentEditorSpecs)) {
    form.querySelector(`[data-content-trigger="${name}"]`).addEventListener(
      "click",
      () => showContentEditorSheet(name),
    );
  }

  const showContentValidity = (name, reveal = true) => {
    const source = form[name];
    const trigger = form.querySelector(`[data-content-trigger="${name}"]`);
    const error = form.querySelector(`[data-content-error="${name}"]`);
    const invalid = !source.checkValidity();
    source.setAttribute("aria-invalid", String(invalid && reveal));
    trigger.setAttribute("aria-invalid", String(invalid && reveal));
    error.textContent = invalid && reveal ? "Заполните это поле." : "";
    error.classList.toggle("hidden", !invalid || !reveal);
  };
  const focusInvalidContent = () => {
    const name = Object.keys(contentEditorSpecs).find((key) => !form[key].checkValidity());
    if (!name) return false;
    showContentValidity(name, true);
    const trigger = form.querySelector(`[data-content-trigger="${name}"]`);
    trigger.focus({ preventScroll: true });
    trigger.scrollIntoView({ block: "center", behavior: "smooth" });
    return true;
  };
  for (const name of Object.keys(contentEditorSpecs)) {
    form[name].addEventListener("invalid", (event) => {
      event.preventDefault();
      showContentValidity(name, true);
    });
    form[name].addEventListener("input", () => {
      if (form[name].getAttribute("aria-invalid") === "true") showContentValidity(name, true);
    });
  }

  let focusInvalidDeadline = () => {};
  let focusInvalidCity = () => {};
  focusInvalidDeadline = () => {
    showDeadlineValidity(true);
    deadlineTrigger.focus({ preventScroll: true });
    deadlineTrigger.scrollIntoView({ block: "center", behavior: "smooth" });
  };
  submit.addEventListener("click", () => {
    if (form.checkValidity()) return;
    queueMicrotask(() => {
      const firstInvalid = [...form.elements].find((control) => (
        typeof control.checkValidity === "function"
        && !control.disabled
        && !control.classList.contains("visually-hidden")
        && !control.checkValidity()
      ));
      if (firstInvalid) {
        firstInvalid.focus({ preventScroll: true });
        firstInvalid.scrollIntoView({ block: "center", behavior: "smooth" });
      } else {
        const city = form.querySelector('[name="city"]');
        if (city && !city.checkValidity()) focusInvalidCity();
        else if (focusInvalidContent()) return;
        else if (!form.deadline_at.checkValidity()) focusInvalidDeadline();
      }
    });
  });
  let selectedCity = values.format === "offline" ? values.city || "" : "";
  let selectedCityLabel = localValues?.city_input || selectedCity;
  let selectedCityTimezone = localValues?.city_timezone || "";
  let cityField = null;
  let cityTimer = null;
  const showCitySheet = (trigger, cityInput) => {
    shell.querySelector(".catalog-sort-backdrop, .catalog-filter-backdrop, .task-size-backdrop")?.remove();
    const backdrop = element("section", undefined, "task-size-backdrop");
    const dialog = element("div", undefined, "task-size-sheet city-choice-sheet");
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.setAttribute("aria-labelledby", "city-choice-title");
    const header = element("div", undefined, "catalog-sort-heading");
    const sheetTitle = element("h2", "Город");
    sheetTitle.id = "city-choice-title";
    const close = element("button", "×", "catalog-sort-close");
    close.type = "button";
    close.setAttribute("aria-label", "Закрыть выбор города");
    header.append(sheetTitle, close);
    const searchLabel = element("label", "Поиск города", "city-search-field");
    const search = element("input");
    search.type = "search";
    search.autocomplete = "off";
    search.placeholder = "Начните вводить название";
    search.setAttribute("aria-label", "Поиск города");
    search.value = selectedCityLabel;
    const results = element("div", undefined, "city-sheet-results");
    results.setAttribute("role", "listbox");
    searchLabel.append(search);
    const dismiss = () => {
      clearTimeout(cityTimer);
      backdrop.remove();
      trigger.focus({ preventScroll: true });
    };
    const choose = (item) => {
      selectedCity = item.value;
      selectedCityLabel = item.label;
      selectedCityTimezone = item.timezone || selectedCityTimezone || currentMemberTimezone;
      cityInput.value = item.value;
      cityInput.setCustomValidity("");
      trigger.querySelector("[data-city-name]").textContent = item.label;
      trigger.querySelector("[data-city-summary]").textContent = timezoneOffsetLabel(
        selectedCityTimezone,
      );
      trigger.setAttribute("aria-invalid", "false");
      cityField.querySelector("[data-city-error]").classList.add("hidden");
      persistDraft();
      dismiss();
    };
    const loadResults = async (query) => {
      if (!query) {
        results.replaceChildren(element("p", "Введите название города.", "city-sheet-empty"));
        return;
      }
      results.replaceChildren(element("p", "Ищем города…", "city-sheet-empty"));
      const response = await getJson(`/api/v1/task-cities?q=${encodeURIComponent(query)}&limit=8`);
      if (!dialog.isConnected || search.value.trim() !== query) return;
      if (!response.items.length) {
        results.replaceChildren(element("p", "Города не найдены.", "city-sheet-empty"));
        return;
      }
      results.replaceChildren();
      for (const item of response.items) {
        const option = element("button", undefined, "city-sheet-option");
        option.type = "button";
        option.setAttribute("role", "option");
        option.setAttribute("aria-label", item.label);
        option.setAttribute("aria-selected", String(item.value === selectedCity));
        const optionCopy = element("span", undefined, "city-sheet-copy");
        optionCopy.append(
          element("strong", item.label),
          element("small", timezoneOffsetLabel(item.timezone || currentMemberTimezone)),
        );
        option.append(
          element("span", "⌖", "city-sheet-icon"),
          optionCopy,
          element("span", item.value === selectedCity ? "✓" : "", "city-sheet-check"),
        );
        option.addEventListener("click", () => choose(item));
        results.append(option);
      }
    };
    search.addEventListener("input", () => {
      clearTimeout(cityTimer);
      const query = search.value.trim();
      cityTimer = setTimeout(() => void loadResults(query), 200);
    });
    search.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        results.querySelector("button")?.focus();
      }
    });
    close.addEventListener("click", dismiss);
    backdrop.addEventListener("click", (event) => {
      if (event.target === backdrop) dismiss();
    });
    dialog.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        dismiss();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = [close, search, ...results.querySelectorAll("button")];
      const first = focusable[0];
      const last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });
    dialog.append(header, searchLabel, results);
    backdrop.append(dialog);
    shell.append(backdrop);
    queueMicrotask(() => {
      search.focus({ preventScroll: true });
      search.select();
      void loadResults(search.value.trim());
    });
  };
  const syncFormat = () => {
    if (form.format.value !== "offline") {
      selectedCity = "";
      selectedCityLabel = "";
      selectedCityTimezone = "";
      cityField?.remove();
      cityField = null;
      focusInvalidCity = () => {};
      return;
    }
    if (cityField) return;
    cityField = element("div", undefined, "section city-choice-field");
    const label = element("span", "Город *", "field-label");
    const input = element("input");
    input.className = "visually-hidden";
    input.name = "city";
    input.required = true;
    input.value = selectedCity;
    input.setAttribute("aria-label", "Город *");
    input.setCustomValidity(selectedCity ? "" : "Выберите город из списка.");
    const trigger = element("button", undefined, "category-choice-trigger city-choice-trigger");
    trigger.type = "button";
    trigger.setAttribute("aria-label", "Выбрать город");
    trigger.setAttribute("aria-haspopup", "dialog");
    const icon = element("span", "⌖", "category-choice-icon");
    icon.setAttribute("aria-hidden", "true");
    const copy = element("span", undefined, "creation-choice-copy");
    copy.append(
      element("strong", selectedCityLabel || "Выберите город"),
      element(
        "small",
        selectedCity
          ? selectedCityTimezone
            ? timezoneOffsetLabel(selectedCityTimezone)
            : "Часовой пояс будет определён"
          : "Поиск по названию",
      ),
    );
    copy.querySelector("strong").dataset.cityName = "";
    copy.querySelector("small").dataset.citySummary = "";
    trigger.append(icon, copy, element("span", "›", "creation-choice-chevron"));
    const error = element("small", "Выберите город.", "field-error hidden");
    error.dataset.cityError = "";
    const revealValidity = (reveal = true) => {
      const invalid = !selectedCity;
      trigger.setAttribute("aria-invalid", String(invalid && reveal));
      error.classList.toggle("hidden", !invalid || !reveal);
    };
    input.addEventListener("invalid", (event) => {
      event.preventDefault();
      revealValidity(true);
    });
    trigger.addEventListener("click", () => showCitySheet(trigger, input));
    focusInvalidCity = () => {
      revealValidity(true);
      trigger.focus({ preventScroll: true });
      trigger.scrollIntoView({ block: "center", behavior: "smooth" });
    };
    cityField.append(label, input, trigger, error);
    form.querySelector("[data-city-anchor]").after(cityField);
  };
  form.format.addEventListener("change", () => {
    syncFormatPresentation();
    syncFormat();
  });
  persistDraft = () => {
    const snapshot = {
      task_kind: form.task_kind.value,
      performer_slots: form.task_kind.value === "solo" ? "1" : form.performer_slots.value,
      format: form.format.value,
      category_id: form.category_id.value,
      title: form.title.value,
      description: form.description.value,
      completion_criteria: form.completion_criteria.value,
      time_size: form.time_size.value,
      credit_reward_per_performer: form.credit_reward_per_performer.value,
      deadline_at: form.deadline_at.value,
      city: selectedCity,
      city_input: selectedCityLabel,
      city_timezone: selectedCityTimezone,
      material_text: form.material_text.value,
    };
    const key = localDraftKey();
    localDraftKeys.add(key);
    try {
      localStorage.setItem(key, JSON.stringify({ revision: draft.revision, values: snapshot }));
      localSaveStatus.textContent = "Сохранено на устройстве";
      localSaveStatus.classList.remove("is-error");
    } catch {
      localSaveStatus.textContent = "Автосохранение недоступно";
      localSaveStatus.classList.add("is-error");
    }
  };
  const clearLocalDraft = () => {
    for (const key of localDraftKeys) {
      try {
        localStorage.removeItem(key);
      } catch {
        // The server copy is already authoritative; storage cleanup is best effort.
      }
    }
  };
  form.addEventListener("input", persistDraft);
  form.addEventListener("change", persistDraft);
  syncFormat();
  syncTaskKind();
  syncFormatPresentation();
  syncCategoryPresentation();
  syncSizePresentation();
  syncRewardRules();
  updateDeadlineValidity();
  showDeadlineValidity(form.deadline_at.validity.rangeUnderflow);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    saveStatus.classList.add("hidden");
    const value = Object.fromEntries(new FormData(form));
    value.performer_slots = form.task_kind.value === "solo" ? "1" : form.performer_slots.value;
    if (form.format.value === "offline") value.city = selectedCity;
    else delete value.city;
    const materials = value.material_text ? { text: value.material_text } : {};
    delete value.material_text;
    try {
      let target = draft;
      if (!target.id) {
        await taskCreationCommand({ action: "start" });
        const started = await getJson("/api/v1/task-creation");
        if (!started.draft) throw new Error("task_draft_unavailable");
        draft = started.draft;
        target = draft;
        persistDraft();
      }
      const deadline = memberWallTimeToDate(value.deadline_at);
      if (!deadline) throw new Error("invalid_deadline");
      await taskCreationCommand({ action: "save", draft_id: target.id, expected_revision: target.revision, form: { ...value, credit_reward_per_performer: Number(value.credit_reward_per_performer), performer_slots: Number(value.performer_slots), deadline_at: deadline.toISOString(), materials } });
      clearLocalDraft();
      history.pushState(
        { screen: "task-preview", draftId: target.id },
        "",
        presentationLocationFor("T06", target.id),
      );
      await openTaskCreation(false, "stale");
    } catch (error) {
      const city = form.querySelector('[name="city"]');
      if (error.message === "invalid_task_city" && city) {
        city.setCustomValidity("Выберите город из списка.");
        focusInvalidCity();
      }
      saveStatus.textContent = error.message === "invalid_task_city"
        ? "Выберите город из списка."
        : error.message === "invalid_deadline"
          ? "Выберите корректные дату и время для вашего часового пояса."
          : "Не удалось сохранить задание. Проверьте данные и попробуйте снова.";
      saveStatus.classList.remove("hidden");
      submit.disabled = false;
    }
  });
  replaceContent(connectedBoundary("T05", "content", form));
}

function showTaskRecovery(state) {
  const draft = state.draft;
  const card = element("article", undefined, "card detail");
  card.append(element("h3", draft.values.title || "Сохранённый черновик"));
  if (state.needs_edit) {
    card.append(element("p", "Предпросмотр устарел. Исправьте срок или другие поля.", "status"));
  } else {
    card.append(element("p", "Можно продолжить с сохранёнными данными.", "muted"));
  }
  const resume = element("button", state.needs_edit ? "Редактировать черновик" : "Продолжить", "primary");
  resume.type = "button";
  resume.addEventListener("click", async () => {
    resume.disabled = true;
    restart.disabled = true;
    recoveryStatus.classList.add("hidden");
    try {
      const current = await getJson("/api/v1/task-creation");
      pendingTaskCreation = null;
      const preview = Boolean(current.preview && !current.needs_edit);
      history.pushState(
        { screen: preview ? "task-preview" : "task-creation", draftId: current.draft?.id || null },
        "",
        presentationLocationFor(preview ? "T06" : "T05", current.draft?.id),
      );
      showTaskCreation(current, !preview);
    } catch {
      resume.disabled = false;
      restart.disabled = false;
      recoveryStatus.textContent = "Не удалось обновить черновик. Повторите запрос.";
      recoveryStatus.classList.remove("hidden");
    }
  });
  const restart = element("button", "Создать новое", "secondary");
  restart.type = "button";
  const recoveryStatus = element("p", "", "status hidden");
  recoveryStatus.setAttribute("aria-live", "polite");
  restart.addEventListener("click", async () => {
    restart.disabled = true;
    resume.disabled = true;
    let created = false;
    try {
      await taskCreationCommand({ action: "start_new", draft_id: draft.id, expected_revision: draft.revision });
      created = true;
      const fresh = await getJson("/api/v1/task-creation");
      history.pushState(
        { screen: "task-creation", draftId: fresh.draft?.id || null },
        "",
        presentationLocationFor("T05", fresh.draft?.id),
      );
      showTaskCreation(fresh, true);
    } catch {
      restart.disabled = created;
      resume.disabled = false;
      recoveryStatus.textContent = created
        ? "Новый черновик создан. Обновите данные через редактирование."
        : "Не удалось создать новый черновик. Повторите запрос.";
      recoveryStatus.classList.remove("hidden");
    }
  });
  card.append(resume, restart, recoveryStatus);
  replaceContent(connectedBoundary("T04B", state.needs_edit ? "error" : "content", card));
}

function beginTaskCreationFlow(push = true) {
  screenRevision += 1;
  if (push) {
    history.pushState({ screen: "task-creation-entry" }, "", presentationLocationFor("T05"));
  } else {
    history.replaceState({ screen: "task-creation-entry" }, "", presentationLocationFor("T05"));
  }
  void openTaskCreation(false, "entry");
}

async function openTaskCreation(forceEdit = false, recovery = null) {
  setNavigation("", true);
  title.textContent = "Новое задание";
  shell.classList.add("task-creation-screen");
  setHeaderControl("back", { screenLabel: "Новое задание" });
  replaceContent(element("p", "Загружаем черновик…", "status muted"));
  try {
    const state = await getJson("/api/v1/task-creation");
    const draftId = state.draft?.id;
    if (draftId && (recovery === "entry" || (recovery === "stale" && state.needs_edit))) {
      history.replaceState(
        { screen: "task-recovery", draftId },
        "",
        presentationLocationFor("T04B", draftId),
      );
      showTaskRecovery(state);
      return;
    }
    if (draftId) {
      const screenId = !forceEdit && state.preview && !state.needs_edit ? "T06" : "T05";
      history.replaceState(
        { screen: screenId === "T06" ? "task-preview" : "task-creation", draftId },
        "",
        presentationLocationFor(screenId, draftId),
      );
    }
    showTaskCreation(state, forceEdit);
  } catch { replaceContent(element("p", "Не удалось открыть создание задания.", "status")); }
}

const valueSection = (heading, value) => {
  const normalized = Array.isArray(value) ? value.join(", ") : value;
  return normalized == null || normalized === ""
    ? null
    : section(heading, String(normalized));
};
const valueOrDash = (value) => value == null ? "—" : String(value);
const initialsFor = (name) => name.split(/\s+/).filter(Boolean).slice(0, 2)
  .map((part) => part[0]).join("").toUpperCase() || "?";

const memberPhotoRequests = new Map();
const memberPhotoObjectUrls = new Map();
const memberPhotoCacheTtlMs = 24 * 60 * 60 * 1000;

const memberPhotoCacheName = () => (
  `community-member-avatars-v1-${String(currentMemberId || "anonymous")}`
);

const validMemberPhoto = (photo) => (
  photo?.size > 0 && photo.type.startsWith("image/")
);

const memberPhotoRequest = (memberId) => new Request(
  new URL(
    `/api/v1/members/${encodeURIComponent(memberId)}/avatar`,
    globalThis.location.origin,
  ).href,
  { credentials: "same-origin", headers: { Accept: "image/*" } },
);

const cachedMemberPhoto = async (request) => {
  if (!("caches" in globalThis)) return null;
  try {
    const cache = await caches.open(memberPhotoCacheName());
    const response = await cache.match(request);
    if (!response) return { cache, photo: null, fresh: false };
    const photo = await response.blob();
    if (!validMemberPhoto(photo)) {
      await cache.delete(request);
      return { cache, photo: null, fresh: false };
    }
    const cachedAt = Number(response.headers.get("x-community-avatar-cached-at"));
    return {
      cache,
      photo,
      fresh: Number.isFinite(cachedAt) && Date.now() - cachedAt < memberPhotoCacheTtlMs,
    };
  } catch {
    return null;
  }
};

const loadMemberPhoto = async (memberId, { forceNetwork = false } = {}) => {
  const request = memberPhotoRequest(memberId);
  const cached = forceNetwork ? null : await cachedMemberPhoto(request);
  if (cached?.fresh) return cached.photo;

  try {
    const response = await fetch(request, forceNetwork ? { cache: "reload" } : undefined);
    if (!response.ok) return cached?.photo || null;
    const photo = await response.blob();
    if (!validMemberPhoto(photo)) return cached?.photo || null;
    if (cached?.cache) {
      try {
        await cached.cache.put(request, new Response(photo, {
          status: 200,
          headers: {
            "Content-Type": photo.type,
            "X-Community-Avatar-Cached-At": String(Date.now()),
          },
        }));
      } catch {
        // Cache Storage is optional; the in-memory cache below still avoids duplicates.
      }
    }
    return photo;
  } catch {
    return cached?.photo || null;
  }
};

const sharedMemberPhotoUrl = (memberId, { forceNetwork = false } = {}) => {
  const key = String(memberId || "").trim();
  if (!key) return Promise.resolve(null);
  if (!memberPhotoRequests.has(key)) {
    memberPhotoRequests.set(key, (async () => {
      const photo = await loadMemberPhoto(key, { forceNetwork });
      if (!photo) return null;
      const objectUrl = URL.createObjectURL(photo);
      const previous = memberPhotoObjectUrls.get(key);
      if (previous) URL.revokeObjectURL(previous);
      memberPhotoObjectUrls.set(key, objectUrl);
      return objectUrl;
    })());
  }
  return memberPhotoRequests.get(key);
};

const applyMemberPhoto = (avatar, memberId, photoUrl) => {
  avatar.querySelector(".person-avatar-photo")?.remove();
  if (!photoUrl || !avatar.isConnected) return;
  const image = document.createElement("img");
  image.className = "person-avatar-photo";
  image.src = photoUrl;
  image.alt = "";
  image.decoding = "async";
  image.addEventListener("error", () => image.remove(), { once: true });
  avatar.append(image);
};

const refreshMemberPhoto = async (memberId) => {
  const key = String(memberId || "").trim();
  if (!key) return;
  memberPhotoRequests.delete(key);
  const previous = memberPhotoObjectUrls.get(key);
  if (previous) URL.revokeObjectURL(previous);
  memberPhotoObjectUrls.delete(key);
  if ("caches" in globalThis) {
    try {
      const cache = await caches.open(memberPhotoCacheName());
      await cache.delete(memberPhotoRequest(key));
    } catch {
      // Cache Storage is optional; a network refresh still follows.
    }
  }
  const selector = `.person-avatar[data-member-id="${CSS.escape(key)}"]`;
  for (const avatar of document.querySelectorAll(selector)) applyMemberPhoto(avatar, key, null);
  const photoUrl = await sharedMemberPhotoUrl(key, { forceNetwork: true });
  for (const avatar of document.querySelectorAll(selector)) applyMemberPhoto(avatar, key, photoUrl);
};

globalThis.addEventListener("pagehide", () => {
  for (const objectUrl of memberPhotoObjectUrls.values()) URL.revokeObjectURL(objectUrl);
  memberPhotoObjectUrls.clear();
}, { once: true });

const personAvatar = (person, { size = "medium" } = {}) => {
  const displayName = person?.display_name || "?";
  const memberId = person?.member_id;
  const avatar = element(
    "span",
    initialsFor(displayName),
    `person-avatar person-avatar-${size}`,
  );
  avatar.setAttribute("aria-hidden", "true");
  if (!memberId) return avatar;
  avatar.dataset.memberId = memberId;
  void sharedMemberPhotoUrl(memberId).then((photoUrl) => {
    applyMemberPhoto(avatar, memberId, photoUrl);
  });
  return avatar;
};

const profileEditTrigger = (label, key, onOpen, className = "profile-card") => {
  const trigger = element("button", undefined, `${className} profile-edit-trigger`);
  trigger.type = "button";
  trigger.dataset.profileAction = key;
  trigger.setAttribute("aria-label", `Изменить ${label.toLowerCase()}`);
  trigger.addEventListener("click", () => onOpen(trigger));
  return trigger;
};

function createProfileEditorSheet(trigger, state, revision, titleText) {
  shell.querySelector(".profile-editor-backdrop")?.remove();
  state.draft = null;
  const backdrop = element("section", undefined, "task-size-backdrop profile-editor-backdrop");
  const dialog = element("div", undefined, "task-size-sheet profile-editor-sheet");
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.setAttribute("aria-labelledby", "profile-editor-sheet-title");
  const header = element("div", undefined, "catalog-sort-heading");
  const sheetTitle = element("h2", titleText);
  sheetTitle.id = "profile-editor-sheet-title";
  const close = element("button", "×", "catalog-sort-close");
  close.type = "button";
  close.setAttribute("aria-label", "Закрыть редактор");
  const body = element("div", undefined, "profile-editor-sheet-body");
  const dismiss = (restoreFocus = true) => {
    state.draft = null;
    backdrop.remove();
    if (restoreFocus) trigger.focus({ preventScroll: true });
  };
  const finish = () => {
    state.route = "/profile";
    showProfileState(state, revision);
  };
  const setBody = (nextTitle, node) => {
    sheetTitle.textContent = nextTitle;
    body.replaceChildren(node);
  };
  close.addEventListener("click", () => dismiss());
  backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop) dismiss();
  });
  dialog.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      dismiss();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = [...dialog.querySelectorAll(
      'button:not([disabled]), input:not([disabled]):not([type="file"]), textarea:not([disabled])',
    )];
    const first = focusable[0];
    const last = focusable.at(-1);
    if (!first || !last) return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
  header.append(sheetTitle, close);
  dialog.append(header, body);
  backdrop.append(dialog);
  shell.append(backdrop);
  return { body, close, dismiss, finish, setBody };
}

function showProfileFieldSheet(trigger, state, revision, name) {
  const titleText = name === "skills" ? "Навыки" : editorConfigs[name].title;
  const sheet = createProfileEditorSheet(trigger, state, revision, titleText);
  const editor = name === "skills"
    ? profileSkillsEditor(state, revision, sheet.finish)
    : profileTextEditor(state, revision, name, sheet.finish);
  sheet.setBody(titleText, editor);
}

function showProfileCitySheet(trigger, state, revision) {
  const sheet = createProfileEditorSheet(trigger, state, revision, "Город");
  const panel = element("section", undefined, "profile-editor profile-city-editor");
  panel.append(
    element("h2", "Выберите город"),
    element(
      "p",
      "По городу мы определим ваш часовой пояс для сроков и времени заданий.",
      "profile-helper",
    ),
    element(
      "p",
      `Часовой пояс · ${timezoneOffsetLabel(state.profile.me.timezone || "UTC")}`,
      "profile-timezone-note",
    ),
  );
  const searchLabel = element("label", "Поиск города", "city-search-field");
  const search = element("input");
  search.type = "search";
  search.autocomplete = "off";
  search.placeholder = "Начните вводить название";
  search.setAttribute("aria-label", "Поиск города");
  search.value = state.profile.me.city || "";
  searchLabel.append(search);
  const results = element("div", undefined, "city-sheet-results profile-city-results");
  results.setAttribute("role", "listbox");
  const status = element("p", "", "status hidden");
  status.setAttribute("aria-live", "polite");
  const clear = element("button", "Не указывать город", "profile-city-clear");
  clear.type = "button";
  let timer = null;
  let operationKey = null;

  const saveCity = async (value, button) => {
    operationKey ||= newOperationKey();
    for (const control of panel.querySelectorAll("button, input")) control.disabled = true;
    status.className = "status";
    status.textContent = "Сохраняем город…";
    try {
      const updated = await submissionRequest(
        "/api/v1/me/profile",
        "PUT",
        operationKey,
        { field: "city", value },
      );
      if (revision !== screenRevision) return;
      state.profile.me = updated;
      setMemberTimezone(updated.timezone || "UTC");
      state.draft = null;
      state.returnFocus = '[data-profile-action="city"]';
      sheet.dismiss(false);
      state.route = "/profile";
      showProfileState(state, revision);
    } catch (error) {
      if (!retryableSubmissionError(error)) operationKey = null;
      status.className = "status";
      status.textContent = error?.status === 422
        ? "Выберите город из найденного списка."
        : "Не удалось сохранить город. Повторите попытку.";
      for (const control of panel.querySelectorAll("button, input")) control.disabled = false;
      button?.focus({ preventScroll: true });
    }
  };
  const loadResults = async (query) => {
    if (!query) {
      results.replaceChildren(element("p", "Введите название города.", "city-sheet-empty"));
      return;
    }
    results.replaceChildren(element("p", "Ищем города…", "city-sheet-empty"));
    try {
      const response = await getJson(`/api/v1/task-cities?q=${encodeURIComponent(query)}&limit=8`);
      if (!panel.isConnected || search.value.trim() !== query) return;
      if (!response.items.length) {
        results.replaceChildren(element("p", "Города не найдены.", "city-sheet-empty"));
        return;
      }
      results.replaceChildren();
      for (const item of response.items) {
        const option = element("button", undefined, "city-sheet-option");
        option.type = "button";
        option.setAttribute("role", "option");
        option.setAttribute("aria-label", item.label);
        option.setAttribute("aria-selected", String(item.value === state.profile.me.city));
        const optionCopy = element("span", undefined, "city-sheet-copy");
        optionCopy.append(
          element("strong", item.label),
          element("small", timezoneOffsetLabel(item.timezone || state.profile.me.timezone)),
        );
        option.append(
          element("span", "⌖", "city-sheet-icon"),
          optionCopy,
          element("span", item.value === state.profile.me.city ? "✓" : "", "city-sheet-check"),
        );
        option.addEventListener("click", () => void saveCity(item.value, option));
        results.append(option);
      }
    } catch {
      if (!panel.isConnected) return;
      results.replaceChildren(element("p", "Не удалось загрузить города.", "city-sheet-empty"));
    }
  };
  search.addEventListener("input", () => {
    clearTimeout(timer);
    operationKey = null;
    status.className = "status hidden";
    const query = search.value.trim();
    timer = setTimeout(() => void loadResults(query), 200);
  });
  search.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      results.querySelector("button")?.focus();
    }
  });
  clear.addEventListener("click", () => void saveCity("", clear));
  panel.append(searchLabel, results, clear, status);
  sheet.setBody("Город", panel);
  queueMicrotask(() => {
    search.focus({ preventScroll: true });
    search.select();
    void loadResults(search.value.trim());
  });
}

function showProfileLinksSheet(trigger, state, revision) {
  const sheet = createProfileEditorSheet(trigger, state, revision, "Ссылки");
  const renderDelete = (link) => {
    state.draft = { route: state.route, operationKey: null };
    const panel = element("section", undefined, "profile-editor profile-link-delete");
    panel.append(
      element("span", "Подтверждение", "confirm-badge"),
      element("h2", `Удалить ${link.label}?`),
      element("p", "Ссылка исчезнет из профиля. Сам аккаунт не изменится.", "profile-helper"),
    );
    const status = element("p", "", "status hidden");
    const remove = element("button", "Удалить", "secondary danger profile-delete-large");
    remove.type = "button";
    remove.addEventListener("click", async () => {
      await saveProfileCommand(
        state,
        revision,
        remove,
        status,
        { field: "profile_links", action: "delete", link_id: link.id },
        "/profile",
        '[data-profile-action="links"]',
        sheet.finish,
      );
    });
    panel.append(status, remove);
    sheet.setBody("Удалить ссылку", panel);
    queueMicrotask(() => remove.focus({ preventScroll: true }));
  };
  const renderEditor = (linkId = null) => {
    state.draft = null;
    const link = linkId
      ? state.profile.me.profile_links.find((item) => item.id === linkId)
      : null;
    const editor = profileLinkEditor(state, revision, linkId, {
      onSaved: sheet.finish,
      onDelete: renderDelete,
    });
    sheet.setBody(link ? "Изменить ссылку" : "Новая ссылка", editor);
  };
  const renderManager = () => {
    state.draft = null;
    const links = state.profile.me.profile_links || [];
    const manager = element("section", undefined, "profile-links-manager");
    const list = element("div", undefined, "managed-link-list");
    for (const link of links) {
      const row = element("div", undefined, "managed-link-row");
      const edit = element("button", undefined, "managed-link-open");
      edit.type = "button";
      edit.dataset.linkId = link.id;
      edit.setAttribute("aria-label", `Изменить ссылку ${link.label}`);
      const copy = element("span", undefined, "managed-link-copy");
      copy.append(element("strong", link.label), element("span", link.url));
      edit.append(copy, element("span", "›", "profile-edit-chevron"));
      edit.addEventListener("click", () => renderEditor(link.id));
      const trash = element("button", undefined, "link-trash");
      trash.type = "button";
      trash.setAttribute("aria-label", `Удалить ссылку ${link.label}`);
      trash.append(trashIcon());
      trash.addEventListener("click", () => renderDelete(link));
      row.append(edit, trash);
      list.append(row);
    }
    manager.append(list);
    if (links.length < 5) {
      const add = element("button", "+ Добавить ссылку", "secondary profile-add-link");
      add.type = "button";
      add.addEventListener("click", () => renderEditor());
      manager.append(add);
    }
    manager.append(element("p", `${links.length} / 5 ссылок`, "profile-counter"));
    sheet.setBody("Ссылки", manager);
    queueMicrotask(() => (list.querySelector("button") || manager.querySelector("button") || sheet.close)
      ?.focus({ preventScroll: true }));
  };
  renderManager();
}

const avatarImageFile = (input) => new Promise((resolve, reject) => {
  const file = input?.files?.[0];
  if (!file || !file.type.startsWith("image/")) {
    reject(new Error("invalid_image"));
    return;
  }
  const objectUrl = URL.createObjectURL(file);
  const image = new Image();
  image.onload = () => {
    URL.revokeObjectURL(objectUrl);
    resolve(image);
  };
  image.onerror = () => {
    URL.revokeObjectURL(objectUrl);
    reject(new Error("invalid_image"));
  };
  image.src = objectUrl;
});

function showProfileAvatarSheet(trigger, state, revision) {
  const sheet = createProfileEditorSheet(trigger, state, revision, "Фото профиля");
  const memberId = state.profile.me.member_id;
  const galleryInput = element("input");
  galleryInput.type = "file";
  galleryInput.hidden = true;
  galleryInput.accept = "image/*";
  galleryInput.className = "avatar-file-input";
  galleryInput.tabIndex = -1;
  galleryInput.setAttribute("aria-hidden", "true");
  const cameraInput = element("input");
  cameraInput.type = "file";
  cameraInput.hidden = true;
  cameraInput.accept = "image/*";
  cameraInput.capture = "user";
  cameraInput.className = "avatar-file-input";
  cameraInput.tabIndex = -1;
  cameraInput.setAttribute("aria-hidden", "true");

  const finish = async () => {
    await refreshMemberPhoto(memberId);
    if (revision !== screenRevision) return;
    state.returnFocus = '[data-profile-action="avatar"]';
    sheet.dismiss(false);
    state.route = "/profile";
    showProfileState(state, revision);
  };

  const renderCrop = (image) => {
    const panel = element("section", undefined, "profile-avatar-editor");
    panel.append(
      element("p", "Перемещайте фото и настройте масштаб", "profile-helper avatar-crop-helper"),
    );
    const stage = element("div", undefined, "avatar-crop-stage");
    const canvas = element("canvas", undefined, "avatar-crop-canvas");
    canvas.width = 512;
    canvas.height = 512;
    canvas.setAttribute("aria-label", "Круглый предпросмотр фотографии");
    stage.append(canvas, element("span", undefined, "avatar-crop-ring"));
    const context = canvas.getContext("2d", { alpha: false });
    const zoom = element("input");
    zoom.type = "range";
    zoom.min = "1";
    zoom.max = "3";
    zoom.step = "0.01";
    zoom.value = "1";
    zoom.setAttribute("aria-label", "Масштаб фотографии");
    const zoomRow = element("label", undefined, "avatar-zoom-row");
    zoomRow.append(element("span", "−"), zoom, element("span", "+"));
    const status = element("p", "", "status hidden");
    status.setAttribute("aria-live", "polite");
    const save = element("button", "Сохранить", "primary avatar-save");
    save.type = "button";
    const chooseAgain = element("button", "Выбрать другое фото", "secondary avatar-choose-again");
    chooseAgain.type = "button";
    let scale = 1;
    let offsetX = 0;
    let offsetY = 0;
    const pointers = new Map();
    let pinchDistance = null;
    let pinchScale = 1;

    const draw = () => {
      const baseScale = Math.max(512 / image.naturalWidth, 512 / image.naturalHeight);
      const width = image.naturalWidth * baseScale * scale;
      const height = image.naturalHeight * baseScale * scale;
      const maxX = Math.max(0, (width - 512) / 2);
      const maxY = Math.max(0, (height - 512) / 2);
      offsetX = Math.max(-maxX, Math.min(maxX, offsetX));
      offsetY = Math.max(-maxY, Math.min(maxY, offsetY));
      context.fillStyle = "#fff";
      context.fillRect(0, 0, 512, 512);
      context.drawImage(
        image,
        (512 - width) / 2 + offsetX,
        (512 - height) / 2 + offsetY,
        width,
        height,
      );
    };
    const distance = () => {
      const points = [...pointers.values()];
      return points.length < 2 ? 0 : Math.hypot(
        points[0].x - points[1].x,
        points[0].y - points[1].y,
      );
    };
    zoom.addEventListener("input", () => {
      scale = Number(zoom.value);
      draw();
    });
    canvas.addEventListener("pointerdown", (event) => {
      canvas.setPointerCapture(event.pointerId);
      pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      if (pointers.size === 2) {
        pinchDistance = distance();
        pinchScale = scale;
      }
    });
    canvas.addEventListener("pointermove", (event) => {
      const previous = pointers.get(event.pointerId);
      if (!previous) return;
      pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      if (pointers.size === 1) {
        const ratio = 512 / Math.max(1, canvas.clientWidth);
        offsetX += (event.clientX - previous.x) * ratio;
        offsetY += (event.clientY - previous.y) * ratio;
      } else if (pinchDistance) {
        scale = Math.max(1, Math.min(3, pinchScale * distance() / pinchDistance));
        zoom.value = String(scale);
      }
      draw();
    });
    const releasePointer = (event) => {
      pointers.delete(event.pointerId);
      if (pointers.size < 2) pinchDistance = null;
    };
    canvas.addEventListener("pointerup", releasePointer);
    canvas.addEventListener("pointercancel", releasePointer);
    chooseAgain.addEventListener("click", () => galleryInput.click());
    save.addEventListener("click", async () => {
      save.disabled = true;
      chooseAgain.disabled = true;
      zoom.disabled = true;
      status.className = "status";
      status.textContent = "Сохраняем фотографию…";
      try {
        const blob = await new Promise((resolve, reject) => canvas.toBlob(
          (value) => value ? resolve(value) : reject(new Error("encode_failed")),
          "image/jpeg",
          0.86,
        ));
        const response = await apiFetch("/api/v1/me/avatar", {
          method: "PUT",
          credentials: "same-origin",
          headers: { "Content-Type": "image/jpeg" },
          body: blob,
        });
        if (!response.ok) {
          throw Object.assign(new Error(requestError(response)), { status: response.status });
        }
        await finish();
      } catch (error) {
        status.textContent = error?.status === 422
          ? "Фото не подходит. Выберите другое изображение."
          : "Не удалось сохранить фотографию. Повторите попытку.";
        save.disabled = false;
        chooseAgain.disabled = false;
        zoom.disabled = false;
      }
    });
    panel.append(stage, zoomRow, status, save, chooseAgain, galleryInput, cameraInput);
    sheet.setBody("Настройка фото", panel);
    draw();
    queueMicrotask(() => save.focus({ preventScroll: true }));
  };

  const selectImage = async (input) => {
    try {
      renderCrop(await avatarImageFile(input));
    } catch {
      input.value = "";
    }
  };
  galleryInput.addEventListener("change", () => void selectImage(galleryInput));
  cameraInput.addEventListener("change", () => void selectImage(cameraInput));

  const renderManager = async () => {
    const panel = element("section", undefined, "profile-avatar-manager");
    const preview = element("div", undefined, "profile-avatar-preview");
    preview.append(personAvatar(state.profile.me));
    const copy = element("div", undefined, "profile-avatar-copy");
    copy.append(
      element("p", "Оно будет видно рядом с вашим именем во всём приложении.", "profile-helper"),
    );
    const choose = element("button", "Выбрать из галереи", "primary avatar-source-button");
    choose.type = "button";
    choose.addEventListener("click", () => galleryInput.click());
    const camera = element("button", "Сделать фото", "secondary avatar-source-button");
    camera.type = "button";
    camera.addEventListener("click", () => cameraInput.click());
    const restore = element("button", "Вернуть фото из Telegram", "avatar-restore hidden");
    restore.type = "button";
    const status = element("p", "", "status hidden");
    status.setAttribute("aria-live", "polite");
    restore.addEventListener("click", async () => {
      for (const control of panel.querySelectorAll("button")) control.disabled = true;
      status.className = "status";
      status.textContent = "Возвращаем фото из Telegram…";
      try {
        const response = await apiFetch("/api/v1/me/avatar", {
          method: "DELETE",
          credentials: "same-origin",
        });
        if (!response.ok) throw new Error(requestError(response));
        await finish();
      } catch {
        status.textContent = "Не удалось вернуть фото из Telegram. Повторите попытку.";
        for (const control of panel.querySelectorAll("button")) control.disabled = false;
      }
    });
    panel.append(preview, copy, choose, camera, restore, status, galleryInput, cameraInput);
    sheet.setBody("Фото профиля", panel);
    try {
      const preference = await getJson("/api/v1/me/avatar");
      if (panel.isConnected && preference.custom) restore.classList.remove("hidden");
    } catch {
      if (panel.isConnected) {
        status.className = "status";
        status.textContent = "Не удалось проверить текущее фото.";
      }
    }
    queueMicrotask(() => choose.focus({ preventScroll: true }));
  };
  void renderManager();
}

const openPublicUrl = (url, options = {}) => {
  if (!openExternalLink(url, options)) {
    content.append(element("p", "Не удалось открыть ссылку.", "status"));
  }
};

const publicLinkRow = (link) => {
  const button = element("button", undefined, "public-link-row");
  button.type = "button";
  button.append(element("strong", link.label), element("span", link.url), element("span", "↗"));
  button.addEventListener("click", () => openPublicUrl(link.url));
  return button;
};

function ownProfileOverview(state, revision) {
  const { me, member } = state.profile;
  const view = element("section", undefined, "profile-overview");
  const identity = element("section", undefined, "profile-card profile-identity-card");
  const avatarTrigger = element("button", undefined, "profile-avatar-trigger");
  avatarTrigger.type = "button";
  avatarTrigger.dataset.profileAction = "avatar";
  avatarTrigger.setAttribute("aria-label", "Изменить фото профиля");
  const cameraBadge = element("span", undefined, "profile-avatar-camera");
  cameraBadge.append(cameraIcon());
  avatarTrigger.append(personAvatar(me), cameraBadge);
  avatarTrigger.addEventListener("click", () => {
    showProfileAvatarSheet(avatarTrigger, state, revision);
  });
  const nameTrigger = profileEditTrigger(
    "имя",
    "name",
    (trigger) => showProfileFieldSheet(trigger, state, revision, "name"),
    "profile-identity-name",
  );
  const copy = element("div", undefined, "identity-copy");
  copy.append(element("h2", me.display_name));
  if (me.telegram_username) copy.append(element("p", `@${me.telegram_username}`, "profile-username"));
  copy.append(element("p", `Уровень ${me.level.number} · ${me.level.display_name}`, "muted"));
  nameTrigger.append(copy, element("span", "›", "profile-edit-chevron"));
  identity.append(avatarTrigger, nameTrigger);
  const city = profileEditTrigger(
    "город",
    "city",
    (trigger) => showProfileCitySheet(trigger, state, revision),
    "profile-card profile-inline-card",
  );
  city.append(element("div", undefined, "profile-copy"));
  city.append(element("span", "›", "profile-edit-chevron"));
  city.firstChild.append(
    element("span", "Город", "section-label"),
    element("strong", me.city || "Не указан"),
    element("small", timezoneOffsetLabel(me.timezone || "UTC"), "profile-timezone"),
  );
  const metrics = element("div", undefined, "metric-grid");
  for (const [value, label] of [[me.credit_balance, "Кредиты"], [me.experience_total, "Опыт"], [member.karma.score, "Карма"]]) {
    const metric = element("article", undefined, "metric-card");
    metric.append(element("strong", valueOrDash(value)), element("span", label));
    metrics.append(metric);
  }
  view.append(identity, city, metrics);
  const blocks = [
    ["О себе", me.short_bio, "bio", "Добавить описание", "Расскажите о себе"],
    ["Навыки", me.skill_tags, "skills", "Добавить навыки", "Добавьте навыки"],
  ];
  for (const [label, value, key, cta, emptyTitle] of blocks) {
    const filled = Array.isArray(value) ? value.length > 0 : Boolean(value);
    const openSheet = (trigger) => showProfileFieldSheet(trigger, state, revision, key);
    const block = profileEditTrigger(
      label,
      key,
      openSheet,
      filled ? "profile-card profile-content-card" : "profile-empty-card",
    );
    if (filled) {
      block.append(element("h3", label, "section-label"));
      block.append(element("span", "›", "profile-edit-chevron"));
      if (Array.isArray(value)) {
        const chips = element("div", undefined, "profile-chips");
        value.forEach((item) => chips.append(element("span", item)));
        block.append(chips);
      } else block.append(element("p", value));
    } else {
      block.append(element("strong", emptyTitle), element("p", key === "bio" ? "Пара строк поможет другим участникам понять, чем вы занимаетесь." : "Навыки помогут быстрее понять, с чем к вам можно обратиться.", "muted"));
      block.append(
        element("span", cta, "profile-edit-cta"),
        element("span", "›", "profile-edit-chevron"),
      );
    }
    view.append(block);
  }
  const links = me.profile_links || [];
  const linksBlock = element("section", undefined, links.length ? "profile-links-block" : "profile-empty-card");
  if (links.length) {
    const header = profileEditTrigger(
      "ссылки",
      "links",
      (trigger) => showProfileLinksSheet(trigger, state, revision),
      "profile-section-heading",
    );
    header.append(element("h3", "Ссылки"));
    header.append(element("span", "›", "profile-edit-chevron"));
    linksBlock.append(header);
    links.forEach((link) => linksBlock.append(publicLinkRow(link)));
  } else {
    linksBlock.remove();
    const emptyLinks = profileEditTrigger(
      "ссылки",
      "links",
      (trigger) => showProfileLinksSheet(trigger, state, revision),
      "profile-empty-card",
    );
    emptyLinks.append(
      element("strong", "Добавьте ссылки"),
      element("p", "LinkedIn, GitHub, сайт или другие публичные страницы.", "muted"),
      element("span", "Добавить ссылки", "profile-edit-cta"),
      element("span", "›", "profile-edit-chevron"),
    );
    view.append(emptyLinks);
    return view;
  }
  view.append(linksBlock);
  return view;
}

const editorConfigs = {
  name: { title: "Имя", prompt: "Как к вам обращаться?", helper: "Это имя увидят другие участники в профиле и заданиях.", field: "display_name", min: 2, max: 80, multiline: false },
  city: { title: "Город", prompt: "В каком городе вы живёте?", field: "city", min: 2, max: 80, multiline: false },
  bio: { title: "О себе", label: "Описание", prompt: "Расскажите о себе", helper: "Чем вы занимаетесь и чем можете быть полезны сообществу.", field: "short_bio", min: 10, max: 500, multiline: true },
};

const titlelessProfileRoutes = new Set([
  "/profile/edit/city",
  "/profile/edit/bio",
  "/profile/edit/skills",
  "/profile/links",
]);

function profileTextEditor(state, revision, name, onSaved = null) {
  const config = editorConfigs[name];
  const current = state.profile.me[config.field] || "";
  const draft = state.draft?.route === state.route ? state.draft : { route: state.route, value: current, operationKey: null, message: "" };
  state.draft = draft;
  const form = element("form", undefined, "profile-editor");
  form.append(element("h2", config.prompt));
  if (config.helper) form.append(element("p", config.helper, "profile-helper"));
  const label = element("label", config.label || config.title);
  const input = element(config.multiline ? "textarea" : "input");
  input.value = draft.value;
  input.minLength = config.min;
  input.maxLength = config.max;
  input.required = true;
  label.append(input);
  const counter = element("p", `${input.value.length} / ${config.max}`, "profile-counter");
  const status = element("p", draft.message, draft.message ? "status" : "status hidden");
  status.setAttribute("aria-live", "polite");
  input.addEventListener("input", () => {
    if (draft.value !== input.value) draft.operationKey = null;
    draft.value = input.value;
    draft.message = "";
    counter.textContent = `${input.value.length} / ${config.max}`;
    status.className = "status hidden";
  });
  const save = element("button", "Сохранить", "primary");
  save.type = "submit";
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    await saveProfileCommand(state, revision, save, status, { field: config.field, value: draft.value }, `/profile`, `[data-profile-action="${name}"]`, onSaved);
  });
  form.append(label, counter, status, save);
  queueMicrotask(() => input.focus({ preventScroll: true }));
  return form;
}

function profileSkillsEditor(state, revision, onSaved = null) {
  const draft = state.draft?.route === state.route ? state.draft : { route: state.route, items: [...state.profile.me.skill_tags], operationKey: null, message: "" };
  state.draft = draft;
  const form = element("form", undefined, "profile-editor profile-skills-editor");
  form.append(
    element("h2", "Чем вы можете помочь?"),
    element("p", "Добавьте до 20 коротких навыков — они будут показаны в профиле.", "profile-helper"),
  );
  const label = element("label", "Добавить навык");
  const row = element("div", undefined, "skill-input-row");
  const input = element("input");
  input.maxLength = 50;
  input.placeholder = "Например, дизайн";
  input.autocomplete = "off";
  const add = element("button", "Добавить", "secondary skill-add");
  add.type = "button";
  add.setAttribute("aria-label", "Добавить навык");
  row.append(input, add);
  label.append(row);
  const list = element("div", undefined, "skill-draft-list");
  const status = element("p", draft.message, draft.message ? "status" : "status hidden");
  status.setAttribute("aria-live", "polite");
  const counter = element("p", `${draft.items.length} / 20 навыков`, "profile-counter");
  const renderItems = () => {
    list.replaceChildren();
    list.classList.toggle("is-empty", draft.items.length === 0);
    if (!draft.items.length) {
      list.append(element("p", "Навыки пока не добавлены", "skill-empty"));
    }
    draft.items.forEach((item, index) => {
      const skill = element("span", undefined, "skill-draft-row");
      const remove = element("button", "×", "skill-remove");
      remove.type = "button";
      remove.setAttribute("aria-label", `Удалить навык ${item}`);
      remove.addEventListener("click", () => {
        draft.items.splice(index, 1);
        draft.operationKey = null;
        status.className = "status hidden";
        renderItems();
      });
      skill.append(element("strong", item), remove);
      list.append(skill);
    });
    counter.textContent = `${draft.items.length} / 20 навыков`;
    counter.setAttribute("aria-label", `${draft.items.length} из 20 навыков`);
  };
  const addSkill = () => {
    const value = input.value.trim().replace(/\s+/g, " ");
    if (!value || draft.items.length >= 20 || draft.items.some((item) => item.toLowerCase() === value.toLowerCase())) {
      status.className = "status";
      status.textContent = draft.items.some((item) => item.toLowerCase() === value.toLowerCase())
        ? "Такой навык уже добавлен."
        : "Проверьте навык или лимит 20.";
      input.focus();
      return;
    }
    draft.items.push(value);
    draft.operationKey = null;
    input.value = "";
    status.className = "status hidden";
    renderItems();
    input.focus();
  };
  add.addEventListener("click", addSkill);
  input.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    addSkill();
  });
  const save = element("button", "Сохранить", "primary");
  save.type = "submit";
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    await saveProfileCommand(state, revision, save, status, { field: "skill_tags", value: draft.items.join("\n") }, "/profile", '[data-profile-action="skills"]', onSaved);
  });
  renderItems();
  const footer = element("div", undefined, "profile-editor-footer");
  footer.append(counter, save);
  form.append(label, list, status, footer);
  queueMicrotask(() => input.focus({ preventScroll: true }));
  return form;
}

async function saveProfileCommand(state, revision, button, status, payload, destination, focusSelector, onSaved = null) {
  button.disabled = true;
  status.className = "status";
  status.textContent = "Сохраняем…";
  state.draft.operationKey ||= newOperationKey();
  try {
    const updated = await submissionRequest("/api/v1/me/profile", "PUT", state.draft.operationKey, payload);
    if (revision !== screenRevision) return;
    state.profile.me = updated;
    setMemberTimezone(updated.timezone || "UTC");
    state.draft = null;
    state.returnFocus = focusSelector;
    if (onSaved) {
      onSaved(updated);
      return;
    }
    openProfileRoute(state, revision, destination, false);
  } catch (error) {
    if (revision !== screenRevision) return;
    if (!retryableSubmissionError(error)) state.draft.operationKey = null;
    status.textContent = error?.status === 422 ? "Проверьте введённые данные." : error?.status === 409 ? "Профиль уже изменился. Повторите сохранение." : "Не удалось сохранить. Повторите попытку.";
    button.disabled = false;
  }
}

function profileLinksList(state, revision) {
  const links = state.profile.me.profile_links || [];
  const view = element("section", undefined, "profile-links-manager");
  const list = element("div", undefined, "managed-link-list");
  links.forEach((link) => {
    const row = element("div", undefined, "managed-link-row");
    row.append(element("div", undefined, "managed-link-copy"));
    row.firstChild.append(element("strong", link.label), element("span", link.url));
    const edit = element("button", "✎", "profile-pencil");
    edit.type = "button";
    edit.dataset.linkId = link.id;
    edit.setAttribute("aria-label", `Изменить ссылку ${link.label}`);
    edit.addEventListener("click", () => openProfileRoute(state, revision, `/profile/links/${link.id}`, true));
    const trash = element("button", undefined, "link-trash");
    trash.type = "button";
    trash.dataset.linkTrashId = link.id;
    trash.setAttribute("aria-label", `Удалить ссылку ${link.label}`);
    trash.append(trashIcon());
    trash.addEventListener("click", () => {
      state.deleteOrigin = "list";
      history.replaceState(
        { ...history.state, profileReturnFocus: `[data-link-trash-id="${link.id}"]` },
        "",
        location.href,
      );
      openProfileRoute(state, revision, `/profile/links/${link.id}/delete`, true);
    });
    row.append(edit, trash);
    list.append(row);
  });
  view.append(list);
  if (links.length < 5) {
    const add = element("button", "+ Добавить ссылку", "secondary profile-add-link");
    add.type = "button";
    add.dataset.profileAddLink = "true";
    add.addEventListener("click", () => openProfileRoute(state, revision, "/profile/links/new", true));
    view.append(add);
  }
  view.append(element("p", `${links.length} / 5 ссылок`, "profile-counter"));
  return view;
}

function profileLinkEditor(state, revision, linkId = null, { onSaved = null, onDelete = null } = {}) {
  const existing = linkId ? state.profile.me.profile_links.find((item) => item.id === linkId) : null;
  if (linkId && !existing) return element("p", "Ссылка не найдена.", "status");
  const draft = state.draft?.route === state.route ? state.draft : {
    route: state.route,
    label: existing?.label || "",
    url: existing?.url || "",
    operationKey: null,
  };
  state.draft = draft;
  const form = element("form", undefined, "profile-editor link-editor");
  form.append(element("h2", existing ? "Изменить ссылку" : "Добавьте публичную страницу"));
  form.append(element("p", existing
    ? "Исправьте название или адрес и сохраните изменения."
    : "Название увидят люди, адрес откроется при нажатии.", "profile-helper"));
  const label = element("label", "Название");
  const labelInput = element("input");
  labelInput.value = draft.label;
  labelInput.maxLength = 32;
  labelInput.required = true;
  label.append(labelInput);
  const counter = element("p", `${draft.label.length} / 32`, "profile-counter");
  let presets = null;
  if (!existing) {
    presets = element("div", undefined, "link-presets");
    ["LinkedIn", "GitHub", "Сайт", "YouTube"].forEach((value) => {
      const preset = element("button", value, "link-preset");
      preset.type = "button";
      preset.addEventListener("click", () => {
        labelInput.value = value;
        labelInput.dispatchEvent(new Event("input", { bubbles: true }));
        labelInput.focus();
      });
      presets.append(preset);
    });
  }
  const urlLabel = element("label", "Ссылка");
  const urlInput = element("input");
  urlInput.type = "url";
  urlInput.value = draft.url;
  urlInput.maxLength = 2048;
  urlInput.required = true;
  urlInput.placeholder = "https://";
  urlLabel.append(
    urlInput,
    element("small", "Только полный адрес, начинающийся с https://", "profile-helper"),
  );
  const status = element("p", "", "status hidden");
  const changed = () => {
    draft.label = labelInput.value;
    draft.url = urlInput.value;
    draft.operationKey = null;
    counter.textContent = `${draft.label.length} / 32`;
  };
  labelInput.addEventListener("input", changed);
  urlInput.addEventListener("input", changed);
  const save = element("button", "Сохранить", "primary");
  save.type = "submit";
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = existing
      ? { field: "profile_links", action: "update", link_id: existing.id, label: draft.label, url: draft.url }
      : { field: "profile_links", action: "create", label: draft.label, url: draft.url };
    await saveProfileCommand(state, revision, save, status, payload, "/profile/links", existing ? `[data-link-id="${existing.id}"]` : "[data-profile-add-link]", onSaved);
  });
  form.append(label, counter);
  if (presets) form.append(presets);
  form.append(urlLabel, status, save);
  if (existing) {
    const remove = element("button", "Удалить", "secondary danger profile-delete-large");
    remove.type = "button";
    remove.dataset.linkDeleteId = existing.id;
    remove.addEventListener("click", () => {
      if (onDelete) {
        onDelete(existing);
        return;
      }
      state.deleteOrigin = "edit";
      history.replaceState(
        { ...history.state, profileReturnFocus: `[data-link-delete-id="${existing.id}"]` },
        "",
        location.href,
      );
      openProfileRoute(state, revision, `/profile/links/${existing.id}/delete`, true);
    });
    form.append(remove);
  }
  queueMicrotask(() => labelInput.focus({ preventScroll: true }));
  return form;
}

function profileDeleteConfirm(state, revision, linkId) {
  const link = state.profile.me.profile_links.find((item) => item.id === linkId);
  if (!link) return element("p", "Ссылка уже удалена.", "status");
  const backdrop = element("section", undefined, "profile-confirm-backdrop");
  const dialog = element("div", undefined, "profile-confirm-sheet");
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.setAttribute("aria-labelledby", "delete-link-title");
  const heading = element("h2", `Удалить ${link.label}?`);
  heading.id = "delete-link-title";
  const status = element("p", "Ссылка исчезнет из профиля. Сам аккаунт не изменится.", "status muted");
  const remove = element("button", "Удалить", "secondary danger profile-delete-large");
  remove.type = "button";
  remove.addEventListener("click", async () => {
    state.draft ||= { route: state.route, operationKey: null };
    const index = state.profile.me.profile_links.findIndex((item) => item.id === link.id);
    const next = state.profile.me.profile_links[index + 1];
    await saveProfileCommand(state, revision, remove, status, { field: "profile_links", action: "delete", link_id: link.id }, "/profile/links", next ? `[data-link-id="${next.id}"]` : "[data-profile-add-link]");
  });
  dialog.append(element("span", "Подтверждение", "confirm-badge"), heading, status, remove);
  backdrop.append(dialog);
  dialog.addEventListener("keydown", (event) => {
    if (event.key !== "Tab") return;
    event.preventDefault();
    remove.focus();
  });
  queueMicrotask(() => remove.focus({ preventScroll: true }));
  return backdrop;
}

function openProfileRoute(state, revision, route, push) {
  state.route = route;
  state.draft = state.draft?.route === route ? state.draft : null;
  if (push && state.fromSettings) state.closeHistoryDelta += 1;
  const profileHistory = {
    screen: "profile",
    route,
    returnToSettings: state.fromSettings,
    profileCloseDelta: state.closeHistoryDelta,
  };
  if (push) history.pushState(profileHistory, "", `#${route}`);
  else history.replaceState(profileHistory, "", `#${route}`);
  showProfileState(state, revision);
}

const communityStatPeriods = [
  ["week", "Неделя"],
  ["month", "Месяц"],
  ["year", "Год"],
  ["all", "Всё время"],
];
const communityAchievementCatalog = [
  {
    code: "speaker",
    icon: "💬",
    title: "Спикер",
    hint: "Пишите сообщения в чате.",
  },
  {
    code: "magnet",
    icon: "🎯",
    title: "Магнит",
    hint: "Получайте реакции на свои сообщения.",
  },
  {
    code: "petrosyan",
    icon: "🤣",
    title: "Петросян",
    hint: "Получайте реакции 😁 и 🤣 на свои сообщения.",
  },
  {
    code: "sharp",
    icon: "💯",
    title: "Чёткий",
    hint: "Получайте реакцию 💯 на свои сообщения.",
  },
  {
    code: "firefighter",
    icon: "🔥",
    title: "Пожарник",
    hint: "Получайте реакцию 🔥 на свои сообщения.",
  },
  {
    code: "heartbreaker",
    icon: "❤️‍🔥",
    title: "Сердцеед",
    hint: "Получайте ❤️, ❤️‍🔥, ❤️‍🩹 или цветные сердца на свои сообщения.",
  },
  {
    code: "support",
    icon: "🙌",
    title: "Поддержка",
    hint: "Ставьте реакции на сообщения в чате.",
  },
  {
    code: "regular",
    icon: "📅",
    title: "Завсегдатай",
    hint: "Будьте активны в разные дни.",
  },
  {
    code: "explorer",
    icon: "🧭",
    title: "Исследователь",
    hint: "Участвуйте в разных темах.",
  },
  {
    code: "streak",
    icon: "🔥",
    title: "Серия",
    hint: "Будьте активны без перерыва.",
  },
  {
    code: "dialog",
    icon: "↩️",
    title: "Диалог",
    hint: "Отправляйте сообщения-ответы.",
  },
  {
    code: "wake_up",
    icon: "⏰",
    title: "Будильник",
    hint: "Возвращайте в разговор участников, которые давно не появлялись в чате.",
  },
  {
    code: "bread_and_salt",
    icon: "🍞",
    title: "Хлеб-соль",
    hint: "Приветствуйте новичков и помогайте им включиться в общение.",
  },
  {
    code: "onboarder",
    icon: "🤝",
    title: "Онбордист",
    hint: "Отвечайте новым участникам и помогайте им освоиться в комьюнити.",
  },
  {
    code: "wealth",
    icon: "💰",
    title: "Я богач",
    hint: "Достигайте нового максимального баланса.",
  },
  {
    code: "manager",
    icon: "🗂️",
    title: "Менеджер",
    hint: "Создавайте задания для сообщества.",
  },
];
const communityLeaderboardMetricGroups = [
  {
    label: "Основное",
    options: [
      { value: "experience", label: "Опыт", icon: "⚡" },
      { value: "karma", label: "Карма", icon: "◆" },
    ],
  },
  {
    label: "Активность",
    options: [
      { value: "messages", label: "Сообщения", icon: "💬" },
      { value: "reactions_given", label: "Поставленные реакции", icon: "🙌" },
      { value: "reactions_received", label: "Полученные реакции", icon: "🎯" },
    ],
  },
  {
    label: "Достижения · уровень",
    options: communityAchievementCatalog.map((achievement) => ({
      value: `achievement:${achievement.code}`,
      label: achievement.title,
      icon: achievement.icon,
    })),
  },
];
const communityLeaderboardMetrics = communityLeaderboardMetricGroups.flatMap((group) => group.options);

function leaderboardDetails(items, metric, period) {
  const boundary = element("section", undefined, "leaderboard-boundary");
  if (!items.length) {
    boundary.append(element("p", "В лидерборде пока никого нет.", "status muted"));
    return boundary;
  }
  const formatValue = (value) => {
    if (metric === "experience") return `${value} XP`;
    if (metric === "karma") return `${value} кармы`;
    if (metric === "messages") return `${value} сообщ.`;
    if (metric === "reactions_given" || metric === "reactions_received") return `${value} реакц.`;
    return `Ур. ${value}`;
  };
  const list = element("ol", undefined, "leaderboard-list");
  for (const item of items) {
    const row = element("li");
    const button = element(
      "button",
      undefined,
      `leaderboard-row${item.member_id === currentMemberId ? " is-current" : ""}`,
    );
    button.type = "button";
    button.append(
      element("span", String(item.rank), "leaderboard-rank"),
      element("strong", item.display_name, "leaderboard-name"),
      element("span", formatValue(item.value), "leaderboard-value"),
    );
    button.addEventListener("click", () => showMemberProfile(item.member_id));
    row.append(button);
    list.append(row);
  }
  boundary.append(list);
  return boundary;
}

function showLeaderboardMetricSheet(state, revision, trigger) {
  shell.querySelector(".leaderboard-filter-backdrop")?.remove();
  trigger.setAttribute("aria-expanded", "true");
  const backdrop = element("section", undefined, "leaderboard-filter-backdrop");
  const shellBox = shell.getBoundingClientRect();
  const triggerBox = trigger.getBoundingClientRect();
  backdrop.style.setProperty(
    "--leaderboard-filter-top",
    `${Math.max(10, Math.round(triggerBox.bottom - shellBox.top + 8))}px`,
  );
  const dialog = element("div", undefined, "leaderboard-filter-sheet");
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.setAttribute("aria-labelledby", "leaderboard-filter-title");
  const header = element("div", undefined, "leaderboard-filter-heading");
  const heading = element("h2", "Рейтинг по");
  heading.id = "leaderboard-filter-title";
  const close = element("button", "×", "leaderboard-filter-close");
  close.type = "button";
  close.setAttribute("aria-label", "Закрыть выбор рейтинга");
  header.append(heading, close);
  const groups = element("div", undefined, "leaderboard-filter-groups");
  let selectedOption = null;
  const dismiss = (restoreFocus = true) => {
    trigger.setAttribute("aria-expanded", "false");
    backdrop.remove();
    if (restoreFocus) trigger.focus({ preventScroll: true });
  };
  for (const group of communityLeaderboardMetricGroups) {
    const section = element("section", undefined, "leaderboard-filter-group");
    section.append(element("h3", group.label));
    const options = element("div", undefined, "leaderboard-filter-options");
    options.setAttribute("role", "radiogroup");
    options.setAttribute("aria-label", group.label);
    for (const metric of group.options) {
      const option = element("button", undefined, "leaderboard-filter-option");
      option.type = "button";
      option.setAttribute("role", "radio");
      option.setAttribute("aria-label", metric.label);
      option.setAttribute("aria-checked", String(metric.value === state.metric));
      option.append(
        element("span", metric.icon, "leaderboard-filter-option-icon"),
        element("span", metric.label),
        element("span", metric.value === state.metric ? "✓" : "", "leaderboard-filter-check"),
      );
      if (metric.value === state.metric) {
        option.classList.add("is-selected");
        selectedOption = option;
      }
      option.addEventListener("click", () => {
        dismiss(false);
        state.restoreLeaderboardFilterFocus = true;
        selectLeaderboardMetric(state, revision, metric.value);
      });
      options.append(option);
    }
    section.append(options);
    groups.append(section);
  }
  close.addEventListener("click", () => dismiss());
  backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop) dismiss();
  });
  dialog.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      dismiss();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = [close, ...groups.querySelectorAll("button")];
    const first = focusable[0];
    const last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
  dialog.append(header, groups);
  backdrop.append(dialog);
  shell.append(backdrop);
  queueMicrotask(() => (selectedOption || close).focus({ preventScroll: true }));
}

function statMetric(value, label) {
  const metric = element("article", undefined, "pulse-metric");
  metric.append(element("strong", String(value)), element("span", label));
  return metric;
}

function pulseMetricButton(value, label, metricName) {
  const metric = element("button", undefined, "pulse-metric");
  metric.type = "button";
  metric.dataset.pulseMetric = metricName;
  metric.append(element("strong", String(value)), element("span", label));
  return metric;
}

function achievementDetailSheet(state, achievement, originButton) {
  const backdrop = element("section", undefined, "achievement-detail-backdrop");
  const closeSheet = () => {
    state.achievementOpen = false;
    backdrop.remove();
    originButton.classList.remove("is-selected");
    originButton.setAttribute("aria-pressed", "false");
    originButton.focus({ preventScroll: true });
  };
  const progress = achievement.next_level_at === null
    ? 100
    : Math.min(100, Math.round(achievement.current / achievement.next_level_at * 100));
  const dialog = element("article", undefined, "achievement-detail-sheet");
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.setAttribute("aria-labelledby", "achievement-detail-title");
  const handle = element("span", undefined, "achievement-detail-handle");
  handle.setAttribute("aria-hidden", "true");
  const close = element("button", "×", "achievement-detail-close");
  close.type = "button";
  close.setAttribute("aria-label", "Закрыть достижение");
  close.addEventListener("click", closeSheet);
  const detailHeading = element("div", undefined, "achievement-detail-heading");
  const detailTitle = element("strong", `${achievement.icon} ${achievement.title}`);
  detailTitle.id = "achievement-detail-title";
  detailHeading.append(
    detailTitle,
    element("span", achievement.unlocked ? `Уровень ${achievement.level}` : "Пока закрыто"),
  );
  const track = element("span", undefined, "achievement-progress-track");
  const fill = element("span", undefined, "achievement-progress-fill");
  fill.style.setProperty("--achievement-progress", `${progress}%`);
  track.append(fill);
  dialog.append(
    handle,
    close,
    detailHeading,
    element("strong", "Как получить", "achievement-detail-label"),
    element("p", achievement.hint, "muted"),
    track,
    element(
      "span",
      achievement.next_level_at === null
        ? "Максимальный уровень"
        : `${achievement.current} из ${achievement.next_level_at}`,
      "achievement-progress-copy",
    ),
  );
  backdrop.append(dialog);
  backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop) closeSheet();
  });
  backdrop.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeSheet();
  });
  let touchStartY = null;
  dialog.addEventListener("touchstart", (event) => {
    touchStartY = event.touches[0]?.clientY ?? null;
  }, { passive: true });
  dialog.addEventListener("touchend", (event) => {
    const touchEndY = event.changedTouches[0]?.clientY;
    if (touchStartY !== null && touchEndY !== undefined && touchEndY - touchStartY > 60) closeSheet();
    touchStartY = null;
  }, { passive: true });
  queueMicrotask(() => close.focus({ preventScroll: true }));
  return backdrop;
}

function pulseDetails(state, revision) {
  const pulse = state.pulses[state.period];
  if (!pulse) return element("p", "Статистика пока недоступна.", "status muted");
  const trackingStarted = new Date(pulse.tracking_started_at);
  const calculatedAt = new Date(pulse.calculated_at);
  const trackingAnniversary = new Date(trackingStarted);
  trackingAnniversary.setUTCFullYear(trackingAnniversary.getUTCFullYear() + 1);
  const allTimeYearly = state.period === "all" && calculatedAt > trackingAnniversary;
  const periodPresentation = {
    week: ["Моя неделя", "7 дней", "дням"],
    month: ["Мой месяц", "30 дней", "дням"],
    year: ["Мой год", "12 месяцев", "месяцам"],
    all: [
      "Всё время",
      `с ${new Date(pulse.tracking_started_at).toLocaleDateString("ru-RU")}`,
      allTimeYearly ? "годам" : "месяцам",
    ],
  }[state.period];
  const pulseAchievements = pulse.achievements.map((progress) => ({
    ...(communityAchievementCatalog.find((item) => item.code === progress.code) || {
      code: progress.code,
      icon: "◈",
      title: progress.code,
      hint: "Продолжайте участвовать в жизни сообщества.",
    }),
    ...progress,
  }));
  const fragment = document.createDocumentFragment();
  const card = element("section", undefined, "pulse-card");
  const eyebrow = element("div", undefined, "pulse-card-eyebrow");
  eyebrow.append(element("strong", periodPresentation[0]), element("span", periodPresentation[1]));
  const metrics = element("div", undefined, "pulse-metrics");
  metrics.setAttribute("role", "group");
  metrics.setAttribute("aria-label", "Показатель активности");
  const metricButtons = {
    messages: pulseMetricButton(pulse.summary.messages, "сообщений", "messages"),
    received: pulseMetricButton(pulse.summary.reactions_received, "получено реакций", "received"),
    given: pulseMetricButton(pulse.summary.reactions_given, "поставлено реакций", "given"),
  };
  metrics.append(metricButtons.messages, metricButtons.received, metricButtons.given);

  const visualPanel = element("section", undefined, "pulse-visual-panel");
  visualPanel.setAttribute("aria-live", "polite");
  const renderActivityChart = (metricName) => {
    const metricPresentation = {
      messages: ["Сообщения", "messages"],
      received: ["Полученные реакции", "reactions_received"],
      given: ["Поставленные реакции", "reactions_given"],
    }[metricName];
    const sectionLabel = `${metricPresentation[0]} по ${periodPresentation[2]}`;
    if (!pulse.series.length) {
      return [
        element("strong", sectionLabel, "pulse-section-label"),
        element("p", "График пока недоступен.", "pulse-chart-empty muted"),
      ];
    }
    const metricKey = metricPresentation[1];
    const maximum = Math.max(...pulse.series.map((item) => item[metricKey]), 1);
    const chart = element("div", undefined, `pulse-chart pulse-chart-${state.period}`);
    chart.setAttribute("role", "img");
    chart.style.setProperty("--pulse-columns", String(pulse.series.length));
    const chartValues = [];
    for (const item of pulse.series) {
      const column = element("span", undefined, "pulse-chart-column");
      const bucketDate = new Date(`${item.bucket_start}T00:00:00Z`);
      const value = item[metricKey];
      if (value > 0) {
        const bar = element("span", undefined, "pulse-chart-bar");
        bar.style.setProperty("--pulse-bar-height", `${Math.max(12, Math.round(value / maximum * 100))}%`);
        bar.setAttribute("title", String(value));
        column.append(bar);
      } else {
        column.classList.add("is-zero");
        const zero = element("span", "—", "pulse-chart-zero");
        zero.setAttribute("aria-hidden", "true");
        column.append(zero);
      }
      chartValues.push(String(value));
      const label = state.period === "week"
        ? bucketDate.toLocaleDateString("ru-RU", { weekday: "short", timeZone: "UTC" }).slice(0, 2)
        : state.period === "year" || (state.period === "all" && !allTimeYearly)
          ? bucketDate.toLocaleDateString("ru-RU", { month: "short", timeZone: "UTC" }).slice(0, 1)
          : state.period === "all"
            ? String(bucketDate.getUTCFullYear())
          : "";
      if (label) column.append(element("span", label, "pulse-chart-label"));
      chart.append(column);
    }
    chart.setAttribute("aria-label", `${sectionLabel}: ${chartValues.join(", ")}`);
    return [element("strong", sectionLabel, "pulse-section-label"), chart];
  };
  const renderPulseMetric = (metricName) => {
    const selected = Object.hasOwn(metricButtons, metricName) ? metricName : "messages";
    state.pulseMetric = selected;
    for (const [name, button] of Object.entries(metricButtons)) {
      button.setAttribute("aria-pressed", String(name === selected));
    }
    const content = element("div", undefined, "pulse-visual-content");
    content.append(...renderActivityChart(selected));
    visualPanel.setAttribute("aria-label", content.querySelector(".pulse-section-label")?.textContent || "График активности");
    visualPanel.replaceChildren(content);
  };
  for (const [metricName, button] of Object.entries(metricButtons)) {
    button.addEventListener("click", () => renderPulseMetric(metricName));
  }
  renderPulseMetric(state.pulseMetric);
  card.append(eyebrow, metrics, visualPanel);

  const achievements = element("section", undefined, "achievements-card");
  const achievementsHeading = element("div", undefined, "community-section-heading");
  const headingCopy = element("div");
  headingCopy.append(element("h2", "Достижения"), element("p", "Коллекция будет расти вместе с сообществом.", "muted"));
  achievementsHeading.append(headingCopy);
  const grid = element("div", undefined, "achievement-grid");
  for (const achievement of pulseAchievements) {
    const button = element(
      "button",
      undefined,
      `achievement-tile${achievement.unlocked ? " is-unlocked" : " is-locked"}`,
    );
    button.type = "button";
    button.dataset.achievementCode = achievement.code;
    button.setAttribute("aria-pressed", "false");
    button.setAttribute("aria-label", `${achievement.title}, ${achievement.unlocked ? `уровень ${achievement.level}` : "не открыто"}`);
    button.append(
      element("span", achievement.unlocked ? achievement.icon : "◈", "achievement-icon"),
      element("strong", achievement.title),
      element("span", achievement.unlocked ? `Ур. ${achievement.level}` : "Закрыто", "achievement-level"),
    );
    button.addEventListener("click", () => {
      state.selectedAchievement = achievement.code;
      state.achievementOpen = true;
      button.classList.add("is-selected");
      button.setAttribute("aria-pressed", "true");
      content.querySelector(".achievement-detail-backdrop")?.remove();
      content.append(achievementDetailSheet(state, achievement, button));
    });
    grid.append(button);
  }
  achievements.append(achievementsHeading, grid);
  fragment.append(card);
  if (
    pulse.summary.messages === 0
    && pulse.summary.reactions_given === 0
    && pulse.summary.reactions_received === 0
  ) {
    fragment.append(
      element(
        "p",
        `Сбор начался ${new Date(pulse.tracking_started_at).toLocaleDateString("ru-RU")}. Новая активность появится здесь автоматически.`,
        "status muted",
      ),
    );
  }
  fragment.append(achievements);
  return fragment;
}

function memberListDetails(items) {
  if (!items.length) return element("p", "Участники не найдены.", "status muted");
  const list = element("ul", undefined, "member-list");
  for (const member of items) {
    const row = element("li");
    const button = element(
      "button",
      undefined,
      `member-row${member.member_id === currentMemberId ? " is-current" : ""}`,
    );
    button.type = "button";
    const copy = element("span", undefined, "member-row-copy");
    const identity = element("span", undefined, "member-row-identity");
    identity.append(
      element("strong", member.display_name, "member-row-name"),
      element("span", `Уровень ${member.level_number}`, "level-badge"),
    );
    const metadata = [...(member.skill_tags || []).slice(0, 2), member.city]
      .filter(Boolean).slice(0, 3).join(" · ");
    copy.append(identity);
    if (metadata) copy.append(element("span", metadata, "member-row-metadata"));
    const stats = element("span", undefined, "member-row-stats");
    stats.append(element("span", `Карма ${member.karma.score}`));
    copy.append(stats);
    button.append(
      personAvatar(member, { size: "small" }),
      copy,
      element("span", "›", "member-chevron"),
    );
    button.addEventListener("click", () => showMemberProfile(member.member_id));
    row.append(button);
    list.append(row);
  }
  return list;
}

function showParticipantsState(state, revision) {
  if (revision !== screenRevision) return;
  setNavigation("participants", false);
  back.classList.add("hidden");
  title.textContent = "Комьюнити";
  const boundary = element("section", undefined, "state-view participants-view");
  boundary.dataset.screenId = state.view === "leaderboard" ? "P05" : state.view === "pulse" ? "P08" : "P01";
  boundary.dataset.uiEngine = "concept-05";
  boundary.dataset.state = state.loading ? "loading" : state.error ? "error" : "content";
  const tabs = element("div", undefined, "segmented participants-tabs");
  tabs.setAttribute("aria-label", "Раздел сообщества");
  const membersTab = element("button", "Люди");
  const pulseTab = element("button", "Пульс");
  const leaderboardTab = element("button", "Лидерборд");
  membersTab.type = pulseTab.type = leaderboardTab.type = "button";
  leaderboardTab.dataset.transitionId = "PE-057";
  leaderboardTab.dataset.transitionTrigger = "open_leaderboard";
  membersTab.setAttribute("aria-pressed", String(state.view === "members"));
  pulseTab.setAttribute("aria-pressed", String(state.view === "pulse"));
  leaderboardTab.setAttribute("aria-pressed", String(state.view === "leaderboard"));
  membersTab.addEventListener("click", () => switchParticipantsView(state, revision, "members"));
  pulseTab.addEventListener("click", () => switchParticipantsView(state, revision, "pulse"));
  leaderboardTab.addEventListener(
    "click",
    () => switchParticipantsView(state, revision, "leaderboard"),
  );
  tabs.append(membersTab, pulseTab, leaderboardTab);
  boundary.append(tabs);
  if (state.view === "members") {
    const search = element("form", undefined, "participant-search");
    search.setAttribute("role", "search");
    const input = element("input");
    input.type = "search";
    input.placeholder = "Найти участника";
    input.setAttribute("aria-label", "Найти участника");
    input.value = state.query;
    search.addEventListener("submit", (event) => {
      event.preventDefault();
      state.query = input.value.trim();
      void loadMembers(state, revision);
    });
    search.append(searchIcon(), input);
    boundary.append(search);
  } else {
    const periods = element("div", undefined, "segmented period-tabs");
    periods.setAttribute("aria-label", "Период статистики");
    const achievementPeriodLocked = state.view === "leaderboard"
      && state.metric.startsWith("achievement:");
    for (const [period, label] of communityStatPeriods) {
      const button = element("button", label);
      button.type = "button";
      button.setAttribute("aria-pressed", String(state.period === period));
      button.disabled = achievementPeriodLocked && period !== "all";
      button.addEventListener("click", () => selectCommunityPeriod(state, revision, period));
      periods.append(button);
    }
    boundary.append(periods);
    if (state.view === "leaderboard") {
      const selectedMetric = communityLeaderboardMetrics.find((metric) => metric.value === state.metric)
        || communityLeaderboardMetrics[0];
      state.metric = selectedMetric.value;
      const filter = element("button", undefined, "leaderboard-filter-trigger");
      filter.type = "button";
      filter.setAttribute("aria-label", `Рейтинг по: ${selectedMetric.label}`);
      filter.setAttribute("aria-haspopup", "dialog");
      filter.setAttribute("aria-expanded", "false");
      const filterIcon = element("span", undefined, "leaderboard-filter-trigger-icon");
      filterIcon.append(slidersIcon());
      const filterCopy = element("span", undefined, "leaderboard-filter-trigger-copy");
      filterCopy.append(
        element("span", "Рейтинг по", "leaderboard-filter-trigger-label"),
        element("strong", selectedMetric.label),
      );
      filter.append(filterIcon, filterCopy, element("span", "⌄", "leaderboard-filter-chevron"));
      filter.addEventListener("click", () => showLeaderboardMetricSheet(state, revision, filter));
      boundary.append(filter);
    }
  }
  if (state.loading) {
    boundary.append(element("p", "Загружаем данные…", "status muted"));
  } else if (state.error) {
    const retry = element("button", "Повторить", "secondary");
    retry.type = "button";
    retry.addEventListener("click", () => {
      if (state.view === "leaderboard") void loadParticipantsLeaderboard(state, revision);
      else if (state.view === "pulse") void loadParticipantsPulse(state, revision);
      else void loadMembers(state, revision);
    });
    boundary.append(
      element(
        "p",
        state.view === "members"
          ? "Не удалось загрузить данные."
          : "Статистика временно недоступна. Остальные разделы продолжают работать.",
        "status",
      ),
      retry,
    );
  } else if (state.view === "leaderboard") {
    boundary.append(leaderboardDetails(
      state.leaderboards[`${state.period}:${state.metric}`] || [],
      state.metric,
      state.period,
    ));
  } else if (state.view === "pulse") {
    boundary.append(pulseDetails(state, revision));
  } else {
    boundary.append(memberListDetails(state.members || []));
  }
  replaceContent(boundary);
  if (state.restoreLeaderboardFilterFocus && state.view === "leaderboard") {
    content.querySelector(".leaderboard-filter-trigger")?.focus({ preventScroll: true });
  } else if (state.focusHeading) {
    state.focusHeading = false;
    title.tabIndex = -1;
    title.focus({ preventScroll: true });
  } else if (returnFocusLeaderboardTab && state.view === "members" && !state.loading) {
    returnFocusLeaderboardTab = false;
    leaderboardTab.focus({ preventScroll: true });
  }
}

async function loadMembers(state, revision) {
  const query = state.query ? "&query=" + encodeURIComponent(state.query) : "";
  const path = "/api/v1/members?limit=30" + query;
  const cached = cachedJson(path);
  if (cached) state.members = cached.items;
  state.loading = !cached;
  state.error = false;
  showParticipantsState(state, revision);
  try {
    const page = await getJson(path, (refreshed) => {
      if (revision !== screenRevision || state.view !== "members") return;
      state.members = refreshed.items;
      state.loading = false;
      state.error = false;
      showParticipantsState(state, revision);
    });
    if (revision !== screenRevision) return;
    if (cached) return;
    state.members = page.items;
  } catch {
    if (revision !== screenRevision) return;
    state.error = !cached;
  }
  state.loading = false;
  showParticipantsState(state, revision);
}

async function loadParticipantsLeaderboard(state, revision) {
  const request = ++state.leaderboardRequest;
  const period = state.period;
  const metric = state.metric;
  const key = `${period}:${metric}`;
  const path = `/api/v1/community-stats/leaderboard?limit=30&period=${period}&metric=${encodeURIComponent(metric)}`;
  const cached = cachedJson(path);
  if (cached) state.leaderboards[key] = cached.items;
  state.loading = !cached;
  state.error = false;
  showParticipantsState(state, revision);
  try {
    const page = await getJson(path, (refreshed) => {
      if (
        revision !== screenRevision
        || request !== state.leaderboardRequest
        || state.period !== period
        || state.metric !== metric
      ) return;
      state.leaderboards[key] = refreshed.items;
      state.loading = false;
      state.error = false;
      showParticipantsState(state, revision);
    });
    if (revision !== screenRevision || request !== state.leaderboardRequest) return;
    if (cached) return;
    state.leaderboards[key] = page.items;
  } catch {
    if (revision !== screenRevision || request !== state.leaderboardRequest) return;
    state.error = !cached;
  }
  state.loading = false;
  showParticipantsState(state, revision);
}

async function loadParticipantsPulse(state, revision) {
  const request = ++state.pulseRequest;
  const period = state.period;
  const path = `/api/v1/community-stats/pulse?period=${period}`;
  const cached = cachedJson(path);
  if (cached) state.pulses[period] = cached;
  state.loading = !cached;
  state.error = false;
  showParticipantsState(state, revision);
  try {
    const pulse = await getJson(path, (refreshed) => {
      if (
        revision !== screenRevision
        || request !== state.pulseRequest
        || state.period !== period
        || state.view !== "pulse"
      ) return;
      state.pulses[period] = refreshed;
      state.loading = false;
      state.error = false;
      showParticipantsState(state, revision);
    });
    if (revision !== screenRevision || request !== state.pulseRequest) return;
    if (!cached) state.pulses[period] = pulse;
  } catch {
    if (revision !== screenRevision || request !== state.pulseRequest) return;
    state.error = !cached;
  }
  state.loading = false;
  showParticipantsState(state, revision);
}

function selectCommunityPeriod(state, revision, period) {
  if (state.view === "leaderboard" && state.metric.startsWith("achievement:") && period !== "all") return;
  if (state.period === period) return;
  state.restoreLeaderboardFilterFocus = false;
  state.period = period;
  state.activityPeriod = period;
  state.achievementOpen = false;
  state.error = false;
  history.replaceState(
    { screen: "participants", view: state.view, period, metric: state.metric },
    "",
    presentationLocationFor(state.view === "leaderboard" ? "P05" : "P08"),
  );
  if (
    state.view === "leaderboard"
    && state.leaderboards[`${period}:${state.metric}`] === undefined
  ) void loadParticipantsLeaderboard(state, revision);
  else if (state.view === "pulse" && state.pulses[period] === undefined) {
    void loadParticipantsPulse(state, revision);
  }
  else {
    state.leaderboardRequest += 1;
    state.loading = false;
    showParticipantsState(state, revision);
  }
}

function selectLeaderboardMetric(state, revision, metric) {
  if (state.metric === metric) return;
  const wasAchievementMetric = state.metric.startsWith("achievement:");
  const isAchievementMetric = metric.startsWith("achievement:");
  if (isAchievementMetric && !wasAchievementMetric) {
    state.activityPeriod = state.period;
    state.period = "all";
  } else if (!isAchievementMetric && wasAchievementMetric) {
    state.period = state.activityPeriod || "week";
  }
  state.metric = metric;
  history.replaceState(
    { screen: "participants", view: state.view, period: state.period, metric },
    "",
    presentationLocationFor("P05"),
  );
  if (state.leaderboards[`${state.period}:${state.metric}`] === undefined) {
    void loadParticipantsLeaderboard(state, revision);
  }
  else {
    state.leaderboardRequest += 1;
    state.loading = false;
    showParticipantsState(state, revision);
  }
}

function switchParticipantsView(state, revision, view) {
  state.restoreLeaderboardFilterFocus = false;
  const previousView = state.view;
  if (view === "leaderboard" && state.metric.startsWith("achievement:")) {
    if (state.period !== "all") state.activityPeriod = state.period;
    state.period = "all";
  } else if (view === "pulse" && previousView === "leaderboard" && state.metric.startsWith("achievement:")) {
    state.period = state.activityPeriod || "week";
  }
  state.view = view;
  if (view !== "pulse") state.achievementOpen = false;
  state.error = false;
  state.focusHeading = view !== "members";
  history.replaceState(
    { screen: "participants", view, period: state.period, metric: state.metric },
    "",
    presentationLocationFor(view === "leaderboard" ? "P05" : view === "pulse" ? "P08" : "P01"),
  );
  if (
    view === "leaderboard"
    && state.leaderboards[`${state.period}:${state.metric}`] === undefined
  ) {
    void loadParticipantsLeaderboard(state, revision);
  } else if (view === "pulse" && state.pulses[state.period] === undefined) {
    void loadParticipantsPulse(state, revision);
  } else if (view === "members" && state.members === null) {
    void loadMembers(state, revision);
  } else {
    showParticipantsState(state, revision);
  }
}

function loadParticipants(view = "members", period = "week", metric = "experience") {
  const revision = ++screenRevision;
  const achievementMetric = metric.startsWith("achievement:");
  const state = {
    view,
    query: "",
    members: null,
    period: achievementMetric && view === "leaderboard" ? "all" : period,
    activityPeriod: achievementMetric ? "week" : period,
    metric,
    pulseMetric: "messages",
    selectedAchievement: "speaker",
    achievementOpen: false,
    pulses: {},
    pulseRequest: 0,
    leaderboards: {},
    leaderboardRequest: 0,
    loading: false,
    error: false,
  };
  switchParticipantsView(state, revision, view);
}

function memberActivityDetails(pulse) {
  const activity = element("section", undefined, "profile-card member-activity-card");
  const heading = element("div", undefined, "community-section-heading");
  heading.append(element("h3", "Активность за неделю"));
  const metrics = element("div", undefined, "pulse-metrics compact");
  metrics.append(
    statMetric(pulse.summary.messages, "сообщений"),
    statMetric(pulse.summary.reactions_received, "получено реакций"),
    statMetric(pulse.summary.reactions_given, "поставлено реакций"),
  );
  const progress = pulse.achievements.find((item) => item.unlocked && item.code === "magnet")
    || pulse.achievements.find((item) => item.unlocked);
  activity.append(heading, metrics);
  if (progress) {
    const definition = communityAchievementCatalog.find((item) => item.code === progress.code);
    const highlight = element("div", undefined, "member-achievement-highlight");
    highlight.append(
      element("span", definition?.icon || "◈", "achievement-icon"),
      element("span", `${definition?.title || progress.code} · ур. ${progress.level}`),
    );
    activity.append(highlight);
  }
  return activity;
}

function safeMemberDetails(member, pulse = null) {
  const card = element("article", undefined, "foreign-profile");
  const identity = element("section", undefined, "profile-card profile-identity-card");
  const copy = element("div", undefined, "identity-copy");
  copy.append(element("h2", member.display_name));
  if (/^[A-Za-z0-9_]{5,32}$/.test(member.telegram_username || "")) {
    const username = element("button", `@${member.telegram_username} ↗`, "foreign-username");
    username.type = "button";
    username.addEventListener("click", () => openPublicUrl(`https://t.me/${member.telegram_username}`, { telegram: true }));
    copy.append(username);
  }
  copy.append(element("p", [member.city, `Уровень ${member.level_number}`].filter(Boolean).join(" · "), "muted"));
  identity.append(personAvatar(member), copy);
  const metrics = element("div", undefined, "metric-grid foreign-metrics");
  for (const [value, label] of [[member.experience_total, "Опыт"], [member.karma.score, "Карма"]]) {
    const metric = element("article", undefined, "metric-card");
    metric.append(element("strong", valueOrDash(value)), element("span", label));
    metrics.append(metric);
  }
  card.append(identity, metrics);
  if (member.short_bio) {
    const bio = element("section", undefined, "profile-card foreign-bio-card");
    bio.append(element("h3", "О себе"), element("p", member.short_bio));
    card.append(bio);
  }
  if (member.skill_tags?.length) {
    const skills = element("section", undefined, "profile-card profile-content-card");
    skills.append(element("h3", "НАВЫКИ", "section-label"));
    const chips = element("div", undefined, "profile-chips");
    member.skill_tags.forEach((item) => chips.append(element("span", item)));
    skills.append(chips);
    card.append(skills);
  }
  if (member.profile_links?.length) {
    const links = element("section", undefined, "profile-links-block");
    links.append(element("h3", "Ссылки"));
    member.profile_links.forEach((link) => links.append(publicLinkRow(link)));
    card.append(links);
  }
  if (pulse) card.append(memberActivityDetails(pulse));
  return card;
}

async function karmaCommand(memberId, draft, action, body) {
  draft.operationKey ||= newOperationKey();
  const result = await submissionRequest(
    "/api/v1/members/" + encodeURIComponent(memberId) + "/karma-vote",
    "POST",
    draft.operationKey,
    { action, ...body },
  );
  draft.operationKey = null;
  draft.revision = result.revision;
  return result;
}

function karmaForm(state, revision) {
  const draft = state.karma ||= {
    stage: "begin",
    revision: null,
    operationKey: null,
    value: "1",
    comment: "",
    confirmed: false,
    refreshError: false,
  };
  const form = element("form", undefined, "task-form");
  form.append(element("h3", "Оценить взаимодействие"));
  const status = element("p", "", "status hidden");
  status.setAttribute("aria-live", "polite");
  if (draft.confirmed) {
    status.className = "status success";
    status.textContent = draft.refreshError
      ? "Оценка сохранена. Не удалось обновить показатели."
      : "Оценка сохранена.";
    form.append(status);
    if (draft.refreshError) {
      const retry = element("button", "Повторить обновление", "primary");
      retry.type = "button";
      retry.addEventListener("click", async () => {
        retry.disabled = true;
        try {
          state.member = await getJson(
            "/api/v1/members/" + encodeURIComponent(state.member.member_id),
          );
          if (revision !== screenRevision) return;
          state.karma = null;
          state.message = "Оценка сохранена.";
          showMemberState(state, revision);
        } catch {
          retry.disabled = false;
        }
      });
      form.append(retry);
    }
    return form;
  }
  const valueLabel = element("label", "Оценка");
  const value = element("select");
  value.append(new Option("+1 · положительно", "1"));
  value.append(new Option("0 · нейтрально", "0"));
  value.append(new Option("−1 · отрицательно", "-1"));
  value.value = draft.value;
  valueLabel.append(value);
  const commentLabel = element("label", "Комментарий (10–300 символов)");
  const comment = element("textarea");
  comment.required = true;
  comment.minLength = 10;
  comment.maxLength = 300;
  comment.value = draft.comment;
  commentLabel.append(comment);
  const submit = element("button", "Подтвердить оценку", "primary");
  submit.type = "submit";
  markTransition(submit, "PE-059", "authoritative_karma_success");
  const resetPendingAction = () => {
    draft.stage = "begin";
    draft.revision = null;
    draft.operationKey = null;
  };
  value.addEventListener("change", () => {
    draft.value = value.value;
    resetPendingAction();
  });
  comment.addEventListener("input", () => {
    draft.comment = comment.value;
    resetPendingAction();
  });
  const saveKarma = async ({ confirm, edit, status: actionStatus }) => {
    confirm.disabled = true;
    if (edit) edit.disabled = true;
    actionStatus.className = "status";
    actionStatus.textContent = "Сохраняем оценку…";
    try {
      if (draft.stage === "begin") {
        await karmaCommand(state.member.member_id, draft, "begin", {});
        if (revision !== screenRevision) return;
        draft.stage = "save_value";
      }
      if (draft.stage === "save_value") {
        await karmaCommand(state.member.member_id, draft, "save_value", {
          expected_revision: draft.revision,
          value: Number(draft.value),
        });
        if (revision !== screenRevision) return;
        draft.stage = "save_comment";
      }
      if (draft.stage === "save_comment") {
        await karmaCommand(state.member.member_id, draft, "save_comment", {
          expected_revision: draft.revision,
          comment: draft.comment,
        });
        if (revision !== screenRevision) return;
        draft.stage = "confirm";
      }
      await karmaCommand(state.member.member_id, draft, "confirm", {
        expected_revision: draft.revision,
      });
      draft.comment = "";
      comment.value = "";
      draft.confirmed = true;
      if (revision !== screenRevision) return;
      try {
        state.member = await getJson(
          "/api/v1/members/" + encodeURIComponent(state.member.member_id),
        );
        if (revision !== screenRevision) return;
        state.karma = null;
        state.message = "Оценка сохранена.";
      } catch {
        draft.refreshError = true;
      }
      title.textContent = "Карма сохранена";
      setHeaderControl("back", { screenLabel: "Карма сохранена", hideTitle: true });
      history.replaceState(
        { screen: "member-karma-success", memberId: state.member.member_id },
        "",
        presentationLocationFor("P04", state.member.member_id),
      );
      const done = element("button", "К профилю", "primary");
      done.type = "button";
      done.addEventListener("click", () => history.back());
      replaceContent(connectedBoundary("P04", "success", element("p", "Оценка сохранена.", "status success"), done));
    } catch (error) {
      if (revision !== screenRevision) return;
      if (!retryableSubmissionError(error)) resetPendingAction();
      actionStatus.textContent = error?.status === 422
        ? "Комментарий должен содержать от 10 до 300 символов."
        : error?.status === 409
          ? draft.stage === "begin"
            ? "Оценка сейчас недоступна. Повторите попытку."
            : "Оценка изменилась в другом окне. Вернитесь к редактированию и повторите."
          : "Оценка недоступна или не удалось сохранить. Повторите попытку.";
      confirm.disabled = false;
      if (edit) edit.disabled = false;
    }
  };
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    draft.value = value.value;
    draft.comment = comment.value;
    showActionConfirmation({
      screenId: "P03",
      headingText: "Подтвердить оценку",
      description: `${value.options[value.selectedIndex].text}. ${comment.value}`,
      confirmLabel: "Сохранить оценку",
      transitionId: "PE-059",
      transitionTrigger: "authoritative_karma_success",
      onEdit: () => openKarmaEditor(state, revision, false),
      hideHeading: true,
      showEdit: false,
      onBack: () => openKarmaEditor(state, revision, false),
      onConfirm: saveKarma,
    });
  });
  form.append(valueLabel, commentLabel, status, submit);
  return form;
}

function openKarmaEditor(state, revision, push = true) {
  if (revision !== screenRevision || !state.member) return;
  const location = presentationLocationFor("P03", state.member.member_id);
  const nextState = { screen: "member-karma", memberId: state.member.member_id };
  if (push) history.pushState(nextState, "", location);
  else history.replaceState(nextState, "", location);
  setNavigation("", true);
  title.textContent = "Оценка кармы";
  setHeaderControl("back", { screenLabel: "Оценка кармы", hideTitle: true });
  replaceContent(connectedBoundary("P03", "content", karmaForm(state, revision)));
  content.querySelector("select")?.focus({ preventScroll: true });
}

function showMemberState(state, revision) {
  if (revision !== screenRevision) return;
  if (state.error) {
    return replaceContent(element("p", "Профиль участника недоступен.", "status"));
  }
  if (!state.member) {
    return replaceContent(element("p", "Загружаем профиль…", "status muted"));
  }
  const details = safeMemberDetails(state.member, state.pulse);
  const nodes = [details];
  if (state.message) nodes.push(element("p", state.message, "status success"));
  if (state.member.can_rate_karma) {
    const rate = element("button", "Оценить карму", "primary");
    rate.type = "button";
    rate.addEventListener("click", () => openKarmaEditor(state, revision));
    details.querySelector(".foreign-metrics")?.after(rate);
  }
  replaceContent(connectedBoundary("P02", "content", ...nodes));
}

async function showMemberProfile(memberId, push = true) {
  const revision = ++screenRevision;
  const state = { member: null, pulse: null, error: false, karma: null, message: "" };
  if (push) history.pushState({ screen: "member-profile", memberId }, "", `#/members/${encodeURIComponent(memberId)}`);
  activeProfileState = null;
  memberProfileHasInternalHistory = push;
  setNavigation("", true);
  title.textContent = "Профиль участника";
  setHeaderControl("back", {
    label: "Назад к участникам",
    screenLabel: "Профиль участника",
    hideTitle: true,
  });
  showMemberState(state, revision);
  back.focus({ preventScroll: true });
  try {
    const [member, pulse] = await Promise.all([
      getJson("/api/v1/members/" + encodeURIComponent(memberId)),
      getJson(
        `/api/v1/community-stats/pulse?period=week&member_id=${encodeURIComponent(memberId)}`,
      ).catch(() => null),
    ]);
    state.member = member;
    state.pulse = pulse;
  } catch {
    state.error = true;
  }
  showMemberState(state, revision);
}

function showProfileState(state, revision) {
  if (revision !== screenRevision) return;
  setNavigation(state.route === "/profile" ? "profile" : "", state.route !== "/profile");
  activeProfileState = state;
  if (state.route === "/profile") {
    setHeaderControl("back", {
      label: "Назад в параметры",
      screenLabel: "Профиль",
      hideTitle: true,
    });
  } else {
    back.classList.toggle("hidden", state.route === "/profile" && !state.fromSettings);
  }
  if (!state.profile) {
    replaceContent(element("p", state.profileError ? "Не удалось загрузить профиль." : "Загружаем профиль…", "status"));
    return;
  }
  let node;
  let headingText = "Профиль";
  const editor = state.route.match(/^\/profile\/edit\/(name|city|bio|skills)$/);
  const linkEdit = state.route.match(/^\/profile\/links\/([0-9a-f-]{36})$/i);
  const linkDelete = state.route.match(/^\/profile\/links\/([0-9a-f-]{36})\/delete$/i);
  const modalOpen = Boolean(linkDelete);
  if (linkDelete && !state.deleteOrigin) {
    sessionStorage.setItem("profileReturnFocus", `[data-link-id="${linkDelete[1]}"]`);
  }
  title.inert = modalOpen;
  back.disabled = false;
  if (editor) {
    headingText = editor[1] === "skills" ? "Навыки" : editorConfigs[editor[1]].title;
    node = editor[1] === "skills" ? profileSkillsEditor(state, revision) : profileTextEditor(state, revision, editor[1]);
  } else if (state.route === "/profile/links") {
    headingText = "Мои ссылки";
    node = profileLinksList(state, revision);
  } else if (state.route === "/profile/links/new") {
    headingText = "Новая ссылка";
    node = profileLinkEditor(state, revision);
  } else if (linkDelete) {
    const link = state.profile.me.profile_links.find((item) => item.id === linkDelete[1]);
    headingText = link?.label || "Удалить ссылку";
    node = profileDeleteConfirm(state, revision, linkDelete[1]);
  } else if (linkEdit) {
    const link = state.profile.me.profile_links.find((item) => item.id === linkEdit[1]);
    headingText = link?.label || "Изменить ссылку";
    node = profileLinkEditor(state, revision, linkEdit[1]);
  } else {
    state.route = "/profile";
    node = ownProfileOverview(state, revision);
  }
  title.textContent = headingText;
  if (titlelessProfileRoutes.has(state.route)) {
    setHeaderControl("back", { screenLabel: headingText, hideTitle: true });
  }
  replaceContent(node);
  if (state.returnFocus) {
    const selector = state.returnFocus;
    queueMicrotask(() => content.querySelector(selector)?.focus({ preventScroll: true }));
  }
}

async function loadOwnProfile(state, revision) {
  state.profileError = false;
  if (!state.profile) showProfileState(state, revision);
  try {
    const me = await getJson("/api/v1/me", (refreshed) => {
      if (revision !== screenRevision || !state.profile) return;
      state.profile = { ...state.profile, me: refreshed };
      showProfileState(state, revision);
    });
    if (revision !== screenRevision) return;
    const memberPath = "/api/v1/members/" + encodeURIComponent(me.member_id);
    const member = await getJson(memberPath, (refreshed) => {
      if (revision !== screenRevision || !state.profile) return;
      state.profile = { ...state.profile, member: refreshed };
      showProfileState(state, revision);
    });
    if (revision !== screenRevision) return;
    state.profile = { me, member };
  } catch {
    if (revision !== screenRevision) return;
    state.profileError = !state.profile;
  }
  showProfileState(state, revision);
  queueMicrotask(() => { state.returnFocus = null; });
}

function loadProfile(push = true) {
  const revision = ++screenRevision;
  const route = /^#\/profile(?:\/.*)?$/.test(location.hash) ? location.hash.slice(1) : "/profile";
  const fromSettings = push
    ? history.state?.screen === "settings"
    : history.state?.returnToSettings === true;
  const cachedMe = cachedJson("/api/v1/me");
  const cachedMember = cachedMe
    ? cachedJson("/api/v1/members/" + encodeURIComponent(cachedMe.member_id))
    : null;
  const storedReturnFocus = sessionStorage.getItem("profileReturnFocus");
  sessionStorage.removeItem("profileReturnFocus");
  const state = {
    profile: cachedMe && cachedMember ? { me: cachedMe, member: cachedMember } : null,
    profileError: false,
    route,
    draft: null,
    fromSettings,
    closeHistoryDelta: push && fromSettings
      ? 1
      : Number(history.state?.profileCloseDelta || 0),
    returnFocus: history.state?.profileReturnFocus || storedReturnFocus || null,
  };
  activeProfileState = state;
  returnFocusProfile = true;
  const profileHistory = {
    screen: "profile",
    route,
    returnToSettings: fromSettings,
    profileCloseDelta: state.closeHistoryDelta,
  };
  if (push) history.pushState(profileHistory, "", "#/profile");
  else history.replaceState(profileHistory, "", `#${route}`);
  showProfileState(state, revision);
  void loadOwnProfile(state, revision);
}

const themePresetLabels = Object.freeze({ acid: "Кислота", neon: "Неон" });
const themeModeLabels = Object.freeze({
  system: "Как в Telegram",
  light: "Светлый",
  dark: "Тёмный",
});

const themeSelectionLabel = () => (
  `${themePresetLabels[getPreviewThemePreset()]} · ${themeModeLabels[getPreviewThemePreference()]}`
);

function updateThemeSelection({ preset, preference }) {
  applyThemePreset(preset);
  applyPreviewTheme(preference);
  const url = new URL(location.href);
  url.searchParams.set("preset", preset);
  url.searchParams.set("theme", preference);
  history.replaceState({ ...history.state, preset, theme: preference }, "", url);
}

function showThemePicker(trigger, summary) {
  shell.querySelector(".theme-picker-backdrop")?.remove();
  const backdrop = element("section", undefined, "theme-picker-backdrop");
  const dialog = element("div", undefined, "theme-picker-sheet");
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.setAttribute("aria-labelledby", "theme-picker-title");
  const header = element("div", undefined, "theme-picker-heading");
  const heading = element("h2", "Оформление");
  heading.id = "theme-picker-title";
  const close = element("button", "×", "theme-picker-close");
  close.type = "button";
  close.setAttribute("aria-label", "Закрыть выбор оформления");
  header.append(heading, close);

  const presetGroup = element("div", undefined, "theme-preset-options");
  presetGroup.setAttribute("role", "radiogroup");
  presetGroup.setAttribute("aria-label", "Тема");
  const presetButtons = [];
  for (const preset of ["acid", "neon"]) {
    const option = element("button", undefined, `theme-preset-option theme-preset-${preset}`);
    option.type = "button";
    option.setAttribute("role", "radio");
    option.dataset.themePresetOption = preset;
    const preview = element("span", undefined, "theme-preset-preview");
    preview.setAttribute("aria-hidden", "true");
    preview.append(
      element("span", undefined, "theme-preview-light"),
      element("span", undefined, "theme-preview-dark"),
    );
    option.append(preview, element("strong", themePresetLabels[preset]));
    presetButtons.push(option);
    presetGroup.append(option);
  }

  const modeHeading = element("p", "Режим", "theme-picker-label");
  const modeGroup = element("div", undefined, "theme-mode-options");
  modeGroup.setAttribute("role", "radiogroup");
  modeGroup.setAttribute("aria-label", "Режим темы");
  const modeButtons = [];
  for (const preference of ["system", "light", "dark"]) {
    const option = element("button", themeModeLabels[preference], "theme-mode-option");
    option.type = "button";
    option.setAttribute("role", "radio");
    option.dataset.themeModeOption = preference;
    modeButtons.push(option);
    modeGroup.append(option);
  }

  const refresh = () => {
    const selectedPreset = getPreviewThemePreset();
    const selectedPreference = getPreviewThemePreference();
    for (const option of presetButtons) {
      option.setAttribute("aria-checked", String(option.dataset.themePresetOption === selectedPreset));
    }
    for (const option of modeButtons) {
      option.setAttribute("aria-checked", String(option.dataset.themeModeOption === selectedPreference));
    }
    summary.textContent = themeSelectionLabel();
  };
  for (const option of presetButtons) {
    option.addEventListener("click", () => {
      updateThemeSelection({
        preset: option.dataset.themePresetOption,
        preference: getPreviewThemePreference(),
      });
      refresh();
    });
  }
  for (const option of modeButtons) {
    option.addEventListener("click", () => {
      updateThemeSelection({
        preset: getPreviewThemePreset(),
        preference: option.dataset.themeModeOption,
      });
      refresh();
    });
  }
  refresh();

  const dismiss = () => {
    backdrop.remove();
    trigger.focus({ preventScroll: true });
  };
  close.addEventListener("click", dismiss);
  backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop) dismiss();
  });
  dialog.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      dismiss();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = [close, ...presetButtons, ...modeButtons];
    const first = focusable[0];
    const last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
  dialog.append(header, presetGroup, modeHeading, modeGroup);
  backdrop.append(dialog);
  shell.append(backdrop);
  queueMicrotask(() => (
    presetButtons.find((option) => option.getAttribute("aria-checked") === "true") || close
  ).focus({ preventScroll: true }));
}

function showSettings(push = true) {
  screenRevision += 1;
  activeProfileState = null;
  setNavigation("settings", false);
  title.textContent = "Параметры";
  back.classList.add("hidden");
  if (push) history.pushState({ screen: "settings" }, "", "#/settings");
  else history.replaceState({ screen: "settings" }, "", "#/settings");

  const list = element("section", undefined, "settings-list");
  const profile = element("button", undefined, "settings-row settings-link-row");
  profile.type = "button";
  profile.append(settingsRowIcon("profile"));
  profile.firstChild.classList.add("settings-row-icon");
  const profileCopy = element("span", undefined, "settings-row-copy");
  profileCopy.append(
    element("strong", "Профиль"),
    element("span", "Личные данные, навыки и ссылки"),
  );
  profile.append(profileCopy, element("span", "›", "settings-chevron"));
  profile.addEventListener("click", () => loadProfile());

  const theme = element("button", undefined, "settings-row settings-link-row settings-theme-row");
  theme.type = "button";
  theme.append(settingsRowIcon("appearance"));
  theme.firstChild.classList.add("settings-row-icon");
  const themeCopy = element("span", undefined, "settings-row-copy");
  const themeSummary = element("span", themeSelectionLabel());
  themeCopy.append(
    element("strong", "Оформление"),
    themeSummary,
  );
  theme.append(themeCopy, element("span", "›", "settings-chevron"));
  theme.addEventListener("click", () => showThemePicker(theme, themeSummary));

  const fullscreen = element("div", undefined, "settings-row settings-fullscreen-row");
  fullscreen.append(settingsRowIcon("fullscreen"));
  fullscreen.firstChild.classList.add("settings-row-icon");
  const fullscreenCopy = element("span", undefined, "settings-row-copy");
  fullscreenCopy.append(
    element("strong", "Полноэкранный режим"),
    element("span", "Использовать весь экран Telegram"),
  );
  const fullscreenToggle = element("button", undefined, "settings-switch");
  fullscreenToggle.type = "button";
  fullscreenToggle.setAttribute("role", "switch");
  fullscreenToggle.setAttribute("aria-label", "Полноэкранный режим");
  fullscreenToggle.append(element("span", undefined, "settings-switch-thumb"));
  const updateFullscreenToggle = () => {
    fullscreenToggle.setAttribute("aria-checked", String(getFullscreenPreference()));
  };
  updateFullscreenToggle();
  fullscreenToggle.addEventListener("click", () => {
    setFullscreenPreference(fullscreenToggle.getAttribute("aria-checked") !== "true");
    updateFullscreenToggle();
  });
  fullscreen.append(fullscreenCopy, fullscreenToggle);

  list.append(profile, theme, fullscreen);
  replaceContent(list);
}

function showTaskDetail(task, push = true) {
  screenRevision += 1;
  returnFocusTaskId = task.id;
  setNavigation("", true);
  shell.classList.add("task-detail-screen");
  title.textContent = "Карточка задания";
  setHeaderControl("back", {
    label: "Назад к заданиям",
    screenLabel: "Карточка задания",
    hideTitle: true,
  });
  if (push) history.pushState({ screen: "task", taskId: task.id }, "", presentationLocationFor("T03", task.id));
  const detail = element("article", undefined, "card detail task-detail");
  detail.append(element("h3", task.title, "task-detail-title"));
  const chips = element("div", undefined, "card-chips");
  if (task.category_name) chips.append(element("span", task.category_name, "chip muted-chip"));
  if (task.task_kind) chips.append(element("span", ({ solo: "Личное", group: "Групповое" })[task.task_kind], "chip"));
  chips.append(element("span", ({ online: "Онлайн", offline: "Офлайн", any: "Любой" })[task.format], "chip muted-chip"));
  detail.append(chips);
  const metadata = element("dl", undefined, "task-detail-meta");
  const appendMeta = (label, value) => {
    metadata.append(element("dt", label), element("dd", value));
  };
  appendMeta("Автор", task.author_display_name);
  appendMeta("Срок", formatDate(task.deadline_at));
  appendMeta("Награда", `${task.credit_reward_per_performer} кредитов`);
  appendMeta("Мест", String(task.performer_slots));
  if (task.city) appendMeta("Город", task.city);
  detail.append(metadata);
  const status = element("p", "", "status hidden");
  status.setAttribute("aria-live", "polite");
  const accept = element("button", "Принять задание", "primary");
  accept.type = "button";
  markTransition(accept, "PE-015", "accept_task");
  accept.addEventListener("click", () => {
    history.pushState(
      { screen: "task-accept", taskId: task.id },
      "",
      presentationLocationFor("T03A", task.id),
    );
    showActionConfirmation({
      screenId: "T03A",
      headingText: "Подтвердить принятие",
      description: `${task.title}. Срок: ${formatDate(task.deadline_at)}. Критерии: ${task.completion_criteria}`,
      confirmLabel: "Принять слот",
      transitionId: "PE-024",
      transitionTrigger: "authoritative_accept_success",
      showEdit: false,
      onConfirm: ({ confirm, status: actionStatus }) => {
        void acceptTask(task, confirm, actionStatus);
      },
    });
  });
  detail.append(status, accept, section("Описание", task.description));
  detail.append(section("Критерии выполнения", task.completion_criteria));
  detail.append(section("Как выполнять", task.performer_instructions));
  for (const [key, value] of Object.entries(task.public_input)) {
    detail.append(section(key, String(value)));
  }
  for (const value of Object.values(task.materials)) {
    detail.append(section("Материал", value));
  }
  replaceContent(connectedBoundary("T03", "content", detail));
  back.focus({ preventScroll: true });
}

async function acceptTask(task, button, status) {
  button.disabled = true;
  status.className = "status";
  status.textContent = "Принимаем задание…";
  const operationKey = pendingAcceptKeys.get(task.id) || newOperationKey();
  pendingAcceptKeys.set(task.id, operationKey);
  try {
    const response = await apiFetch(
      "/api/v1/tasks/" + task.id + "/assignments",
      {
        method: "POST",
        headers: { "Idempotency-Key": operationKey },
        credentials: "same-origin",
      },
    );
    const payload = await submissionResponse(response);
    pendingAcceptKeys.delete(task.id);
    history.replaceState(
      {
        screen: "assignment",
        assignmentId: payload.id,
        returnTo: "assignments-taken",
      },
      "",
      presentationLocationFor("M03", payload.id),
    );
    await showAssignmentDetail(payload.id, false);
  } catch (error) {
    status.textContent = error instanceof TypeError
      ? "Сеть недоступна. Повторите попытку — запрос останется тем же."
      : "Задание сейчас недоступно. Вернитесь к заданиям и попробуйте другое.";
    if (!retryableSubmissionError(error)) pendingAcceptKeys.delete(task.id);
    button.disabled = false;
  }
}

const archivedOwnedTaskStatuses = new Set([
  "expired",
  "partially_completed",
  "completed",
  "cancelled",
]);

const compactListDate = (value) => (
  value
    ? memberDateFormatter({ day: "numeric", month: "short" }).format(new Date(value))
    : "без срока"
);

const nextWorkListHeader = ({
  searchLabel,
  query,
  onQuery,
  leadingControl = null,
  trailingControls = null,
}) => {
  const actions = element("div", undefined, "catalog-actions work-list-actions");
  const listBack = element("button", "‹", "secondary catalog-back-button");
  listBack.type = "button";
  listBack.setAttribute("aria-label", "Назад к заданиям");
  listBack.addEventListener("click", () => void loadTaskHome());
  const search = element("label", undefined, "catalog-search");
  const searchInput = element("input");
  searchInput.type = "search";
  searchInput.placeholder = "Название задания";
  searchInput.setAttribute("aria-label", searchLabel);
  searchInput.value = query;
  search.append(searchIcon(), searchInput);
  if (trailingControls) {
    actions.classList.add("has-trailing-controls");
    actions.append(listBack, search, trailingControls);
  } else if (leadingControl) {
    actions.classList.add("has-leading-control");
    actions.append(listBack, leadingControl, search);
  } else {
    actions.append(listBack, search);
  }
  searchInput.addEventListener("input", () => onQuery(searchInput.value));
  return { actions, searchInput };
};

const nextWorkListHeading = (label, count, actionCount = 0) => {
  const headingRow = element("div", undefined, "work-list-heading");
  headingRow.append(
    element("h2", label),
    element("span", String(count), "work-list-count"),
  );
  if (actionCount) {
    headingRow.append(
      element(
        "span",
        `${actionCount} ${actionCount === 1 ? "действие" : "действия"}`,
        "work-list-action-count",
      ),
    );
  }
  return headingRow;
};

const activeTaskFilterCount = (filters) => Object.entries(filters)
  .filter(([key, value]) => key !== "query" && Boolean(value)).length;

const taskFilterButton = (filters, onClick) => {
  const count = activeTaskFilterCount(filters);
  const filter = element("button", undefined, "secondary catalog-filter-button");
  filter.type = "button";
  filter.setAttribute("aria-label", count ? `Фильтры, выбрано: ${count}` : "Фильтры");
  filter.setAttribute("aria-haspopup", "dialog");
  filter.append(slidersIcon());
  if (count) {
    filter.classList.add("is-active");
    filter.append(element("span", String(count), "catalog-filter-count"));
  }
  filter.addEventListener("click", onClick);
  return filter;
};

const assignmentTaskProjection = (assignment) => ({
  ...assignment,
  deadline_at: assignment.deadline_at || assignment.task_deadline_at,
});

const assignmentListDescription = (assignment) => assignment.result_summary || ({
  accepted: "Задание выполняется — результат ещё не отправлен.",
  submitted: "Результат отправлен и ожидает проверки.",
  rejected_pending_dispute: "Нужно принять решение по отклонённому результату.",
  disputed: "Спор открыт и ожидает решения.",
  reviewer_required: "Ожидается независимая проверка.",
}[assignment.assignment_status] || "Откройте задание, чтобы посмотреть текущее состояние.");

const nextAssignmentListCard = (assignment) => {
  const card = element("button", undefined, "card task-card work-task-card");
  card.type = "button";
  const chips = element("div", undefined, "card-chips");
  chips.append(element("span", assignmentStatus(assignment.assignment_status), "chip"));
  chips.append(
    element(
      "span",
      assignment.task_origin === "community" ? "Сообщество" : "От участника",
      "chip muted-chip",
    ),
  );
  const label = element("div", undefined, "task-card-title");
  label.append(element("h3", assignment.task_title), element("span", "›", "chevron"));
  const meta = element("div", undefined, "task-meta");
  meta.append(
    element("span", `Взято ${compactListDate(assignment.accepted_at)}`),
    element("span", `до ${compactListDate(assignment.task_deadline_at)}`),
  );
  card.append(
    chips,
    label,
    element("p", assignmentListDescription(assignment), "muted"),
    meta,
  );
  card.addEventListener("click", () => showAssignmentDetail(assignment.id));
  return card;
};

function showNextTakenAssignments(revision, screenId = "M01") {
  if (revision !== screenRevision) return;
  setNavigation("catalog", false);
  title.textContent = "Что я выполняю";
  back.classList.add("hidden");
  const boundary = connectedBoundary(screenId, assignments.length ? "content" : "empty");
  boundary.dataset.uiEngine = "next-work-list";
  boundary.dataset.template = "list";
  boundary.classList.add("catalog-view", "work-list-view", "taken-tasks-view");
  const results = element("div", undefined, "catalog-results work-list-results");
  const headingRow = nextWorkListHeading("Что я выполняю", assignments.length);
  const updateResults = () => {
    const query = takenTasksQuery.trim().toLocaleLowerCase("ru");
    const visible = assignments.filter((assignment) => {
      const queryMatches = !query
        || assignment.task_title.toLocaleLowerCase("ru").includes(query)
        || assignmentListDescription(assignment).toLocaleLowerCase("ru").includes(query);
      return queryMatches && taskMatchesFilters(
        assignmentTaskProjection(assignment),
        takenTasksFilters,
      );
    });
    const visibleById = new Map(visible.map((assignment) => [assignment.id, assignment]));
    const orderedVisible = sortTaskLikeItems(
      visible.map(assignmentTaskProjection),
      takenTasksSort,
    ).map((projection) => visibleById.get(projection.id));
    boundary.dataset.state = visible.length ? "content" : "empty";
    headingRow.querySelector(".work-list-count").textContent = String(visible.length);
    if (!visible.length) {
      results.replaceChildren(
        element(
          "p",
          query ? "По вашему запросу ничего не найдено." : "Активных заданий пока нет.",
          "compact-empty",
        ),
      );
      return null;
    }
    const list = element("div", undefined, "list");
    let focusTarget = null;
    for (const assignment of orderedVisible) {
      const card = nextAssignmentListCard(assignment);
      if (assignment.id === returnFocusAssignmentId) focusTarget = card;
      list.append(card);
    }
    results.replaceChildren(list);
    return focusTarget;
  };
  const currentSortLabel = catalogSortOptions.find(([, value]) => value === takenTasksSort)?.[0] || "Создано позже";
  const sort = element("button", undefined, "secondary catalog-sort-button work-list-sort-button");
  sort.type = "button";
  sort.setAttribute("aria-label", `Сортировка: ${currentSortLabel}`);
  sort.setAttribute("aria-haspopup", "dialog");
  sort.append(sortIcon());
  sort.classList.toggle("is-active", takenTasksSort !== "created_desc");
  sort.addEventListener("click", () => showCatalogSortSheet(sort, {
    sortOptions: catalogSortOptions,
    selectedSort: takenTasksSort,
    onSelect: (value) => {
      takenTasksSort = value;
      showNextTakenAssignments(screenRevision, screenId);
    },
  }));
  const actionEnd = element("div", undefined, "catalog-actions-end");
  const filter = taskFilterButton(takenTasksFilters, () => showCatalogFilterSheet(filter, {
    filters: takenTasksFilters,
    sourceTasks: assignments.map(assignmentTaskProjection),
    onChange: (value) => { takenTasksFilters = value; },
    refresh: () => showNextTakenAssignments(screenRevision, screenId),
  }));
  actionEnd.append(filter, sort);
  const header = nextWorkListHeader({
    searchLabel: "Поиск в выполняемых заданиях",
    query: takenTasksQuery,
    onQuery: (value) => {
      takenTasksQuery = value;
      updateResults();
    },
    trailingControls: actionEnd,
  });
  boundary.append(header.actions, headingRow, results);
  const focusTarget = updateResults();
  replaceContent(boundary);
  focusTarget?.focus({ preventScroll: true });
  returnFocusAssignmentId = null;
}

function showAssignments(revision = ++screenRevision) {
  if (revision !== screenRevision) return;
  showNextTakenAssignments(revision);
}

function showTakenAssignments() {
  screenRevision += 1;
  history.replaceState({ screen: "assignments-taken" }, "", presentationLocationFor("M02"));
  showNextTakenAssignments(screenRevision, "M02");
}

async function loadAssignments(push = true) {
  const revision = ++screenRevision;
  const path = "/api/v1/assignments?status=active&limit=20";
  const cached = cachedJson(path);
  if (push) history.replaceState({ screen: "assignments" }, "", presentationLocationFor("M01"));
  if (cached) {
    assignments = cached.items;
    showAssignments(revision);
  } else {
    setNavigation("assignments", false);
    title.textContent = "Мои задания";
    back.classList.add("hidden");
    replaceContent(element("p", "Загружаем активные назначения…", "status muted"));
  }
  try {
    const page = await getJson(path, (refreshed) => {
      if (revision !== screenRevision) return;
      assignments = refreshed.items;
      showAssignments(revision);
    });
    if (revision !== screenRevision) return;
    if (cached) return;
    assignments = page.items;
    showAssignments(revision);
  } catch (error) {
    if (revision !== screenRevision || cached) return;
    const retry = element("button", "Повторить", "primary");
    retry.type = "button";
    retry.addEventListener("click", () => loadAssignments(false));
    replaceContent(...assignmentError(error.message, retry));
  }
}

const decisionLabels = {
  full: "Принять полностью",
  partial: "Принять частично",
  reject: "Отклонить",
};

const createdTaskStatus = (value) => ({
  published: "Опубликовано",
  closed_for_new_performers: "Набор закрыт",
  settling: "Завершается",
  expired: "Срок истёк",
  partially_completed: "Частично завершено",
  completed: "Завершено",
  cancelled: "Отменено",
}[value] || value);

function showOwnedTask(task, push = true) {
  if (push) history.pushState({ screen: "owned-task", task }, "", presentationLocationFor("M10", task.id));
  setNavigation("", true);
  const performedArchive = task.archive_role === "performed";
  title.textContent = performedArchive ? "Выполненное задание" : "Созданное задание";
  const returnScope = ownedTaskListScope;
  const returnArchiveRole = ownedArchiveRole;
  setHeaderControl("back", {
    label: returnScope === "archive" ? "Назад в архив" : "Назад к созданным заданиям",
    screenLabel: performedArchive ? "Выполненное задание" : "Созданное задание",
    hideTitle: true,
    onBack: () => {
      const baseLocation = presentationLocationFor("M09");
      const nextLocation = returnScope === "archive"
        ? `${baseLocation}&scope=archive${returnArchiveRole === "performed" ? "&archive_view=performed" : ""}`
        : baseLocation;
      history.replaceState(
        { screen: "created-assignments", scope: returnScope, archiveRole: returnArchiveRole },
        "",
        nextLocation,
      );
      void loadCreatedReviews(false, returnScope, returnArchiveRole);
    },
  });
  const detail = element("article", undefined, "card owned-task-detail");
  const detailHeader = element("header", undefined, "owned-task-header");
  const headingCopy = element("div", undefined, "owned-task-heading-copy");
  headingCopy.append(
    element("span", performedArchive ? "Выполнено вами" : "Создано вами", "owned-task-eyebrow"),
    element("h2", task.title),
  );
  detailHeader.append(
    headingCopy,
    element(
      "span",
      performedArchive ? assignmentStatus(task.performed_status) : createdTaskStatus(task.status),
      "chip owned-task-status-chip",
    ),
  );

  const summary = element("div", undefined, "owned-task-summary");
  const assigneeCount = element("div", undefined, "owned-task-metric");
  assigneeCount.append(
    element("strong", `${task.assignees.length}/${task.performer_slots}`),
    element("span", "Исполнители"),
  );
  const activeDisputes = task.assignees.filter((assignee) => assignee.status === "disputed").length;
  const attention = element("div", undefined, "owned-task-metric");
  attention.append(
    element("strong", String(activeDisputes)),
    element("span", activeDisputes === 1 ? "Открытый спор" : "Открытые споры"),
  );
  if (activeDisputes > 0) attention.classList.add("is-attention");
  summary.append(assigneeCount, attention);
  detail.append(detailHeader, summary);

  const assigneesBlock = element("section", undefined, "owned-task-assignees");
  assigneesBlock.append(element("h3", "Исполнители", "owned-task-section-title"));
  for (const assignee of task.assignees) {
    const assigneeCard = element("div", undefined, "owned-task-assignee");
    const avatar = personAvatar(assignee, { size: "small" });
    const copy = element("div", undefined, "owned-task-assignee-copy");
    copy.append(
      element("strong", assignee.display_name),
      element("span", assignmentStatus(assignee.status)),
    );
    assigneeCard.append(avatar, copy);
    if (assignee.status === "disputed") {
      assigneeCard.classList.add("is-disputed");
      assigneeCard.append(element("span", "Спор", "chip owned-task-dispute-chip"));
    }
    assigneesBlock.append(assigneeCard);
  }
  if (task.assignees.length === 0) {
    assigneesBlock.append(element("p", "Пока никто не взял задание.", "muted owned-task-empty"));
  }
  detail.append(assigneesBlock);
  if (activeDisputes > 0) {
    detail.append(element(
      "p",
      "Спор передан независимому модератору. Автор и исполнитель не могут рассматривать собственное дело.",
      "owned-task-dispute-note",
    ));
  }
  if (!performedArchive && task.cancellation_action) {
    const cancel = element(
      "button",
      task.cancellation_action === "request" ? "Запросить отмену" : "Отменить задание",
      "secondary danger",
    );
    cancel.type = "button";
    cancel.addEventListener("click", () => confirmOwnedTaskCancellation(task));
    detail.append(cancel);
  } else if (task.cancellation_status === "pending") {
    detail.append(element("p", "Запрос на отмену ожидает ответа исполнителей.", "status muted"));
  }
  replaceContent(connectedBoundary("M10", "content", detail));
  back.focus({ preventScroll: true });
}

function confirmOwnedTaskCancellation(task) {
  let operationKey = null;
  showActionConfirmation({
    screenId: "M10",
    headingText: task.cancellation_action === "request" ? "Запросить отмену" : "Отменить задание",
    description: task.cancellation_action === "request"
      ? "Набор новых исполнителей закроется, а текущие получат запрос на отмену."
      : "Задание будет отменено, зарезервированные кредиты вернутся.",
    confirmLabel: task.cancellation_action === "request" ? "Отправить запрос" : "Отменить задание",
    showEdit: false,
    onConfirm: async ({ confirm, edit, status }) => {
      confirm.disabled = true;
      if (edit) edit.disabled = true;
      status.className = "status";
      status.textContent = "Применяем отмену…";
      operationKey ||= newOperationKey();
      try {
        const response = await apiFetch(
          "/api/v1/owned-tasks/" + encodeURIComponent(task.id) + "/cancellation",
          {
            method: "POST",
            headers: { "Idempotency-Key": operationKey },
            credentials: "same-origin",
          },
        );
        const outcome = await submissionResponse(response);
        task.cancellation_action = null;
        task.cancellation_status = outcome.status === "pending" ? "pending" : null;
        task.status = outcome.status === "cancelled" ? "cancelled" : task.status;
        history.replaceState({ screen: "owned-task", task }, "", presentationLocationFor("M10", task.id));
        showOwnedTask(task, false);
        const message = outcome.status === "pending"
          ? "Запрос на отмену отправлен исполнителям."
          : "Задание отменено.";
        content.querySelector(".detail")?.append(element("p", message, "status success"));
      } catch (error) {
        status.textContent = error?.status === 409
          ? "Отмена больше недоступна для текущего состояния задания."
          : "Не удалось применить отмену. Повторите запрос.";
        if (!retryableSubmissionError(error)) operationKey = null;
        confirm.disabled = false;
        if (edit) edit.disabled = false;
      }
    },
  });
}

const nextOwnedTaskListCard = (task) => {
  const card = element("button", undefined, "card task-card work-task-card owned-work-card");
  card.type = "button";
  const chips = element("div", undefined, "card-chips");
  const performed = task.archive_role === "performed";
  const archived = performed || archivedOwnedTaskStatuses.has(task.status);
  chips.append(
    element(
      "span",
      performed ? assignmentStatus(task.performed_status) : createdTaskStatus(task.status),
      archived ? "chip muted-chip" : "chip",
    ),
  );
  if (task.cancellation_status === "pending") {
    chips.append(element("span", "Ждёт ответа на отмену", "chip action-chip"));
  }
  const label = element("div", undefined, "task-card-title");
  label.append(element("h3", task.title), element("span", "›", "chevron"));
  const meta = element("div", undefined, "task-meta");
  meta.append(
    element("span", `${task.assignees.length} из ${task.performer_slots} исполнителей`),
    element("span", `до ${compactListDate(task.deadline_at)}`),
  );
  const description = performed
    ? `Ваш результат: ${assignmentStatus(task.performed_status)}`
    : task.assignees.length
    ? task.assignees.map((assignee) => (
      `${assignee.display_name}: ${assignmentStatus(assignee.status)}`
    )).join(" · ")
    : archived ? "Задание находится в архиве." : "Пока без исполнителя.";
  card.append(chips, label, element("p", description, "muted"), meta);
  card.addEventListener("click", () => {
    returnFocusOwnedTaskId = task.id;
    const screen = content.closest(".screen");
    history.replaceState(
      { ...history.state, scrollTop: screen?.scrollTop || 0 },
      "",
      location.href,
    );
    showOwnedTask(task);
  });
  return card;
};

const nextOwnedReviewListCard = (review) => {
  const card = element("button", undefined, "card task-card work-task-card work-review-card");
  card.type = "button";
  const chips = element("div", undefined, "card-chips");
  chips.append(
    element("span", "Требуется проверка", "chip action-chip"),
    element("span", review.performer_display_name, "chip muted-chip"),
  );
  const label = element("div", undefined, "task-card-title");
  label.append(element("h3", review.task_title), element("span", "›", "chevron"));
  const meta = element("div", undefined, "task-meta");
  meta.append(element("span", `Отправлено ${compactListDate(review.submitted_at)}`));
  if (review.review_deadline_at) {
    meta.append(element("span", `решить до ${compactListDate(review.review_deadline_at)}`));
  }
  card.append(
    chips,
    label,
    element("p", `Исполнитель ${review.performer_display_name} отправил результат.`, "muted"),
    meta,
  );
  card.addEventListener("click", () => showCreatedReview(review.id));
  return card;
};

function showOwnedArchiveFilterSheet(trigger) {
  shell.querySelector(".catalog-sort-backdrop, .catalog-filter-backdrop")?.remove();
  const backdrop = element("section", undefined, "catalog-filter-backdrop");
  const dialog = element("div", undefined, "catalog-filter-sheet");
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.setAttribute("aria-labelledby", "owned-archive-filter-title");
  const header = element("div", undefined, "catalog-sort-heading");
  const filterTitle = element("h2", "Фильтры архива");
  filterTitle.id = "owned-archive-filter-title";
  const close = element("button", "×", "catalog-sort-close");
  close.type = "button";
  close.setAttribute("aria-label", "Закрыть фильтры");
  header.append(filterTitle, close);

  const form = element("form", undefined, "task-form card catalog-filter-form");
  const selectField = (labelText, options, value) => {
    const label = element("label", labelText);
    const select = element("select");
    for (const [optionLabel, optionValue] of options) {
      select.append(new Option(optionLabel, optionValue));
    }
    select.value = value;
    label.append(select);
    return { label, select };
  };
  const statusField = selectField("Статус", [
    ["Любой", ""],
    ["Завершено", "completed"],
    ["Частично завершено", "partially_completed"],
    ["Отменено", "cancelled"],
    ["Срок истёк", "expired"],
  ], ownedArchiveFilters.status);
  const performersField = selectField("Исполнители", [
    ["Неважно", ""],
    ["Есть исполнители", "with"],
    ["Без исполнителей", "without"],
  ], ownedArchiveFilters.performers);
  const archivedLabel = element("label", "Добавлено в архив до");
  const archivedInput = element("input");
  archivedInput.type = "date";
  archivedInput.setAttribute("aria-label", "Добавлено в архив до");
  archivedInput.value = ownedArchiveFilters.archivedUntil;
  archivedLabel.append(
    archivedInput,
    element("span", "Дата завершения, отмены или истечения срока", "profile-helper"),
  );
  const actions = element("div", undefined, "catalog-filter-actions");
  const reset = element("button", "Сбросить", "secondary");
  reset.type = "button";
  const apply = element("button", "Применить", "primary");
  apply.type = "submit";
  actions.append(reset, apply);
  form.append(statusField.label, performersField.label, archivedLabel, actions);

  const dismiss = (restoreFocus = true) => {
    backdrop.remove();
    if (restoreFocus) trigger.focus({ preventScroll: true });
  };
  const refresh = () => {
    dismiss(false);
    showNextCreatedAssignments(screenRevision);
    queueMicrotask(() => content.querySelector(".catalog-filter-button")?.focus({ preventScroll: true }));
  };
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    ownedArchiveFilters = {
      status: statusField.select.value,
      performers: performersField.select.value,
      archivedUntil: archivedInput.value,
    };
    refresh();
  });
  reset.addEventListener("click", () => {
    ownedArchiveFilters = emptyOwnedArchiveFilters();
    refresh();
  });
  close.addEventListener("click", () => dismiss());
  backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop) dismiss();
  });
  dialog.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      dismiss();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = [close, ...form.querySelectorAll("select, input, button")];
    const first = focusable[0];
    const last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
  dialog.append(header, form);
  backdrop.append(dialog);
  shell.append(backdrop);
  queueMicrotask(() => statusField.select.focus({ preventScroll: true }));
}

function showNextCreatedAssignments(revision) {
  if (revision !== screenRevision) return;
  const archiveMode = ownedTaskListScope === "archive";
  const performedArchive = archiveMode && ownedArchiveRole === "performed";
  const scopedTasks = performedArchive
    ? ownedTasks
    : ownedTasks.filter((task) => archivedOwnedTaskStatuses.has(task.status) === archiveMode);
  const scopedReviews = archiveMode ? [] : ownedReviews;
  const scopedTaskById = new Map(scopedTasks.map((task) => [task.id, task]));
  const screenTitle = archiveMode ? "Архив заданий" : "Созданные мной";
  const currentQuery = () => archiveMode ? archivedTasksQuery : createdTasksQuery;
  const currentSort = () => archiveMode ? archivedTasksSort : createdTasksSort;
  const activeArchiveFilterCount = performedArchive
    ? 0
    : Object.values(ownedArchiveFilters).filter(Boolean).length;
  const activeCreatedFilterCount = activeTaskFilterCount(createdTasksFilters);
  setNavigation("catalog", false);
  title.textContent = screenTitle;
  back.classList.add("hidden");
  const boundary = connectedBoundary(
    "M09",
    scopedTasks.length || scopedReviews.length ? "content" : "empty",
  );
  boundary.dataset.uiEngine = "next-work-list";
  boundary.dataset.template = "list";
  boundary.dataset.listScope = ownedTaskListScope;
  boundary.classList.add("catalog-view", "work-list-view", "created-tasks-view");
  const results = element("div", undefined, "catalog-results work-list-results");
  const headingRow = nextWorkListHeading(screenTitle, scopedTasks.length, scopedReviews.length);
  const updateResults = () => {
    const query = currentQuery().trim().toLocaleLowerCase("ru");
    const matchingTasks = scopedTasks.filter((task) => {
      const queryMatches = !query
        || task.title.toLocaleLowerCase("ru").includes(query)
        || task.assignees.some((assignee) => (
          assignee.display_name.toLocaleLowerCase("ru").includes(query)
        ));
      if (!queryMatches) return false;
      if (!archiveMode) return taskMatchesFilters(task, createdTasksFilters);
      if (performedArchive) return true;
      return (
        (!ownedArchiveFilters.status || task.status === ownedArchiveFilters.status)
        && (
          !ownedArchiveFilters.performers
          || (ownedArchiveFilters.performers === "with" && task.assignees.length > 0)
          || (ownedArchiveFilters.performers === "without" && task.assignees.length === 0)
        )
        && (
          !ownedArchiveFilters.archivedUntil
          || (task.archived_at && memberDateKey(task.archived_at) <= ownedArchiveFilters.archivedUntil)
        )
      );
    });
    if (archiveMode) {
      const originalOrder = new Map(scopedTasks.map((task, index) => [task.id, index]));
      const byOriginalOrder = (left, right) => originalOrder.get(left.id) - originalOrder.get(right.id);
      const deadlineValue = (task) => {
        const value = Date.parse(task.deadline_at);
        return Number.isFinite(value) ? value : Number.POSITIVE_INFINITY;
      };
      const archiveValue = (task) => {
        const value = Date.parse(task.archived_at);
        return Number.isFinite(value) ? value : Number.NEGATIVE_INFINITY;
      };
      const comparators = {
        archive_desc: (left, right) => archiveValue(right) - archiveValue(left) || byOriginalOrder(left, right),
        archive_asc: (left, right) => archiveValue(left) - archiveValue(right) || byOriginalOrder(left, right),
        deadline_asc: (left, right) => deadlineValue(left) - deadlineValue(right) || byOriginalOrder(left, right),
        deadline_desc: (left, right) => deadlineValue(right) - deadlineValue(left) || byOriginalOrder(left, right),
      };
      matchingTasks.sort(comparators[currentSort()] || byOriginalOrder);
    } else {
      sortTaskLikeItems(matchingTasks, currentSort());
    }
    const matchingReviews = scopedReviews.filter((review) => (
      (
        !query
        || review.task_title.toLocaleLowerCase("ru").includes(query)
        || review.performer_display_name.toLocaleLowerCase("ru").includes(query)
      )
      && (
        !activeCreatedFilterCount
        || (scopedTaskById.has(review.task_id)
          && taskMatchesFilters(scopedTaskById.get(review.task_id), createdTasksFilters))
      )
    ));
    const hasItems = matchingTasks.length || matchingReviews.length;
    boundary.dataset.state = hasItems ? "content" : "empty";
    headingRow.querySelector(".work-list-count").textContent = String(matchingTasks.length);
    const actionCount = headingRow.querySelector(".work-list-action-count");
    if (actionCount) {
      actionCount.textContent = `${matchingReviews.length} ${matchingReviews.length === 1 ? "действие" : "действия"}`;
      actionCount.classList.toggle("hidden", matchingReviews.length === 0);
    }
    if (!hasItems) {
      results.replaceChildren(
        element(
          "p",
          query
            ? "По вашему запросу ничего не найдено."
            : archiveMode && activeArchiveFilterCount
              ? "По заданным фильтрам ничего не найдено."
              : archiveMode ? "Архив пока пуст." : "Созданных заданий пока нет.",
          "compact-empty",
        ),
      );
      return null;
    }
    const list = element("div", undefined, "list");
    let focusTarget = null;
    for (const review of matchingReviews) {
      const card = nextOwnedReviewListCard(review);
      if (review.id === returnFocusReviewId) focusTarget = card;
      list.append(card);
    }
    for (const task of matchingTasks) {
      const card = nextOwnedTaskListCard(task);
      if (task.id === returnFocusOwnedTaskId) focusTarget = card;
      list.append(card);
    }
    results.replaceChildren(list);
    return focusTarget;
  };
  const currentSortOptions = archiveMode ? archiveTaskSortOptions : catalogSortOptions;
  const currentSortLabel = currentSortOptions.find(([, value]) => value === currentSort())?.[0]
    || (archiveMode ? "Недавно в архиве" : "Создано позже");
  const sort = element("button", undefined, "secondary catalog-sort-button work-list-sort-button");
  sort.type = "button";
  sort.setAttribute("aria-label", `Сортировка: ${currentSortLabel}`);
  sort.setAttribute("aria-haspopup", "dialog");
  sort.append(sortIcon());
  sort.classList.toggle("is-active", currentSort() !== (archiveMode ? "archive_desc" : "created_desc"));
  sort.addEventListener("click", () => showCatalogSortSheet(sort, {
    sortOptions: currentSortOptions,
    selectedSort: currentSort(),
    onSelect: (value) => {
      if (archiveMode) archivedTasksSort = value;
      else createdTasksSort = value;
      showNextCreatedAssignments(screenRevision);
    },
  }));
  let trailingControls = null;
  if (archiveMode) {
    const actionEnd = element("div", undefined, "catalog-actions-end");
    if (!performedArchive) {
      const filter = element("button", undefined, "secondary catalog-filter-button");
      filter.type = "button";
      filter.setAttribute("aria-label", "Фильтры архива");
      filter.setAttribute("aria-haspopup", "dialog");
      filter.append(slidersIcon());
      if (activeArchiveFilterCount) {
        filter.classList.add("is-active");
        filter.setAttribute("aria-label", `Фильтры архива, выбрано: ${activeArchiveFilterCount}`);
        filter.append(element("span", String(activeArchiveFilterCount), "catalog-filter-count"));
      }
      filter.addEventListener("click", () => showOwnedArchiveFilterSheet(filter));
      actionEnd.append(filter);
    }
    actionEnd.append(sort);
    trailingControls = actionEnd;
  } else {
    const actionEnd = element("div", undefined, "catalog-actions-end");
    const filter = taskFilterButton(createdTasksFilters, () => showCatalogFilterSheet(filter, {
      filters: createdTasksFilters,
      sourceTasks: scopedTasks,
      onChange: (value) => { createdTasksFilters = value; },
      refresh: () => showNextCreatedAssignments(screenRevision),
    }));
    actionEnd.append(filter, sort);
    trailingControls = actionEnd;
  }
  const header = nextWorkListHeader({
    searchLabel: archiveMode ? "Поиск в архиве заданий" : "Поиск в созданных заданиях",
    query: currentQuery(),
    onQuery: (value) => {
      if (archiveMode) archivedTasksQuery = value;
      else createdTasksQuery = value;
      updateResults();
    },
    trailingControls,
  });
  if (archiveMode) {
    const archiveRoles = element("div", undefined, "segmented archive-role-tabs");
    for (const [label, value] of [["Созданные", "created"], ["Выполненные", "performed"]]) {
      const roleButton = element("button", label);
      roleButton.type = "button";
      roleButton.setAttribute("aria-pressed", String(ownedArchiveRole === value));
      roleButton.addEventListener("click", () => {
        if (ownedArchiveRole !== value) void loadCreatedReviews(true, "archive", value);
      });
      archiveRoles.append(roleButton);
    }
    boundary.append(header.actions, archiveRoles, results);
  } else {
    boundary.append(header.actions, headingRow, results);
  }
  const focusTarget = updateResults();
  replaceContent(boundary);
  focusTarget?.focus({ preventScroll: true });
  returnFocusOwnedTaskId = null;
  returnFocusReviewId = null;
  const scrollTop = Number(history.state?.scrollTop || 0);
  if (scrollTop) queueMicrotask(() => content.closest(".screen")?.scrollTo({ top: scrollTop }));
}

function renderCreatedAssignments(revision) {
  if (revision !== screenRevision) return;
  showNextCreatedAssignments(revision);
}

async function loadCreatedReviews(push = true, scope = "active", archiveRole = "created") {
  const revision = ++screenRevision;
  ownedTaskListScope = scope === "archive" ? "archive" : "active";
  ownedArchiveRole = archiveRole === "performed" ? "performed" : "created";
  if (push) {
    const baseLocation = presentationLocationFor("M09");
    const nextLocation = ownedTaskListScope === "archive"
      ? `${baseLocation}&scope=archive${ownedArchiveRole === "performed" ? "&archive_view=performed" : ""}`
      : baseLocation;
    history.replaceState(
      { screen: "created-assignments", scope: ownedTaskListScope, archiveRole: ownedArchiveRole },
      "",
      nextLocation,
    );
  }
  const ownedPath = ownedTaskListScope === "archive" && ownedArchiveRole === "performed"
    ? "/api/v1/owned-tasks?scope=performed"
    : "/api/v1/owned-tasks";
  const reviewsPath = "/api/v1/assignment-reviews";
  const cachedOwned = cachedJson(ownedPath);
  const cachedReviews = cachedJson(reviewsPath);
  if (cachedOwned && cachedReviews) {
    ownedTasks = cachedOwned.items;
    ownedReviews = cachedReviews.items;
    renderCreatedAssignments(revision);
  } else {
    setNavigation("assignments", false);
    title.textContent = "Мои задания";
    back.classList.add("hidden");
    replaceContent(element("p", "Загружаем созданные задания…", "status muted"));
  }
  try {
    const [owned, reviews] = await Promise.all([
      getJson(ownedPath),
      getJson(reviewsPath),
    ]);
    if (revision !== screenRevision) return;
    if (cachedOwned && cachedReviews) return;
    ownedTasks = owned.items;
    ownedReviews = reviews.items;
    renderCreatedAssignments(revision);
  } catch (error) {
    if (revision !== screenRevision) return;
    const retry = element("button", "Повторить", "primary");
    retry.type = "button";
    retry.addEventListener("click", () => loadCreatedReviews(false, ownedTaskListScope, ownedArchiveRole));
    replaceContent(element("p", "Не удалось загрузить созданные задания.", "status"), retry);
  }
}

async function showCreatedReview(assignmentId, push = true, returnTo = null) {
  const revision = ++screenRevision;
  returnFocusReviewId = assignmentId;
  const returnTarget = returnTo || (
    history.state?.screen === "assignment-review"
      && history.state.assignmentId === assignmentId
      ? history.state.returnTo
      : null
  );
  if (push) {
    history.pushState(
      {
        screen: "assignment-review",
        assignmentId,
        ...(returnTarget ? { returnTo: returnTarget } : {}),
      },
      "",
      presentationLocationFor("M11", assignmentId),
    );
  }
  const moderationReview = returnTarget === "moderation-community";
  setNavigation(moderationReview ? "moderation" : "", true);
  title.textContent = "Решение по результату";
  shell.classList.add("assignment-review-screen");
  setHeaderControl("back", {
    label: returnTarget === "task-home" ? "Назад к заданиям" : "Назад",
    screenLabel: "Решение по результату",
    hideTitle: true,
    onBack: returnTarget === "task-home"
      ? () => loadTaskHome()
      : moderationReview ? () => loadCommunityReviews() : null,
  });
  replaceContent(element("p", "Загружаем результат…", "status muted"));
  try {
    const review = await getJson(
      (moderationReview ? "/api/v1/moderation/community-reviews/" : "/api/v1/assignment-reviews/")
      + encodeURIComponent(assignmentId),
    );
    if (revision !== screenRevision) return;
    const detail = element("article", undefined, "card detail assignment-review-detail");
    const status = element("p", "", "status hidden");
    status.setAttribute("aria-live", "polite");
    const detailHeader = element("header", undefined, "assignment-detail-header");
    const detailMeta = element("div", undefined, "assignment-detail-meta");
    detailMeta.append(element("span", "Требуется решение", "assignment-detail-status"));
    if (review.review_deadline_at) {
      const deadline = element("span", undefined, "assignment-detail-deadline");
      deadline.append(element("span", "Решить до"), time(review.review_deadline_at));
      detailMeta.append(deadline);
    }
    detailHeader.append(element("h2", review.task_title), detailMeta);
    const detailContent = element("div", undefined, "assignment-detail-content");
    const performer = element("section", undefined, "section assignment-detail-section");
    performer.append(
      element("h3", "Исполнитель"),
      memberProfileButton(review.performer_id, review.performer_display_name, "исполнителя"),
    );
    const result = section("Результат", review.result);
    result.classList.add("assignment-detail-section", "assignment-review-result");
    detailContent.append(performer, result);
    detail.append(detailHeader, detailContent);
    const decisionActions = element("div", undefined, "assignment-review-actions");
    for (const decision of review.available_decisions) {
      const decisionClass = decision === "full"
        ? "primary assignment-review-action-full"
        : decision === "reject"
          ? "secondary danger"
          : "secondary";
      const button = element(
        "button",
        decisionLabels[decision],
        decisionClass,
      );
      button.type = "button";
      markTransition(button, "PE-040", "authoritative_review_success");
      let operationKey = null;
      const saveDecision = async ({ confirm = button, edit = null, status: actionStatus = status } = {}) => {
        confirm.disabled = true;
        if (edit) edit.disabled = true;
        actionStatus.className = "status";
        actionStatus.textContent = "Сохраняем решение…";
        operationKey ||= newOperationKey();
        try {
          await submissionRequest(
            "/api/v1/assignment-reviews/" + encodeURIComponent(assignmentId) + "/decision",
            "POST",
            operationKey,
            { decision },
          );
          if (returnTarget === "task-home") {
            await loadTaskHome();
            return;
          }
          if (moderationReview) {
            await loadCommunityReviews();
            showAdministratorToast("Решение сохранено");
            return;
          }
          history.replaceState(
            { screen: "review-outcome", assignmentId },
            "",
            presentationLocationFor("M13", assignmentId),
          );
          title.textContent = "Решение сохранено";
          const done = element("button", "К созданным заданиям", "primary");
          done.type = "button";
          done.addEventListener("click", () => {
            history.replaceState(
              { screen: "created-assignments", scope: "active" },
              "",
              presentationLocationFor("M09"),
            );
            void loadCreatedReviews(false, "active");
          });
          replaceContent(connectedBoundary("M13", "success", element("p", `Решение «${decisionLabels[decision]}» сохранено.`, "status success"), done));
        } catch (error) {
          actionStatus.textContent = "Не удалось сохранить решение. Повторите запрос — ключ останется тем же.";
          if (!retryableSubmissionError(error)) operationKey = null;
          confirm.disabled = false;
          if (edit) edit.disabled = false;
        }
      };
      button.addEventListener("click", () => {
        const sheet = showAssignmentActionSheet(button, {
          title: decisionLabels[decision],
          description: decision === "reject"
            ? moderationReview
              ? "Исполнитель сможет открыть спор в течение 24 часов."
              : "Резерв останется заморожен на 24 часа — исполнитель сможет открыть спор."
            : decision === "partial"
              ? "Исполнитель получит частичную награду за принятый результат."
              : "Результат будет принят, а награда полностью перечислена исполнителю.",
          tone: decision === "reject" ? "danger" : "default",
        });
        const confirmClass = decision === "reject"
          ? "assignment-action-confirm-danger"
          : "primary";
        const confirm = element("button", decisionLabels[decision], confirmClass);
        confirm.type = "button";
        markTransition(confirm, "PE-040", "authoritative_review_success");
        confirm.addEventListener("click", () => saveDecision({
          confirm,
          status: sheet.status,
        }));
        sheet.actions.append(confirm);
        queueMicrotask(() => confirm.focus({ preventScroll: true }));
      });
      decisionActions.append(button);
    }
    detail.append(decisionActions);
    detail.append(status);
    replaceContent(connectedBoundary("M11", "content", detail));
    back.focus({ preventScroll: true });
  } catch (error) {
    if (revision === screenRevision) replaceContent(...assignmentError(error.message));
  }
}

const submissionMessage = (error) => error instanceof TypeError
  ? "Сеть недоступна. Повторите запрос — он останется тем же."
  : "Не удалось сохранить результат. Проверьте назначение и повторите.";

const retryableSubmissionError = (error) => error instanceof TypeError
  || !error?.status
  || error.status >= 500
  || error.status < 400;

async function submissionResponse(response) {
  let payload = null;
  if (response.status !== 204) {
    try {
      payload = await response.json();
    } catch {
      const error = new Error("request_failed");
      error.status = response.status;
      throw error;
    }
  }
  if (!response.ok) {
    const error = new Error(payload?.code || "request_failed");
    error.status = response.status;
    throw error;
  }
  return payload;
}

async function submissionRequest(path, method, operationKey, body) {
  const response = await apiFetch(path, {
    method,
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": operationKey,
    },
    body: JSON.stringify(body),
    credentials: "same-origin",
  });
  return submissionResponse(response);
}

function showAssignmentActionSheet(trigger, { title: headingText, description, tone = "default" }) {
  shell.querySelector(".assignment-action-backdrop")?.remove();
  const backdrop = element("section", undefined, "assignment-action-backdrop");
  const dialog = element("div", undefined, `assignment-action-sheet assignment-action-sheet-${tone}`);
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.setAttribute("aria-labelledby", "assignment-action-title");
  const header = element("header", undefined, "assignment-action-heading");
  const headingNode = element("h2", headingText);
  headingNode.id = "assignment-action-title";
  const close = element("button", "×", "assignment-action-close");
  close.type = "button";
  close.setAttribute("aria-label", "Закрыть окно");
  header.append(headingNode, close);
  const body = element("div", undefined, "assignment-action-body");
  if (description) body.append(element("p", description, "assignment-action-description"));
  const status = element("p", "", "assignment-action-status hidden");
  status.setAttribute("aria-live", "polite");
  const actions = element("div", undefined, "assignment-action-buttons");
  const dismiss = (restoreFocus = true) => {
    if (!backdrop.isConnected) return;
    backdrop.remove();
    if (restoreFocus) trigger?.focus({ preventScroll: true });
  };
  close.addEventListener("click", () => dismiss());
  backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop) dismiss();
  });
  dialog.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      dismiss();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = [...dialog.querySelectorAll(
      'button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled])',
    )];
    const first = focusable[0];
    const last = focusable.at(-1);
    if (!first || !last) return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
  dialog.append(header, body, status, actions);
  backdrop.append(dialog);
  shell.append(backdrop);
  return { backdrop, dialog, body, status, actions, close, dismiss };
}

function showSubmissionActionSheet(trigger, assignment) {
  const returnToTaskHome = history.state?.screen === "assignment"
    && history.state.returnTo === "task-home";
  const sheet = showAssignmentActionSheet(trigger, {
    title: "Отправить результат",
    description: "Опишите готовый результат — автор увидит его при проверке.",
  });
  const form = element("form", undefined, "assignment-action-form");
  const label = element("label", "Результат");
  const input = document.createElement("textarea");
  input.id = "assignment-result-sheet";
  input.name = "result";
  input.required = true;
  input.minLength = 10;
  input.maxLength = 2000;
  input.rows = 4;
  input.placeholder = "Что сделано и где посмотреть результат";
  input.setAttribute("aria-label", "Результат");
  label.htmlFor = input.id;
  const counter = element(
    "span",
    "Минимум 10 символов · 0 / 2000",
    "assignment-action-counter is-requirement",
  );
  label.append(input, counter);
  form.append(label);
  sheet.body.append(form);
  const submit = element("button", "Подготавливаем…", "primary");
  submit.type = "submit";
  submit.disabled = true;
  submit.setAttribute("form", "assignment-result-form");
  form.id = "assignment-result-form";
  markTransition(submit, "PE-034", "authoritative_submit_success");
  sheet.actions.append(submit);

  let draft = null;
  let beginKey = null;
  let saveKey = null;
  let confirmKey = null;

  const showStatus = (message, kind = "") => {
    sheet.status.className = `assignment-action-status${kind ? ` ${kind}` : ""}`;
    sheet.status.textContent = message;
  };
  const updateCounter = () => {
    const normalizedLength = input.value.trim().length;
    const missingLength = Math.max(0, input.minLength - normalizedLength);
    counter.textContent = missingLength === input.minLength
      ? `Минимум ${input.minLength} символов · ${input.value.length} / 2000`
      : missingLength
        ? `Нужно ещё ${missingLength} · ${input.value.length} / 2000`
        : `${input.value.length} / 2000`;
    counter.classList.toggle("is-requirement", missingLength > 0);
    counter.classList.toggle("is-limit", input.value.length >= input.maxLength);
    submit.disabled = !draft || normalizedLength < input.minLength;
  };
  input.addEventListener("input", () => {
    confirmKey = null;
    updateCounter();
  });

  const ensureDraft = async () => {
    submit.disabled = true;
    submit.textContent = "Подготавливаем…";
    showStatus("Открываем черновик…", "is-loading");
    beginKey ||= newOperationKey();
    try {
      const response = await apiFetch(
        "/api/v1/assignments/" + encodeURIComponent(assignment.id) + "/submission-drafts",
        {
          method: "POST",
          headers: { "Idempotency-Key": beginKey },
          credentials: "same-origin",
        },
      );
      draft = await submissionResponse(response);
      input.value = typeof draft.result === "string" ? draft.result : "";
      sheet.status.className = "assignment-action-status hidden";
      submit.textContent = "Отправить результат";
      updateCounter();
      input.focus({ preventScroll: true });
    } catch (error) {
      showStatus(submissionMessage(error), "is-error");
      if (!retryableSubmissionError(error)) beginKey = null;
      submit.textContent = "Повторить";
      submit.disabled = false;
    }
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!draft) {
      await ensureDraft();
      return;
    }
    const result = input.value.trim();
    if (result.length < input.minLength) {
      showStatus("Опишите результат минимум в 10 символах.", "is-error");
      input.focus({ preventScroll: true });
      return;
    }
    sheet.close.disabled = true;
    submit.disabled = true;
    submit.textContent = "Отправляем…";
    showStatus("Сохраняем и отправляем результат…", "is-loading");
    try {
      if (draft.result !== result) {
        saveKey ||= newOperationKey();
        draft = await submissionRequest(
          "/api/v1/submission-drafts/" + encodeURIComponent(draft.id),
          "PUT",
          saveKey,
          { expected_revision: draft.revision, payload: { result } },
        );
        saveKey = null;
        confirmKey = null;
      }
      confirmKey ||= newOperationKey();
      await submissionRequest(
        "/api/v1/submission-drafts/" + encodeURIComponent(draft.id) + "/confirm",
        "POST",
        confirmKey,
        { expected_revision: draft.revision },
      );
      sheet.dismiss(false);
      if (returnToTaskHome) {
        await loadTaskHome();
        return;
      }
      await showAssignmentDetail(assignment.id, false);
      const success = element("p", "Результат отправлен на проверку.", "status success assignment-inline-outcome");
      content.querySelector('[data-screen-id="M03"]')?.append(success);
    } catch (error) {
      showStatus(submissionMessage(error), "is-error");
      if (!retryableSubmissionError(error)) {
        saveKey = null;
        confirmKey = null;
      }
      sheet.close.disabled = false;
      submit.disabled = false;
      submit.textContent = "Повторить отправку";
    }
  });
  queueMicrotask(() => sheet.close.focus({ preventScroll: true }));
  void ensureDraft();
}

function showCancellationActionSheet(trigger, assignment) {
  const returnToTaskHome = history.state?.screen === "assignment"
    && history.state.returnTo === "task-home";
  const sheet = showAssignmentActionSheet(trigger, {
    title: "Отказаться от задания",
    description: "Слот освободится, а задание исчезнет из ваших активных.",
    tone: "danger",
  });
  const form = element("form", undefined, "assignment-action-form");
  form.id = "assignment-cancellation-form";
  const label = element("label", "Причина отказа");
  const reason = document.createElement("textarea");
  reason.id = "assignment-cancellation-sheet-reason";
  reason.name = "reason";
  reason.required = true;
  reason.maxLength = 1000;
  reason.rows = 3;
  reason.placeholder = "Коротко объясните причину";
  reason.setAttribute("aria-label", "Причина отказа");
  label.htmlFor = reason.id;
  const counter = element(
    "span",
    "Укажите причину отказа · 0 / 1000",
    "assignment-action-counter is-requirement",
  );
  label.append(reason, counter);
  form.append(label);
  sheet.body.append(form);
  const confirm = element("button", "Подтвердить отказ", "assignment-action-confirm-danger");
  confirm.type = "submit";
  confirm.setAttribute("form", form.id);
  confirm.disabled = true;
  markTransition(confirm, "PE-036", "withdrawal_outcome");
  sheet.actions.append(confirm);
  let operationKey = null;
  reason.addEventListener("input", () => {
    const hasReason = Boolean(reason.value.trim());
    counter.textContent = hasReason
      ? `${reason.value.length} / 1000`
      : `Укажите причину отказа · ${reason.value.length} / 1000`;
    counter.classList.toggle("is-requirement", !hasReason);
    counter.classList.toggle("is-limit", reason.value.length >= reason.maxLength);
    confirm.disabled = !hasReason;
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const normalized = reason.value.trim();
    if (!normalized) return;
    sheet.close.disabled = true;
    confirm.disabled = true;
    confirm.textContent = "Отказываемся…";
    sheet.status.className = "assignment-action-status is-loading";
    sheet.status.textContent = "Отправляем отказ…";
    operationKey ||= newOperationKey();
    try {
      await submissionRequest(
        "/api/v1/assignments/" + encodeURIComponent(assignment.id) + "/cancellation",
        "POST",
        operationKey,
        { reason: normalized },
      );
      sheet.dismiss(false);
      if (returnToTaskHome) {
        await loadTaskHome();
        return;
      }
      history.replaceState({ screen: "assignments" }, "", presentationLocationFor("M01"));
      await loadAssignments(false);
    } catch (error) {
      sheet.status.className = "assignment-action-status is-error";
      sheet.status.textContent = error instanceof TypeError
        ? "Сеть недоступна. Повторите запрос — он останется тем же."
        : "Не удалось отказаться. Проверьте состояние задания и повторите.";
      if (!retryableSubmissionError(error)) operationKey = null;
      sheet.close.disabled = false;
      confirm.disabled = false;
      confirm.textContent = "Повторить отказ";
    }
  });
  queueMicrotask(() => reason.focus({ preventScroll: true }));
}

function showDisputeActionSheet(trigger, assignment) {
  const returnToTaskHome = history.state?.screen === "assignment"
    && history.state.returnTo === "task-home";
  const sheet = showAssignmentActionSheet(trigger, {
    title: "Открыть спор",
    description: "Опишите, почему результат нужно пересмотреть. Комментарий увидит только команда модерации.",
  });
  const form = element("form", undefined, "assignment-action-form");
  form.id = "assignment-dispute-form";
  const label = element("label", "Причина пересмотра");
  const comment = document.createElement("textarea");
  comment.id = "assignment-dispute-sheet-comment";
  comment.name = "comment";
  comment.required = true;
  comment.minLength = 10;
  comment.maxLength = 1000;
  comment.rows = 4;
  comment.placeholder = "Что именно нужно пересмотреть";
  comment.setAttribute("aria-label", "Причина пересмотра");
  label.htmlFor = comment.id;
  const counter = element(
    "span",
    "Минимум 10 символов · 0 / 1000",
    "assignment-action-counter is-requirement",
  );
  label.append(comment, counter);
  form.append(label);
  sheet.body.append(form);
  const confirm = element("button", "Подать спор", "primary");
  confirm.type = "submit";
  confirm.setAttribute("form", form.id);
  confirm.disabled = true;
  markTransition(confirm, "PE-044", "open_dispute_materials");
  sheet.actions.append(confirm);
  let operationKey = null;

  const updateCounter = () => {
    const normalizedLength = comment.value.trim().length;
    const missingLength = Math.max(0, comment.minLength - normalizedLength);
    counter.textContent = missingLength === comment.minLength
      ? `Минимум ${comment.minLength} символов · ${comment.value.length} / 1000`
      : missingLength
        ? `Нужно ещё ${missingLength} · ${comment.value.length} / 1000`
        : `${comment.value.length} / 1000`;
    counter.classList.toggle("is-requirement", missingLength > 0);
    counter.classList.toggle("is-limit", comment.value.length >= comment.maxLength);
    confirm.disabled = normalizedLength < comment.minLength;
  };
  comment.addEventListener("input", updateCounter);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const normalized = comment.value.trim();
    if (normalized.length < comment.minLength) {
      sheet.status.className = "assignment-action-status is-error";
      sheet.status.textContent = "Опишите причину минимум в 10 символах.";
      comment.focus({ preventScroll: true });
      return;
    }
    sheet.close.disabled = true;
    confirm.disabled = true;
    confirm.textContent = "Подаём спор…";
    sheet.status.className = "assignment-action-status is-loading";
    sheet.status.textContent = "Передаём спор команде модерации…";
    operationKey ||= newOperationKey();
    try {
      await submissionRequest(
        "/api/v1/assignments/" + encodeURIComponent(assignment.id) + "/disputes",
        "POST",
        operationKey,
        { comment: normalized },
      );
      sheet.dismiss(false);
      if (returnToTaskHome) {
        await loadTaskHome();
        return;
      }
      await showAssignmentDetail(assignment.id, false);
    } catch (error) {
      if (error?.status === 409) {
        sheet.dismiss(false);
        if (returnToTaskHome) {
          await loadTaskHome();
          return;
        }
        await showAssignmentDetail(assignment.id, false);
        return;
      }
      sheet.status.className = "assignment-action-status is-error";
      sheet.status.textContent = error instanceof TypeError
        ? "Сеть недоступна. Повторите запрос — он останется тем же."
        : "Не удалось подать спор. Проверьте комментарий и состояние задания.";
      if (!retryableSubmissionError(error)) operationKey = null;
      sheet.close.disabled = false;
      confirm.disabled = false;
      confirm.textContent = "Повторить подачу";
    }
  });
  queueMicrotask(() => comment.focus({ preventScroll: true }));
}


async function showAssignmentDetail(assignmentId, push = true, returnTo = null) {
  const revision = ++screenRevision;
  returnFocusAssignmentId = assignmentId;
  const returnTarget = returnTo || (
    history.state?.screen === "assignment"
      && history.state.assignmentId === assignmentId
      ? history.state.returnTo
      : null
  );
  if (push) {
    history.pushState(
      {
        screen: "assignment",
        assignmentId,
        ...(returnTarget ? { returnTo: returnTarget } : {}),
      },
      "",
      presentationLocationFor("M03", assignmentId),
    );
  }
  setNavigation("", true);
  title.textContent = "Активное назначение";
  const returnToTakenAssignments = returnTarget === "assignments-taken";
  const returnToTaskHome = returnTarget === "task-home";
  shell.classList.add("assignment-detail-screen");
  setHeaderControl("back", {
    label: returnToTaskHome
      ? "Назад к заданиям"
      : returnToTakenAssignments
        ? "Назад к выполняемым заданиям"
        : "Назад",
    screenLabel: "Активное назначение",
    hideTitle: true,
    onBack: returnToTaskHome
      ? () => loadTaskHome()
      : returnToTakenAssignments
        ? () => loadAssignments()
        : null,
  });
  replaceContent(element("p", "Загружаем назначение…", "status muted"));
  try {
    const response = await apiFetch(
      "/api/v1/assignments/" + encodeURIComponent(assignmentId),
      { credentials: "same-origin" },
    );
    if (!response.ok) throw new Error(requestError(response));
    const assignment = await response.json();
    if (revision !== screenRevision) return;
    const detail = element("article", undefined, "card detail assignment-detail");
    const detailHeader = element("header", undefined, "assignment-detail-header");
    const detailMeta = element("div", undefined, "assignment-detail-meta");
    const deadline = element("span", undefined, "assignment-detail-deadline");
    deadline.append(element("span", "Срок"), time(assignment.task_deadline_at));
    detailMeta.append(
      element(
        "span",
        assignmentStatus(assignment.assignment_status),
        "assignment-detail-status",
      ),
      deadline,
    );
    detailHeader.append(element("h2", assignment.task_title));
    if (assignment.task_author_display_name) {
      const customer = element("div", undefined, "assignment-detail-customer");
      customer.append(element("span", "Заказчик", "assignment-detail-customer-label"));
      if (assignment.task_creator_id) {
        const customerProfile = memberProfileButton(
          assignment.task_creator_id,
          assignment.task_author_display_name,
          "заказчика",
        );
        customer.append(customerProfile);
      } else {
        customer.append(
          element("span", assignment.task_author_display_name, "assignment-detail-customer-name"),
        );
      }
      detailHeader.append(customer);
    }
    detailHeader.append(detailMeta);
    const detailContent = element("div", undefined, "assignment-detail-content");
    const compactSection = (headingText, value) => {
      const node = section(headingText, value);
      node.classList.add("assignment-detail-section");
      return node;
    };
    const compactDateSection = (headingText, value) => {
      const node = dateSection(headingText, value);
      node.classList.add("assignment-detail-section");
      return node;
    };
    detailContent.append(
      compactSection("Описание", assignment.description),
      compactSection("Критерии приёмки", assignment.completion_criteria),
      compactSection("Как выполнить", assignment.performer_instructions),
    );
    if (assignment.result_summary) {
      detailContent.append(compactSection("Последний результат", assignment.result_summary));
    }
    if (assignment.review_deadline_at) {
      detailContent.append(compactDateSection("Срок проверки", assignment.review_deadline_at));
    }
    if (assignment.reject_dispute_deadline_at) {
      detailContent.append(compactDateSection("Подать спор до", assignment.reject_dispute_deadline_at));
    }
    if (assignment.case_status) {
      const disputeStatus = compactSection("Спор", "Передан команде модерации");
      disputeStatus.dataset.screenId = "M15";
      disputeStatus.dataset.uiEngine = "concept-05";
      detailContent.append(disputeStatus);
    } else if (assignment.assignment_status === "rejected_pending_dispute") {
      detailContent.append(compactSection(
        "Условия спора",
        assignment.can_dispute
          ? "Опишите причину до указанного срока. Комментарий увидит только команда модерации."
          : "Срок подачи спора истёк.",
      ));
    }
    const actions = element("div", undefined, "detail-actions");
    if (assignment.can_submit) {
      const submit = element("button", "Отправить результат", "primary");
      submit.type = "button";
      submit.addEventListener("click", () => showSubmissionActionSheet(submit, assignment));
      actions.append(submit);
    }
    if (assignment.can_dispute) {
      const dispute = element("button", "Подать спор", "secondary");
      dispute.type = "button";
      dispute.addEventListener("click", () => showDisputeActionSheet(dispute, assignment));
      actions.append(dispute);
    }
    if (assignment.can_cancel) {
      const cancel = element("button", "Отказаться от задания", "secondary danger");
      cancel.type = "button";
      cancel.addEventListener("click", () => showCancellationActionSheet(cancel, assignment));
      actions.append(cancel);
    }
    detail.append(detailHeader, detailContent);
    if (actions.childElementCount) detail.append(actions);
    replaceContent(connectedBoundary("M03", "content", detail));
    back.focus({ preventScroll: true });
  } catch (error) {
    if (revision !== screenRevision) return;
    const code = error.message === "request_failed" ? "detail_failed" : error.message;
    const nodes = code === "detail_failed"
      ? [element("p", "Не удалось загрузить назначение. Вернитесь назад и повторите.", "status")]
      : assignmentError(code);
    replaceContent(...nodes);
  }
}

const moderationCaseType = (value) => ({
  dispute: "Спор по заданию",
  fraud_review: "Проверка операции",
}[value] || "Кейс модерации");

const moderationStatus = (value) => ({
  open: "Открыт",
  appealed: "Обжалован",
}[value] || value);

const resolutionLabels = {
  full_payment: "Полная выплата",
  partial_payment: "Частичная выплата",
  full_refund: "Полный возврат",
  cancel_without_fault: "Отмена без вины сторон",
  performer_no_show: "Неявка исполнителя",
  creator_abuse: "Нарушение со стороны автора",
  fraud: "Мошенничество",
};

const moderationError = (code, retry) => {
  if (code === "session_expired") {
    return [element("p", "Сессия истекла. Закройте и снова откройте Mini App.", "status")];
  }
  if (code === "account_unavailable") {
    return [element("p", "Споры недоступны для этого аккаунта.", "status")];
  }
  return [
    element("p", "Не удалось загрузить споры.", "status"),
    retry,
  ];
};

const administratorPermissionDetails = [
  ["interaction_review", "Модерация споров", "Просмотр дел и принятие решений"],
  ["member_invitation", "Приглашение участников", "Создание и отзыв персональных приглашений"],
  ["member_blocking", "Блокировка пользователей", "Ограничение и восстановление доступа"],
  ["administrator_management", "Назначение администраторов", "Повышенное право: только в пределах своих полномочий"],
  ["community_task_create", "Создание заданий сообщества", "Публикация заданий от имени сообщества"],
  ["community_task_review", "Проверка заданий сообщества", "Решения по результатам в очереди модерации"],
];

const administratorIdentity = (person, meta) => {
  const row = element("span", undefined, "admin-person-main");
  row.append(
    element("span", person.display_name, "admin-person-name"),
    element(
      "span",
      `${person.telegram_username ? `@${person.telegram_username}` : "без username"}${meta ? ` · ${meta}` : ""}`,
      "admin-person-meta",
    ),
  );
  return row;
};

const administratorPermissionNames = (permissions) => administratorPermissionDetails
  .filter(([id]) => permissions.includes(id))
  .map(([, name]) => name);

function moderationTabs(active, disputeCount = null) {
  const tabs = element("div", undefined, "admin-tabs");
  tabs.dataset.active = active;
  if (disputeCount !== null) tabs.dataset.disputeCount = String(disputeCount);
  const options = [
    ["disputes", disputeCount === null ? "Споры" : `Споры · ${disputeCount}`, () => loadModeration()],
  ];
  if (administratorPermissions.includes("community_task_review")) {
    options.push(["community-reviews", "Проверка", () => loadCommunityReviews()]);
  }
  options.push(
    ["access", "Доступ", () => loadAdministrationAccess()],
    ["team", "Команда", () => loadAdministrationTeam()],
  );
  if (canGrantCredits) {
    tabs.classList.add("has-credits");
    options.push(["credits", "Кредиты", () => loadCreditGrantHome()]);
  }
  tabs.style.gridTemplateColumns = `repeat(${options.length}, minmax(0, 1fr))`;
  for (const [id, label, action] of options) {
    const button = element("button", label, "admin-tab");
    button.type = "button";
    button.classList.toggle("is-active", id === active);
    button.setAttribute("aria-pressed", String(id === active));
    button.addEventListener("click", action);
    tabs.append(button);
  }
  return tabs;
}

const creditGrantStatusLabel = (status) => ({
  active: "активный участник",
  paused: "доступ приостановлен",
  restricted: "доступ ограничен",
  suspended: "доступ приостановлен",
  banned: "заблокирован",
  left: "вышел из сообщества",
  pending: "регистрация не завершена",
}[status] || status);

const creditGrantRecipientCard = (person, { selectable = false, self = false } = {}) => {
  const card = element(selectable ? "button" : "article", undefined, "credit-recipient-card");
  if (selectable) card.type = "button";
  const avatar = personAvatar(person);
  const identity = administratorIdentity(
    person,
    self ? "это вы" : creditGrantStatusLabel(person.status),
  );
  const balance = element("span", undefined, "credit-recipient-balance");
  balance.append(
    element("strong", String(person.credit_balance)),
    element("small", "кредитов"),
  );
  card.append(avatar, identity, balance);
  return card;
};

const creditGrantInlineSearch = (revision) => {
  const panel = element("section", undefined, "credit-inline-search");
  const search = element("label", undefined, "credit-search-field");
  search.append(searchIcon());
  const input = document.createElement("input");
  input.type = "search";
  input.placeholder = "Имя или @username";
  input.autocomplete = "off";
  input.maxLength = 80;
  search.append(input);
  const results = element("section", undefined, "credit-search-results");
  let timer = null;
  let requestNumber = 0;
  const runSearch = async () => {
    const query = input.value.trim();
    const currentRequest = ++requestNumber;
    if (!query) {
      results.replaceChildren();
      return;
    }
    results.replaceChildren(element("p", "Ищем…", "compact-empty"));
    try {
      const page = await getJson(
        `/api/v1/administration/credits/recipients?limit=30&query=${encodeURIComponent(query)}`,
      );
      if (revision !== screenRevision || currentRequest !== requestNumber) return;
      if (!page.items.length) {
        results.replaceChildren(element("p", "Участники не найдены.", "compact-empty"));
        return;
      }
      const list = element("div", undefined, "credit-recipient-list");
      for (const person of page.items) {
        const card = creditGrantRecipientCard(person, { selectable: true });
        card.addEventListener("click", () => showCreditGrantForm(person));
        list.append(card);
      }
      results.replaceChildren(list);
    } catch {
      if (revision !== screenRevision || currentRequest !== requestNumber) return;
      results.replaceChildren(element("p", "Не удалось выполнить поиск. Повторите.", "compact-empty"));
    }
  };
  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(runSearch, 250);
  });
  panel.append(search, results);
  return panel;
};

async function loadCreditGrantHome(push = true) {
  const revision = ++screenRevision;
  if (push) history.pushState({ screen: "credit-grant-home" }, "", "#/moderation/credits");
  else if (location.hash !== "#/moderation/credits") {
    history.replaceState({ screen: "credit-grant-home" }, "", "#/moderation/credits");
  }
  setNavigation("moderation", false);
  title.textContent = "Модерация";
  replaceContent(moderationTabs("credits"), element("p", "Загружаем баланс…", "compact-empty"));
  try {
    const self = await getJson("/api/v1/administration/credits/self");
    if (revision !== screenRevision) return;
    canGrantCredits = true;
    const boundary = element("section", undefined, "state-view credit-grant-home");
    const intro = element("section", undefined, "credit-grant-intro");
    const introHeader = element("div", undefined, "credit-grant-intro-header");
    const introCopy = element("div", undefined, "credit-grant-intro-copy");
    introCopy.append(
      element("h2", "Кому начислить"),
      element("p", "Выберите себя или найдите участника", "muted"),
    );
    const historyButton = element("button", "История", "credit-history-link");
    historyButton.type = "button";
    historyButton.addEventListener("click", () => loadCreditGrantHistory());
    introHeader.append(introCopy, historyButton);
    intro.append(
      introHeader,
      creditGrantRecipientCard(self, { selectable: true, self: true }),
      creditGrantInlineSearch(revision),
    );
    intro.querySelector(".credit-recipient-card").addEventListener("click", () => {
      showCreditGrantForm(self);
    });
    boundary.append(moderationTabs("credits"), intro);
    replaceContent(boundary);
  } catch (error) {
    if (revision !== screenRevision) return;
    const retry = element("button", "Повторить", "primary");
    retry.type = "button";
    retry.addEventListener("click", () => loadCreditGrantHome(false));
    replaceContent(
      moderationTabs("credits"),
      element("p", "Начисление кредитов недоступно.", "compact-empty"),
      retry,
    );
  }
}

async function showCreditGrantForm(personOrId, push = true) {
  const revision = ++screenRevision;
  const person = typeof personOrId === "string"
    ? await getJson(`/api/v1/administration/credits/recipients/${encodeURIComponent(personOrId)}`)
    : personOrId;
  if (revision !== screenRevision) return;
  if (push) {
    history.pushState(
      { screen: "credit-grant-form", memberId: person.member_id },
      "",
      `#/moderation/credits/recipients/${encodeURIComponent(person.member_id)}`,
    );
  }
  setNavigation("moderation", true);
  heading.classList.add("credit-grant-heading");
  title.textContent = "Начисление";
  setHeaderControl("back", { onBack: () => loadCreditGrantHome(false) });
  const retained = creditGrantDraft?.person?.member_id === person.member_id
    ? creditGrantDraft
    : { person, amount: "", reason: "", operationKey: null };
  creditGrantDraft = { ...retained, person };
  const form = element("form", undefined, "credit-grant-form");
  const amountLabel = element("label", undefined, "credit-grant-field");
  amountLabel.append(element("span", "Сколько кредитов"));
  const amount = document.createElement("input");
  amount.type = "number";
  amount.inputMode = "numeric";
  amount.min = "1";
  amount.step = "1";
  amount.placeholder = "0";
  amount.required = true;
  amount.value = creditGrantDraft.amount || "";
  amountLabel.append(amount);
  const reasonLabel = element("label", undefined, "credit-grant-field");
  reasonLabel.append(element("span", "Причина начисления"));
  const reason = document.createElement("textarea");
  reason.rows = 3;
  reason.minLength = 3;
  reason.maxLength = 500;
  reason.placeholder = "Например: компенсация за техническую ошибку";
  reason.required = true;
  reason.value = creditGrantDraft.reason || "";
  reasonLabel.append(reason);
  const note = element("p", "Баланс увеличится без начисления опыта.", "credit-grant-note");
  const status = element("p", "", "status hidden");
  const continueButton = element("button", "Продолжить", "primary");
  continueButton.type = "submit";
  form.append(
    creditGrantRecipientCard(person),
    amountLabel,
    reasonLabel,
    note,
    status,
    continueButton,
  );
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const amountValue = Number(amount.value);
    const reasonValue = reason.value.trim();
    if (!Number.isSafeInteger(amountValue) || amountValue <= 0) {
      status.className = "status is-error";
      status.textContent = "Введите целое количество кредитов больше нуля.";
      amount.focus();
      return;
    }
    if (reasonValue.length < 3) {
      status.className = "status is-error";
      status.textContent = "Коротко укажите причину начисления.";
      reason.focus();
      return;
    }
    creditGrantDraft = { person, amount: amountValue, reason: reasonValue, operationKey: null };
    showCreditGrantConfirmation();
  });
  replaceContent(form);
  amount.focus({ preventScroll: true });
}

function showCreditGrantConfirmation(push = true) {
  if (!creditGrantDraft?.person || !creditGrantDraft.amount || !creditGrantDraft.reason) {
    loadCreditGrantHome(false);
    return;
  }
  ++screenRevision;
  if (push) {
    history.pushState(
      { screen: "credit-grant-confirm", memberId: creditGrantDraft.person.member_id },
      "",
      "#/moderation/credits/confirm",
    );
  }
  setNavigation("moderation", true);
  heading.classList.add("credit-grant-heading");
  title.textContent = "Подтверждение";
  setHeaderControl("back", { onBack: () => showCreditGrantForm(creditGrantDraft.person, false) });
  const card = element("section", undefined, "credit-grant-confirm");
  card.append(
    creditGrantRecipientCard(creditGrantDraft.person),
    element("p", `+${creditGrantDraft.amount} кредитов`, "credit-grant-confirm-amount"),
    section("Причина", creditGrantDraft.reason),
    element("p", "Опыт и уровень участника не изменятся.", "credit-grant-note"),
  );
  const status = element("p", "", "status hidden");
  const confirm = element("button", "Начислить кредиты", "primary");
  confirm.type = "button";
  confirm.addEventListener("click", async () => {
    confirm.disabled = true;
    status.className = "status";
    status.textContent = "Начисляем…";
    creditGrantDraft.operationKey ||= newOperationKey();
    try {
      const receipt = await submissionRequest(
        "/api/v1/administration/credits/grants",
        "POST",
        creditGrantDraft.operationKey,
        {
          target_member_id: creditGrantDraft.person.member_id,
          amount: creditGrantDraft.amount,
          reason: creditGrantDraft.reason,
        },
      );
      showCreditGrantSuccess(receipt);
    } catch (error) {
      status.className = "status is-error";
      status.textContent = error instanceof TypeError
        ? "Сеть недоступна. Повторите начисление."
        : "Не удалось начислить кредиты. Проверьте данные и повторите.";
      if (!retryableSubmissionError(error)) creditGrantDraft.operationKey = null;
      confirm.disabled = false;
    }
  });
  card.append(status, confirm);
  replaceContent(card);
}

function showCreditGrantSuccess(receipt) {
  ++screenRevision;
  history.replaceState(
    { screen: "credit-grant-success", memberId: receipt.recipient.member_id },
    "",
    "#/moderation/credits/success",
  );
  setNavigation("moderation", true);
  heading.classList.add("credit-grant-heading");
  title.textContent = "Готово";
  setHeaderControl("close", {
    screenLabel: "Кредиты начислены",
    onBack: () => loadCreditGrantHome(false),
  });
  const card = element("section", undefined, "credit-grant-success");
  card.append(
    element("span", "✓", "credit-grant-success-icon"),
    element("h2", `Начислено ${receipt.amount} кредитов`),
    element("p", receipt.recipient.display_name, "muted"),
    element("strong", `${receipt.recipient.credit_balance} кредитов на балансе`, "credit-grant-total"),
    element("p", "Опыт не изменился. Операция записана в историю.", "credit-grant-note"),
  );
  const again = element("button", "Начислить ещё", "secondary");
  again.type = "button";
  again.addEventListener("click", () => loadCreditGrantHome(false));
  const historyButton = element("button", "Открыть историю", "primary");
  historyButton.type = "button";
  historyButton.addEventListener("click", () => loadCreditGrantHistory());
  card.append(historyButton, again);
  replaceContent(card);
  creditGrantDraft = null;
}

async function loadCreditGrantHistory(push = true, cursor = null) {
  const revision = ++screenRevision;
  if (push) history.pushState({ screen: "credit-grant-history" }, "", "#/moderation/credits/history");
  setNavigation("moderation", true);
  heading.classList.add("credit-grant-heading");
  title.textContent = "История начислений";
  setHeaderControl("back", { onBack: () => loadCreditGrantHome(false) });
  replaceContent(element("p", "Загружаем операции…", "compact-empty"));
  try {
    const page = await getJson(
      `/api/v1/administration/credits/history?limit=30${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
    );
    if (revision !== screenRevision) return;
    if (!page.items.length) {
      replaceContent(element("p", "Начислений пока нет.", "compact-empty"));
      return;
    }
    const list = element("div", undefined, "credit-history-list");
    for (const item of page.items) {
      const card = element("article", undefined, "credit-history-card");
      const top = element("div", undefined, "credit-history-top");
      top.append(
        element("strong", item.recipient.display_name),
        element("strong", `+${item.amount}`, "credit-history-amount"),
      );
      card.append(
        top,
        element(
          "p",
          `${item.recipient.telegram_username ? `@${item.recipient.telegram_username}` : "без username"} · ${memberDateFormatter({ dateStyle: "short", timeStyle: "short" }).format(new Date(item.created_at))}`,
          "muted",
        ),
        element("p", item.reason, "credit-history-reason"),
        element("p", `Начислил: ${item.actor_display_name}`, "muted"),
      );
      list.append(card);
    }
    const nodes = [list];
    if (page.next_cursor) {
      const more = element("button", "Показать ещё", "secondary");
      more.type = "button";
      more.addEventListener("click", () => loadCreditGrantHistory(false, page.next_cursor));
      nodes.push(more);
    }
    replaceContent(...nodes);
  } catch {
    if (revision !== screenRevision) return;
    replaceContent(element("p", "Не удалось загрузить историю.", "compact-empty"));
  }
}

function administratorRights(permissions, { disabled = false, allowed = null } = {}) {
  const rights = element("div", undefined, "admin-rights");
  for (const [id, name, description] of administratorPermissionDetails) {
    const row = element("label", undefined, "admin-right-row");
    if (id === "administrator_management") row.classList.add("is-elevated");
    const copy = element("span");
    copy.append(
      element("span", name, "admin-right-name"),
      element("span", description, "admin-right-description"),
    );
    const control = element("span", undefined, "admin-switch");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.dataset.permission = id;
    input.checked = permissions.includes(id);
    input.disabled = disabled || (allowed !== null && !allowed.includes(id));
    control.append(input, element("span", undefined, "admin-switch-track"));
    row.append(copy, control);
    rights.append(row);
  }
  return rights;
}

const selectedAdministratorPermissions = () => [
  ...content.querySelectorAll("[data-permission]:checked"),
].map((input) => input.dataset.permission);

function showAdministratorToast(message) {
  shell.querySelector(".admin-toast")?.remove();
  const toast = element("div", message, "admin-toast");
  toast.setAttribute("role", "status");
  shell.append(toast);
  setTimeout(() => toast.remove(), 2600);
}

function administratorSheet(trigger, build) {
  shell.querySelector(".admin-sheet-backdrop")?.remove();
  const backdrop = element("section", undefined, "admin-sheet-backdrop");
  const sheet = element("section", undefined, "admin-sheet");
  sheet.setAttribute("role", "dialog");
  sheet.setAttribute("aria-modal", "true");
  const close = () => {
    backdrop.remove();
    trigger?.focus({ preventScroll: true });
  };
  build(sheet, close);
  backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop) close();
  });
  backdrop.append(sheet);
  shell.append(backdrop);
  queueMicrotask(() => sheet.querySelector("button, textarea")?.focus({ preventScroll: true }));
}

async function loadAdministrationAccess(push = true) {
  const revision = ++screenRevision;
  if (push) history.pushState({ screen: "moderation-access" }, "", "#/moderation/access");
  setNavigation("moderation", false);
  title.textContent = "Модерация";
  back.classList.add("hidden");
  replaceContent(moderationTabs("access"), element("p", "Загружаем права…", "compact-empty"));
  try {
    const overview = await getJson("/api/v1/administration");
    if (revision !== screenRevision) return;
    const summary = element("section", undefined, "admin-summary");
    const copy = element("div");
    copy.append(
      element("h2", "Ваш доступ"),
      element("p", "Полномочия, доступные в интерфейсе модерации"),
    );
    summary.append(copy);
    const notice = element(
      "div",
      overview.can_appoint
        ? "Вы можете назначать администраторов в пределах правил делегирования."
        : "Изменить набор прав может владелец или назначивший вас администратор.",
      "admin-notice",
    );
    replaceContent(
      moderationTabs("access"),
      summary,
      notice,
      administratorRights(overview.actor_permissions, { disabled: true }),
    );
  } catch {
    if (revision === screenRevision) {
      replaceContent(
        moderationTabs("access"),
        element("p", "Не удалось загрузить права доступа.", "status"),
      );
    }
  }
}

function administratorCard(person) {
  const button = element("button", undefined, "admin-person");
  button.type = "button";
  button.dataset.administratorId = person.member_id;
  const permissionNames = administratorPermissionNames(person.permissions);
  button.append(
    personAvatar(person),
    administratorIdentity(
      person,
      person.is_owner
        ? "все права · суперадминистратор"
        : `${permissionNames.slice(0, 2).join(", ") || "без прав"}${permissionNames.length > 2 ? ` · ${permissionNames.length} права` : ""}`,
    ),
    element("span", person.is_owner ? "Владелец" : "Администратор", `admin-badge${person.is_owner ? " is-owner" : ""}`),
  );
  button.addEventListener("click", () => showAdministratorRights(person.member_id));
  return button;
}

async function loadAdministrationTeam(push = true) {
  const revision = ++screenRevision;
  if (push) history.pushState({ screen: "moderation-team" }, "", "#/moderation/team");
  setNavigation("moderation", false);
  title.textContent = "Модерация";
  back.classList.add("hidden");
  replaceContent(moderationTabs("team"), element("p", "Загружаем команду…", "compact-empty"));
  try {
    const overview = await getJson("/api/v1/administration");
    if (revision !== screenRevision) return;
    const summary = element("section", undefined, "admin-summary");
    const copy = element("div");
    copy.append(
      element("h2", "Команда"),
      element("p", "Администраторы и их полномочия"),
    );
    summary.append(copy, element("span", String(overview.items.length), "admin-count"));
    const nodes = [moderationTabs("team"), summary];
    const canInvite = overview.actor_permissions.includes("member_invitation");
    let invitationOverview = null;
    if (canInvite) {
      try {
        invitationOverview = await getJson("/api/v1/administration/invitations?limit=50");
      } catch {
        invitationOverview = null;
      }
      if (revision !== screenRevision) return;
      const invite = element("button", "+ Пригласить участника", "primary admin-full");
      invite.type = "button";
      invite.addEventListener("click", () => showPersonalInvitationCreate());
      nodes.push(invite);
    }
    if (overview.can_appoint) {
      const add = element(
        "button",
        "+ Назначить администратора",
        `${canInvite ? "secondary" : "primary"} admin-full`,
      );
      add.type = "button";
      add.addEventListener("click", () => loadAdministratorCandidates());
      nodes.push(add);
    }
    if (canInvite) {
      const invitations = element("button", undefined, "admin-invitation-summary");
      invitations.type = "button";
      const icon = element("span", "↗", "admin-invitation-icon");
      const invitationCopy = element("span", undefined, "admin-invitation-copy");
      invitationCopy.append(
        element("strong", "Приглашения"),
        element(
          "span",
          invitationOverview === null
            ? "Открыть список"
            : `${invitationOverview.pending_count} ожидают ответа`,
        ),
      );
      invitations.append(icon, invitationCopy, element("span", "›", "admin-chevron"));
      invitations.addEventListener("click", () => loadPersonalInvitations());
      nodes.push(invitations);
    }
    const list = element("div", undefined, "admin-list");
    for (const person of overview.items) list.append(administratorCard(person));
    nodes.push(
      list,
      element(
        "div",
        "Назначать администраторов можно только из активных участников сообщества. Владелец всегда имеет все права.",
        "admin-notice",
      ),
    );
    replaceContent(...nodes);
  } catch {
    if (revision === screenRevision) {
      replaceContent(
        moderationTabs("team"),
        element("p", "Управление командой недоступно для этого аккаунта.", "status"),
      );
    }
  }
}

const personalInvitationStatus = {
  waiting: "Ожидает",
  joined: "Вступил",
  expired: "Истекло",
  revoked: "Отозвано",
};

const personalInvitationDate = (value) => new Intl.DateTimeFormat("ru", {
  day: "numeric",
  month: "long",
}).format(new Date(value));

function renderInvitationMembershipResources(container, state) {
  container.replaceChildren();
  const heading = element("div", undefined, "admin-invitation-condition-heading");
  const hasCoreResource = state.items.some((resource) => resource.required);
  heading.append(
    element("strong", "Условия вступления"),
    element(
      "span",
      hasCoreResource ? "Обязательный чат уже включён" : "При необходимости добавьте ресурс",
    ),
  );
  container.append(heading);
  for (const resource of state.items) {
    const row = element("label", undefined, "admin-invitation-condition");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.disabled = resource.required;
    input.checked = resource.required || state.selected.has(resource.resource_id);
    if (resource.resource_id) {
      input.addEventListener("change", () => {
        if (input.checked) state.selected.add(resource.resource_id);
        else state.selected.delete(resource.resource_id);
      });
    }
    const copy = element("span");
    copy.append(
      element("strong", resource.title),
      element("small", resource.required ? "Обязательно для всех" : "Добавить к приглашению"),
    );
    row.append(input, copy);
    container.append(row);
  }
  if (state.canAdd) {
    const add = element("button", "+ Добавить ресурс", "admin-text-action admin-resource-add");
    add.type = "button";
    add.addEventListener("click", () => {
      administratorSheet(add, (sheet, close) => {
        sheet.append(
          element("h2", "Добавить Telegram-ресурс"),
          element("p", "Бот должен быть администратором этого чата или канала."),
        );
        const chat = document.createElement("input");
        chat.className = "admin-search";
        chat.placeholder = "@username чата или его ID";
        const link = document.createElement("input");
        link.className = "admin-search";
        link.placeholder = "https://t.me/...";
        const status = element("p", "", "status hidden");
        const controls = element("div", undefined, "admin-sheet-actions");
        const cancel = element("button", "Отмена", "secondary");
        const save = element("button", "Добавить", "primary");
        cancel.type = save.type = "button";
        cancel.addEventListener("click", close);
        save.addEventListener("click", async () => {
          save.disabled = cancel.disabled = true;
          status.className = "status";
          status.textContent = "Проверяем доступ бота…";
          try {
            const resource = await submissionRequest(
              "/api/v1/administration/membership-resources",
              "POST",
              newOperationKey(),
              { telegram_chat: chat.value.trim(), join_url: link.value.trim() },
            );
            state.items.push(resource);
            state.selected.add(resource.resource_id);
            close();
            renderInvitationMembershipResources(container, state);
          } catch (error) {
            status.textContent = error.message === "membership_check_unavailable"
              ? "Telegram временно не отвечает. Повторите позже."
              : "Не удалось добавить. Проверьте чат, ссылку и права бота.";
            save.disabled = cancel.disabled = false;
          }
        });
        controls.append(cancel, save);
        sheet.append(chat, link, status, controls);
        queueMicrotask(() => chat.focus({ preventScroll: true }));
      });
    });
    container.append(add);
  }
}

async function loadInvitationMembershipResources(container, state) {
  try {
    const response = await fetchJson("/api/v1/administration/membership-resources");
    state.items = [...response.items];
    state.canAdd = response.can_add;
    renderInvitationMembershipResources(container, state);
  } catch {
    container.replaceChildren(
      element("p", "Не удалось загрузить условия вступления.", "status"),
    );
  }
}

function showPersonalInvitationCreate(push = true, invitation = null) {
  screenRevision += 1;
  if (push) {
    history.pushState(
      { screen: "personal-invitation-create" },
      "",
      "#/moderation/invitations/new",
    );
  }
  setNavigation("moderation", true);
  heading.classList.add("admin-rights-heading");
  title.textContent = "Пригласить участника";
  if (invitation) {
    history.replaceState(
      { screen: "personal-invitation-create", invitation },
      "",
      "#/moderation/invitations/new",
    );
    const card = element("section", undefined, "admin-invitation-ready");
    card.append(
      element("span", "✓", "admin-invitation-ready-icon"),
      element("h2", "Приглашение готово"),
      element("strong", `@${invitation.telegram_username}`),
      element(
        "p",
        `Одно использование · действует до ${personalInvitationDate(invitation.expires_at)}`,
      ),
    );
    const send = element(
      "button",
      `Написать @${invitation.telegram_username}`,
      "primary admin-full",
    );
    const copy = element("button", "Скопировать ссылку", "secondary admin-full");
    const list = element("button", "Все приглашения", "admin-text-action");
    const status = element("p", "", "admin-invitation-action-status");
    status.setAttribute("aria-live", "polite");
    send.type = copy.type = list.type = "button";
    send.addEventListener("click", () => {
      const message = `Вас приглашают в Комьюнити\n${invitation.invitation_url}`;
      const directUrl = `https://t.me/${encodeURIComponent(invitation.telegram_username)}?text=${encodeURIComponent(message)}`;
      if (globalThis.Telegram?.WebApp?.openTelegramLink) {
        globalThis.Telegram.WebApp.openTelegramLink(directUrl);
      } else {
        globalThis.open(directUrl, "_blank", "noopener,noreferrer");
      }
      status.textContent = `Открываем чат с @${invitation.telegram_username}.`;
    });
    copy.addEventListener("click", async () => {
      try {
        if (!navigator.clipboard?.writeText) throw new Error("clipboard_unavailable");
        await navigator.clipboard.writeText(invitation.invitation_url);
        copy.textContent = "Ссылка скопирована";
        status.textContent = "Можно вставить её в любое сообщение.";
      } catch {
        status.textContent = "Не удалось скопировать. Откройте чат кнопкой выше.";
      }
    });
    list.addEventListener("click", () => loadPersonalInvitations());
    replaceContent(
      card,
      send,
      copy,
      status,
      list,
      element("div", "После регистрации участник войдёт сразу, без ожидания модератора.", "admin-notice"),
    );
    return;
  }
  const form = element("form", undefined, "admin-invitation-form");
  const label = element("label", undefined, "admin-field-label");
  label.append(element("span", "Telegram username"));
  const input = document.createElement("input");
  input.className = "admin-search";
  input.name = "telegram_username";
  input.placeholder = "username или @username";
  input.autocomplete = "off";
  input.spellcheck = false;
  label.append(input);
  const helper = element(
    "p",
    "Можно ввести имя с @ или без. Ссылка сработает только для этого аккаунта.",
    "admin-invitation-helper",
  );
  const notice = element(
    "div",
    "Пользователь просто откроет ссылку. Вводить код и ждать одобрения не потребуется.",
    "admin-notice",
  );
  const resourceState = { items: [], selected: new Set(), canAdd: false };
  const resources = element("section", undefined, "admin-invitation-conditions");
  resources.append(element("p", "Загружаем условия…", "compact-empty"));
  void loadInvitationMembershipResources(resources, resourceState);
  const submit = element("button", "Создать ссылку", "primary admin-full");
  submit.type = "submit";
  const status = element("p", "", "status hidden");
  status.setAttribute("aria-live", "polite");
  let operationKey = null;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const username = input.value.trim();
    if (!/^@?[A-Za-z0-9_]{5,32}$/.test(username)) {
      status.className = "status";
      status.textContent = "Введите Telegram username: от 5 до 32 символов.";
      input.focus();
      return;
    }
    submit.disabled = true;
    status.className = "status";
    status.textContent = "Создаём персональную ссылку…";
    operationKey ||= newOperationKey();
    try {
      const invitation = await submissionRequest(
        "/api/v1/administration/invitations",
        "POST",
        operationKey,
        {
          telegram_username: username,
          required_resource_ids: [...resourceState.selected],
        },
      );
      clearJsonCache();
      showPersonalInvitationCreate(false, invitation);
    } catch (error) {
      status.textContent = error.status === 403
        ? "У вас нет права приглашать участников."
        : error.status === 503
          ? "Приглашения временно недоступны. Попробуйте позже."
          : "Не удалось создать приглашение. Повторите попытку.";
      submit.disabled = false;
    }
  });
  form.append(label, helper, resources, notice, submit, status);
  replaceContent(form, element("div", "Ссылка действует 7 дней и только один раз.", "admin-notice"));
  queueMicrotask(() => input.focus({ preventScroll: true }));
}

function personalInvitationRow(invitation, refresh) {
  const row = element("article", undefined, "admin-invitation-row");
  const copy = element("div", undefined, "admin-invitation-row-copy");
  copy.append(
    element("strong", `@${invitation.telegram_username}`),
    element(
      "span",
      invitation.status === "joined"
        ? `${invitation.redeemed_display_name || "Участник"} · вступил ${personalInvitationDate(invitation.redeemed_at)}`
        : `Создал(а) ${invitation.created_by_display_name} · ${personalInvitationDate(invitation.created_at)}`,
    ),
  );
  const actions = element("div", undefined, "admin-invitation-row-actions");
  const badge = element(
    "span",
    personalInvitationStatus[invitation.status] || invitation.status,
    `admin-invitation-status is-${invitation.status}`,
  );
  actions.append(badge);
  if (invitation.status === "waiting") {
    const revoke = element("button", "Отозвать", "admin-invitation-revoke");
    revoke.type = "button";
    let operationKey = null;
    revoke.addEventListener("click", () => {
      administratorSheet(revoke, (sheet, close) => {
        sheet.append(
          element("h2", "Отозвать приглашение?"),
          element("p", `Ссылка для @${invitation.telegram_username} перестанет работать.`),
        );
        const controls = element("div", undefined, "admin-sheet-actions");
        const cancel = element("button", "Оставить", "secondary");
        const confirm = element("button", "Отозвать", "admin-danger-button");
        cancel.type = confirm.type = "button";
        cancel.addEventListener("click", close);
        confirm.addEventListener("click", async () => {
          cancel.disabled = confirm.disabled = true;
          operationKey ||= newOperationKey();
          try {
            await submissionRequest(
              `/api/v1/administration/invitations/${encodeURIComponent(invitation.invitation_id)}/revoke`,
              "POST",
              operationKey,
              {},
            );
            clearJsonCache();
            close();
            await refresh();
            showAdministratorToast("Приглашение отозвано");
          } catch {
            confirm.disabled = cancel.disabled = false;
          }
        });
        controls.append(cancel, confirm);
        sheet.append(controls);
      });
    });
    actions.append(revoke);
  }
  row.append(copy, actions);
  return row;
}

async function loadPersonalInvitations(push = true) {
  const revision = ++screenRevision;
  if (push) {
    history.pushState(
      { screen: "personal-invitations" },
      "",
      "#/moderation/invitations",
    );
  }
  setNavigation("moderation", true);
  heading.classList.add("admin-rights-heading");
  title.textContent = "Приглашения";
  replaceContent(element("p", "Загружаем приглашения…", "compact-empty"));
  try {
    const overview = await fetchJson("/api/v1/administration/invitations?limit=50");
    if (revision !== screenRevision) return;
    const rows = element("div", undefined, "admin-invitation-list");
    const refresh = () => loadPersonalInvitations(false);
    for (const invitation of overview.items) rows.append(personalInvitationRow(invitation, refresh));
    if (!overview.items.length) {
      rows.append(element("p", "Приглашений пока нет.", "compact-empty"));
    }
    replaceContent(
      rows,
      element(
        "div",
        "Потеряли ссылку — отзовите приглашение и создайте новое.",
        "admin-notice",
      ),
    );
  } catch {
    if (revision === screenRevision) {
      replaceContent(element("p", "Не удалось загрузить приглашения.", "status"));
    }
  }
}

function candidateCard(person) {
  const button = element("button", undefined, "admin-person");
  button.type = "button";
  button.append(
    personAvatar(person),
    administratorIdentity(person, "активный участник"),
    element("span", "›", "admin-chevron"),
  );
  button.addEventListener("click", () => showAdministratorRights(person.member_id, true, person));
  return button;
}

async function loadAdministratorCandidates(push = true, initialQuery = "") {
  const revision = ++screenRevision;
  if (push) history.pushState({ screen: "administrator-candidates" }, "", "#/moderation/administrators/new");
  setNavigation("moderation", true);
  title.textContent = "Новый администратор";
  const intro = element("section", undefined, "admin-summary");
  const copy = element("div");
  copy.append(
    element("h2", "Выберите участника"),
    element("p", "Назначить можно только активного участника сообщества."),
  );
  intro.append(copy);
  const search = document.createElement("input");
  search.className = "admin-search";
  search.type = "search";
  search.placeholder = "Имя или @username";
  search.setAttribute("aria-label", "Поиск участника");
  search.value = initialQuery;
  const list = element("div", undefined, "admin-list");
  replaceContent(intro, search, element("p", "Активные участники", "admin-section-label"), list);
  const fetchCandidates = async () => {
    const query = search.value.trim();
    try {
      const page = await getJson(`/api/v1/administration/candidates?limit=30${query ? `&query=${encodeURIComponent(query)}` : ""}`);
      if (revision !== screenRevision) return;
      list.replaceChildren(...page.items.map(candidateCard));
      if (!page.items.length) list.append(element("p", "Участники не найдены.", "compact-empty"));
    } catch {
      if (revision === screenRevision) list.replaceChildren(element("p", "Не удалось загрузить участников.", "status"));
    }
  };
  let searchTimer = null;
  search.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(fetchCandidates, 250);
  });
  await fetchCandidates();
}

function administratorProfile(person, subtitle) {
  const card = element("section", undefined, "admin-profile-card");
  card.append(personAvatar(person), administratorIdentity(person, subtitle));
  return card;
}

async function showAdministratorRights(memberId, isNew = false, candidate = null, push = true) {
  const revision = ++screenRevision;
  if (push) {
    history.pushState(
      { screen: "administrator-rights", memberId, isNew, candidate },
      "",
      isNew ? `#/moderation/administrators/new/${memberId}` : `#/moderation/administrators/${memberId}`,
    );
  }
  setNavigation("moderation", true);
  heading.classList.add("admin-rights-heading");
  title.textContent = "Права";
  replaceContent(element("p", "Загружаем права…", "compact-empty"));
  try {
    const [person, overview] = await Promise.all([
      isNew ? Promise.resolve(candidate) : getJson(`/api/v1/administration/${encodeURIComponent(memberId)}`),
      getJson("/api/v1/administration"),
    ]);
    if (revision !== screenRevision || !person) return;
    const owner = !isNew && person.is_owner;
    const allowed = owner
      ? person.permissions
      : overview.actor_permissions.filter((permission) => (
        permission !== "administrator_management"
        || overview.can_delegate_administrator_management
      ));
    const nodes = [
      administratorProfile(
        person,
        owner ? "суперадминистратор" : isNew ? "активный участник" : "администратор",
      ),
    ];
    if (owner) {
      nodes.push(element("div", "Это владелец сообщества. У него всегда включены все права; изменить или снять их нельзя.", "admin-notice"));
    } else if (isNew) {
      nodes.push(element("div", "Новый администратор получит только выбранные права. Их можно изменить позже.", "admin-notice"));
    } else if (person.appointed_by) {
      const date = person.appointed_at ? new Date(person.appointed_at).toLocaleDateString("ru-RU") : "дата не указана";
      nodes.push(element("div", `Назначил ${person.appointed_by.display_name} · ${date}`, "admin-audit-note"));
    }
    nodes.push(administratorRights(person.permissions || [], { disabled: owner || (!isNew && !person.can_edit), allowed }));
    if (!owner && (isNew || person.can_edit)) {
      const actions = element("div", undefined, "admin-sticky-actions");
      const save = element("button", isNew ? "Назначить администратором" : "Сохранить права", "primary admin-full");
      save.type = "button";
      save.addEventListener("click", () => confirmAdministratorChange(save, person, isNew));
      actions.append(save);
      if (!isNew && person.can_demote) {
        const demote = element("button", "Снять права администратора", "admin-danger-button admin-full");
        demote.type = "button";
        demote.addEventListener("click", () => confirmAdministratorDemotion(demote, person));
        actions.append(demote);
      }
      nodes.push(actions);
    }
    replaceContent(...nodes);
  } catch {
    if (revision === screenRevision) replaceContent(element("p", "Не удалось загрузить права администратора.", "status"));
  }
}

function confirmAdministratorChange(trigger, person, isNew) {
  const permissions = selectedAdministratorPermissions();
  if (!permissions.length) {
    showAdministratorToast("Выберите хотя бы одно право");
    return;
  }
  administratorSheet(trigger, (sheet, close) => {
    const headingText = isNew ? "Назначить администратора?" : "Сохранить новые права?";
    const headingNode = element("h2", headingText);
    sheet.append(
      headingNode,
      administratorProfile(person, person.telegram_username ? `@${person.telegram_username}` : "без username"),
      element("p", "Пользователь получит следующие права:"),
    );
    const list = element("ul");
    for (const name of administratorPermissionNames(permissions)) list.append(element("li", name));
    sheet.append(list);
    if (permissions.includes("administrator_management")) {
      sheet.append(element("div", "Право назначения администраторов является повышенным. Передавать его дальше пользователь не сможет.", "admin-notice"));
    }
    const actions = element("div", undefined, "admin-sheet-actions");
    const cancel = element("button", "Отмена", "secondary");
    cancel.type = "button";
    cancel.addEventListener("click", close);
    const confirm = element("button", isNew ? "Назначить" : "Сохранить", "primary");
    confirm.type = "button";
    let operationKey = null;
    confirm.addEventListener("click", async () => {
      cancel.disabled = true;
      confirm.disabled = true;
      operationKey ||= newOperationKey();
      try {
        await submissionRequest(
          `/api/v1/administration/${encodeURIComponent(person.member_id)}`,
          isNew ? "POST" : "PUT",
          operationKey,
          { permissions },
        );
        close();
        history.replaceState({ screen: "moderation-team" }, "", "#/moderation/team");
        await loadAdministrationTeam(false);
        showAdministratorToast(isNew ? `${person.display_name} назначен администратором` : "Права администратора сохранены");
      } catch (error) {
        if (!retryableSubmissionError(error)) operationKey = null;
        cancel.disabled = false;
        confirm.disabled = false;
        showAdministratorToast("Не удалось сохранить права");
      }
    });
    actions.append(cancel, confirm);
    sheet.append(actions);
  });
}

function confirmAdministratorDemotion(trigger, person) {
  administratorSheet(trigger, (sheet, close) => {
    sheet.append(
      element("h2", "Снять права администратора?"),
      administratorProfile(person, "останется участником сообщества"),
    );
    const label = element("label", "Причина", "admin-field-label");
    const reason = document.createElement("textarea");
    reason.className = "admin-textarea";
    reason.maxLength = 500;
    reason.placeholder = "Например: изменение зоны ответственности";
    label.append(reason);
    sheet.append(
      label,
      element("div", "Административные действия станут недоступны сразу. Профиль и история участника сохранятся.", "admin-notice"),
    );
    const actions = element("div", undefined, "admin-sheet-actions");
    const cancel = element("button", "Отмена", "secondary");
    cancel.type = "button";
    cancel.addEventListener("click", close);
    const confirm = element("button", "Снять права", "admin-danger-button");
    confirm.type = "button";
    confirm.disabled = true;
    reason.addEventListener("input", () => { confirm.disabled = reason.value.trim().length < 3; });
    let operationKey = null;
    confirm.addEventListener("click", async () => {
      cancel.disabled = true;
      confirm.disabled = true;
      operationKey ||= newOperationKey();
      try {
        await submissionRequest(
          `/api/v1/administration/${encodeURIComponent(person.member_id)}/demote`,
          "POST",
          operationKey,
          { reason: reason.value.trim() },
        );
        close();
        history.replaceState({ screen: "moderation-team" }, "", "#/moderation/team");
        await loadAdministrationTeam(false);
        showAdministratorToast("Права администратора сняты");
      } catch (error) {
        if (!retryableSubmissionError(error)) operationKey = null;
        cancel.disabled = false;
        confirm.disabled = false;
        showAdministratorToast("Не удалось снять права");
      }
    });
    actions.append(cancel, confirm);
    sheet.append(actions);
  });
}

function showCommunityReviewQueue(reviews, revision) {
  if (revision !== screenRevision) return;
  setNavigation("moderation", false);
  title.textContent = "Модерация";
  back.classList.add("hidden");
  const boundary = element("section", undefined, "state-view");
  boundary.dataset.screenId = "S04Q";
  boundary.dataset.uiEngine = "concept-05";
  boundary.dataset.state = reviews.length ? "content" : "empty";
  boundary.append(moderationTabs("community-reviews"));
  const heading = element("section", undefined, "admin-summary");
  const copy = element("div");
  copy.append(
    element("h2", "Задания сообщества"),
    element("p", "Результаты, ожидающие решения"),
  );
  heading.append(copy, element("span", String(reviews.length), "admin-count"));
  boundary.append(heading);
  if (!reviews.length) {
    boundary.append(element("p", "Заданий на проверку нет", "compact-empty"));
    replaceContent(boundary);
    return;
  }
  const list = element("ul", undefined, "list moderation-case-list");
  for (const review of reviews) {
    const card = element("button", undefined, "card moderation-card moderation-case-card");
    card.type = "button";
    card.dataset.assignmentId = review.id;
    const copyNode = element("span", undefined, "moderation-card-copy");
    const top = element("span", undefined, "moderation-card-topline");
    top.append(
      element("span", "На проверке", "chip"),
      element("span", "Сообщество", "chip muted-chip"),
    );
    const submitted = element("span", "Отправлено: ", "meta");
    submitted.append(time(review.submitted_at));
    copyNode.append(
      top,
      element("h3", review.task_title),
      element("span", `Исполнитель: ${review.performer_display_name}`, "meta"),
      submitted,
    );
    card.append(copyNode, element("span", "›", "moderation-card-chevron"));
    card.addEventListener("click", () => showCreatedReview(review.id, true, "moderation-community"));
    const row = element("li");
    row.append(card);
    list.append(row);
  }
  boundary.append(list);
  replaceContent(boundary);
}

async function loadCommunityReviews(push = true) {
  const revision = ++screenRevision;
  if (push) {
    history.pushState(
      { screen: "moderation-community-reviews" },
      "",
      "#/moderation/community-reviews",
    );
  }
  setNavigation("moderation", false);
  title.textContent = "Модерация";
  back.classList.add("hidden");
  replaceContent(
    moderationTabs("community-reviews"),
    element("p", "Загружаем задания…", "compact-empty"),
  );
  try {
    const page = await getJson("/api/v1/moderation/community-reviews");
    if (revision !== screenRevision) return;
    showCommunityReviewQueue(page.items, revision);
  } catch {
    if (revision !== screenRevision) return;
    const retry = element("button", "Повторить", "primary");
    retry.type = "button";
    retry.addEventListener("click", () => loadCommunityReviews(false));
    replaceContent(
      moderationTabs("community-reviews"),
      element("p", "Не удалось загрузить задания на проверку.", "status"),
      retry,
    );
  }
}

function showModerationCases(cases, revision) {
  if (revision !== screenRevision) return;
  const disputes = cases.filter((item) => item.case_type === "dispute" && item.status === "open");
  const focusedCaseId = returnFocusModerationCaseId
    || document.activeElement?.closest?.(".moderation-card")?.dataset.caseId;
  setNavigation("moderation", false);
  title.textContent = "Модерация";
  back.classList.add("hidden");
  const boundary = element("section", undefined, "state-view");
  boundary.dataset.screenId = "S01";
  boundary.dataset.uiEngine = "concept-05";
  boundary.dataset.state = disputes.length ? "content" : "empty";
  boundary.append(moderationTabs("disputes", disputes.length));

  if (!disputes.length) {
    boundary.append(element("p", "Открытых споров нет", "compact-empty"));
    replaceContent(boundary);
    return;
  } else {
    const list = element("ul", undefined, "list moderation-case-list");
    let focusTarget = null;
    for (const item of disputes) {
      const actionable = item.case_type === "dispute" && item.status === "open";
      const card = element(actionable ? "button" : "article", undefined, "card moderation-card moderation-case-card");
      card.dataset.caseId = item.id;
      if (actionable) card.type = "button";
      const copy = element("span", undefined, "moderation-card-copy");
      const top = element("span", undefined, "moderation-card-topline");
      top.append(element("span", moderationStatus(item.status), "chip"));
      if (item.case_type !== "dispute") top.append(element("span", "Проверка", "chip muted-chip"));
      const opened = element("span", "Открыт: ", "meta");
      opened.append(time(item.opened_at));
      copy.append(top, element("h3", moderationCaseType(item.case_type)), opened);
      if (item.current_code) copy.append(element("span", "Решение: " + item.current_code, "meta"));
      card.append(copy);
      if (actionable) card.append(element("span", "›", "moderation-card-chevron"));
      if (actionable) {
        card.addEventListener("click", () => showModerationCase(item.id));
        if (item.id === focusedCaseId) focusTarget = card;
      }
      const row = element("li");
      row.append(card);
      list.append(row);
    }
    boundary.append(list);
    replaceContent(boundary);
    focusTarget?.focus({ preventScroll: true });
    returnFocusModerationCaseId = null;
    return;
  }
  replaceContent(boundary);
  returnFocusModerationCaseId = null;
}

async function loadModeration(push = true) {
  const revision = ++screenRevision;
  returnFocusModeration = true;
  if (push) history.replaceState({ screen: "moderation" }, "", presentationLocationFor("S01"));
  setNavigation("moderation", false);
  title.textContent = "Модерация";
  back.classList.add("hidden");
  replaceContent(
    moderationTabs("disputes"),
    element("p", "Загружаем споры…", "compact-empty"),
  );
  try {
    let casePage = await getJson("/api/v1/moderation/cases?limit=20", (refreshed) => {
      casePage = refreshed;
      if (revision === screenRevision) showModerationCases(casePage.items, revision);
    });
    if (revision !== screenRevision) return;
    showModerationCases(casePage.items, revision);
  } catch (error) {
    if (revision !== screenRevision) return;
    const retry = element("button", "Повторить", "primary");
    retry.type = "button";
    retry.addEventListener("click", () => loadModeration(false));
    replaceContent(moderationTabs("disputes"), element("p", "Открытые споры", "screen-subtitle"), ...moderationError(error.message, retry));
  }
}

async function showModerationCase(caseId, push = true) {
  const revision = ++screenRevision;
  returnFocusModerationCaseId = caseId;
  if (push) {
    history.pushState(
      { screen: "moderation-case", caseId },
      "",
      presentationLocationFor("S02", caseId),
    );
  }
  setNavigation("moderation", true);
  title.textContent = "Решение по спору";
  setHeaderControl("close", { label: "Закрыть спор", screenLabel: "Решение по спору" });
  replaceContent(element("p", "Загружаем спор…", "status muted"));
  back.focus({ preventScroll: true });
  try {
    const dispute = await getJson(
      "/api/v1/moderation/cases/" + encodeURIComponent(caseId),
    );
    if (revision !== screenRevision) return;
    const detail = element("article", undefined, "card detail moderation-resolution-card");
    const reward = Number(dispute.credit_reward_per_performer);
    const rewardRemainder = Math.abs(reward) % 100;
    const rewardLastDigit = rewardRemainder % 10;
    const rewardUnit = rewardRemainder > 10 && rewardRemainder < 20
      ? "кредитов"
      : rewardLastDigit === 1
        ? "кредит"
        : rewardLastDigit >= 2 && rewardLastDigit <= 4 ? "кредита" : "кредитов";
    const summary = element("header", undefined, "moderation-dispute-summary");
    const facts = element("div", undefined, "moderation-dispute-facts");
    facts.append(
      element(
        "span",
        dispute.task_origin === "community" ? "От сообщества" : "От участника",
        "moderation-dispute-fact",
      ),
      element(
        "span",
        `${reward} ${rewardUnit}`,
        "moderation-dispute-fact is-reward",
      ),
    );
    summary.append(element("h2", dispute.task_title), facts);

    const context = element("section", undefined, "moderation-dispute-context");
    const disputeReason = element("section", undefined, "moderation-dispute-copy");
    disputeReason.append(
      element("h3", "Причина спора"),
      element("p", dispute.dispute_reason),
    );
    context.append(disputeReason);
    if (dispute.result_summary) {
      const result = element("section", undefined, "moderation-dispute-copy");
      result.append(element("h3", "Результат"), element("p", dispute.result_summary));
      context.append(result);
    }
    detail.append(summary, context);

    const form = element("form", undefined, "moderation-decision-form");
    form.append(element("h3", "Решение модератора", "moderation-decision-title"));
    const label = element("label", undefined, "moderation-form-field");
    label.append(element("span", "Решение"));
    const select = element("select");
    select.name = "resolution";
    for (const code of dispute.allowed_resolution_codes) {
      const option = element("option", resolutionLabels[code] || code);
      option.value = code;
      select.append(option);
    }
    label.append(select);
    const reasonLabel = element("label", undefined, "moderation-form-field");
    reasonLabel.append(element("span", "Причина решения"));
    const reason = element("textarea");
    reason.name = "reason";
    reason.required = true;
    reason.rows = 3;
    reason.maxLength = 1000;
    reason.placeholder = "Коротко объясните принятое решение";
    reasonLabel.append(reason);
    const status = element("p", "", "status hidden");
    status.setAttribute("aria-live", "polite");
    const review = element("button", "Проверить решение", "primary");
    review.type = "submit";
    let operationKey = null;
    const actions = element("div", undefined, "moderation-decision-actions");
    actions.append(status, review);
    form.append(label, reasonLabel, actions);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const normalizedReason = reason.value.trim();
      if (!normalizedReason) {
        reason.focus({ preventScroll: true });
        return;
      }
      const resolution = select.value;
      history.pushState(
        { screen: "moderation-confirm", caseId },
        "",
        presentationLocationFor("S03", caseId),
      );
      showActionConfirmation({
        screenId: "S03",
        headingText: "Подтвердить решение",
        description: (resolutionLabels[resolution] || resolution) + ". " + normalizedReason,
        confirmLabel: "Применить решение",
        transitionId: "PE-068",
        transitionTrigger: "authoritative_resolution_success",
        onEdit: () => history.back(),
        onConfirm: async ({ confirm, edit, status: actionStatus }) => {
        edit.disabled = true;
        confirm.disabled = true;
        actionStatus.className = "status";
        actionStatus.textContent = "Применяем решение…";
        operationKey ||= newOperationKey();
        try {
          await submissionRequest(
            "/api/v1/moderation/cases/" + encodeURIComponent(caseId) + "/resolution",
            "POST",
            operationKey,
            {
              expected_revision: dispute.revision,
              code: resolution,
              reason: normalizedReason,
            },
          );
          history.replaceState({ screen: "moderation-outcome" }, "", presentationLocationFor("S04", caseId));
          title.textContent = "Решение сохранено";
          const queue = element("button", "К спорам", "primary");
          queue.type = "button";
          queue.addEventListener("click", () => loadModeration(false));
          replaceContent(connectedBoundary("S04", "success", element("p", "Решение применено.", "status success"), queue));
        } catch (error) {
          actionStatus.textContent = error?.status === 409
            ? "Спор уже изменился или больше недоступен. Вернитесь к списку споров."
            : "Не удалось применить решение. Повторите запрос — ключ останется тем же.";
          if (!retryableSubmissionError(error)) operationKey = null;
          edit.disabled = false;
          confirm.disabled = false;
          confirm.focus({ preventScroll: true });
        }
        },
      });
    });
    detail.append(form);
    replaceContent(connectedBoundary("S02", "content", detail));
    select.focus({ preventScroll: true });
  } catch (error) {
    if (revision !== screenRevision) return;
    replaceContent(
      element(
        "p",
        error.message === "not_found"
          ? "Спор больше не доступен для решения."
          : "Не удалось загрузить спор. Вернитесь к списку споров и повторите.",
        "status",
      ),
    );
  }
}

async function telegramInitData() {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const value = globalThis.Telegram?.WebApp?.initData;
    if (value) return value;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  return null;
}

const invitationStartParameter = (initData) => {
  const signedValue = typeof initData === "string"
    ? new URLSearchParams(initData).get("start_param")
    : null;
  if (signedValue) return signedValue;
  const unsafeValue = globalThis.Telegram?.WebApp?.initDataUnsafe?.start_param;
  if (typeof unsafeValue === "string" && unsafeValue) return unsafeValue;
  return new URLSearchParams(globalThis.location?.search || "").get("tgWebAppStartParam");
};


const taskHomeActionLabels = {
  submit_result: "Сдать результат",
  review_work: "Проверить работу",
  answer_cancellation: "Ответить на отмену",
};

const taskHomeWaitingLabels = {
  performer_work: "Выполняют ваши задания",
  work_review: "Проверяют вашу работу",
  external_decision: "Решают отмену или спор",
};

let taskHomeHeroMode = null;

const taskHomeCount = (value, hasMore = false) => (
  value === null || value === undefined ? "—" : `${value}${hasMore ? "+" : ""}`
);

const taskHomeIcon = (kind) => {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML = {
    create: '<path d="M12 5v14M5 12h14"/>',
    archive: '<path d="M4 7h16v13H4zM3 4h18v3H3zM9 11h6"/>',
    taken: '<path d="m6.5 12.5 3.5 3.5 7.5-8"/>',
    created: '<circle cx="12" cy="8" r="3.5"/><path d="M5.5 20c.6-4.2 2.8-6.5 6.5-6.5s5.9 2.3 6.5 6.5"/>',
  }[kind];
  return svg;
};

const taskHomeDestination = (target) => {
  if (target === "created") return loadCreatedReviews();
  return loadAssignments();
};

const taskHomeItemsTotal = (items = []) => (
  items.reduce((total, item) => total + item.count, 0)
);

const openTaskHomeActionItem = (action, item) => {
  if (action === "review_work") {
    showCreatedReview(item.id, true, "task-home");
    return;
  }
  showAssignmentDetail(item.id, true, "task-home");
};

const taskHomeActionStatus = (action, item) => {
  if (action === "review_work") return "Требуется проверка";
  if (action === "answer_cancellation") return "Требуется ответ";
  return assignmentStatus(item.status || "accepted");
};

const taskHomeActionDescription = (action, item) => {
  if (action === "review_work") {
    return item.context
      ? `Исполнитель ${item.context} отправил результат.`
      : "Исполнитель отправил результат.";
  }
  if (action === "answer_cancellation") {
    return "Запрос на отмену требует вашего решения.";
  }
  return item.status === "submitted"
    ? "Результат уже отправлен — при необходимости его можно дополнить."
    : "Задание выполняется — результат ещё не отправлен.";
};

const taskHomeActionCard = (action, item) => {
  const option = element(
    "button",
    undefined,
    "card task-card work-task-card task-home-action-card",
  );
  option.type = "button";
  const chips = element("div", undefined, "card-chips");
  chips.append(element("span", taskHomeActionStatus(action, item), "chip action-chip"));
  if (item.context) chips.append(element("span", item.context, "chip muted-chip"));
  const label = element("div", undefined, "task-card-title");
  label.append(element("h3", item.title), element("span", "›", "chevron"));
  const meta = element("div", undefined, "task-meta");
  if (item.started_at) {
    const startedLabel = action === "review_work" ? "Отправлено" : "Взято";
    meta.append(element("span", `${startedLabel} ${compactListDate(item.started_at)}`));
  }
  if (item.deadline_at) {
    const deadlineLabel = action === "review_work" ? "решить до" : "до";
    meta.append(element("span", `${deadlineLabel} ${compactListDate(item.deadline_at)}`));
  }
  option.append(
    chips,
    label,
    element("p", taskHomeActionDescription(action, item), "muted"),
    meta,
  );
  return option;
};

function showTaskHomeActionSheet(trigger, action, label, items) {
  shell.querySelector(".catalog-sort-backdrop, .catalog-filter-backdrop")?.remove();
  const backdrop = element("section", undefined, "catalog-sort-backdrop");
  const dialog = element("div", undefined, "catalog-sort-sheet task-home-action-sheet");
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.setAttribute("aria-labelledby", "task-home-action-title");
  const header = element("div", undefined, "catalog-sort-heading");
  const sheetTitle = element("h2", label);
  sheetTitle.id = "task-home-action-title";
  const close = element("button", "×", "catalog-sort-close");
  close.type = "button";
  close.setAttribute("aria-label", "Закрыть выбор задания");
  header.append(sheetTitle, close);
  const options = element("div", undefined, "catalog-sort-options task-home-action-options");
  const dismiss = (restoreFocus = true) => {
    backdrop.remove();
    if (restoreFocus) trigger.focus({ preventScroll: true });
  };
  for (const item of items) {
    const option = taskHomeActionCard(action, item);
    option.addEventListener("click", () => {
      dismiss(false);
      openTaskHomeActionItem(action, item);
    });
    options.append(option);
  }
  close.addEventListener("click", () => dismiss());
  backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop) dismiss();
  });
  dialog.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      dismiss();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = [close, ...options.querySelectorAll("button")];
    const first = focusable[0];
    const last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
  dialog.append(header, options);
  backdrop.append(dialog);
  shell.append(backdrop);
  queueMicrotask(() => options.querySelector("button")?.focus({ preventScroll: true }));
}

const openTaskHomeAction = (trigger, item, label) => {
  const actionItems = item.items || [];
  if (item.count === 1 && actionItems.length === 1) {
    openTaskHomeActionItem(item.action, actionItems[0]);
    return;
  }
  if (actionItems.length > 1) {
    showTaskHomeActionSheet(trigger, item.action, label, actionItems);
    return;
  }
  taskHomeDestination(item.target);
};

function renderTaskHomeHero(hero, home) {
  const attentionTotal = taskHomeItemsTotal(home.attention);
  const waitingItems = home.waiting_on_others || [];
  const waitingTotal = taskHomeItemsTotal(waitingItems);
  if (!taskHomeHeroMode) {
    taskHomeHeroMode = attentionTotal ? "attention" : waitingTotal ? "waiting" : "attention";
  }
  const waitingMode = taskHomeHeroMode === "waiting";
  const items = waitingMode ? waitingItems : home.attention;
  const total = waitingMode ? waitingTotal : attentionTotal;
  const labels = waitingMode ? taskHomeWaitingLabels : taskHomeActionLabels;

  hero.dataset.heroMode = taskHomeHeroMode;
  const heading = element("div", undefined, "task-home-attention-heading");
  const copy = element("div", undefined, "task-home-attention-copy");
  copy.append(
    element("p", waitingMode ? "ОЖИДАНИЕ" : "СЕЙЧАС", "task-home-eyebrow"),
    element(
      "h2",
      total
        ? waitingMode ? "Ждём действия других" : "Требуются ваши действия"
        : waitingMode ? "Никого не ждём" : "Всё под контролем",
      "task-home-attention-title",
    ),
  );
  heading.append(
    copy,
    element("strong", String(total), "task-home-attention-count"),
  );

  const list = element("div", undefined, "task-home-attention-list");
  list.setAttribute("aria-label", waitingMode ? "Ожидание действий других" : "Ваши действия");
  const visibleItems = items.filter((candidate) => candidate.count > 0);
  for (const item of visibleItems) {
    const action = element("button", undefined, "task-home-attention-action");
    action.type = "button";
    action.dataset.homeAttention = item.action;
    action.append(
      element("span", labels[item.action]),
      element("span", String(item.count)),
    );
    action.addEventListener("click", () => openTaskHomeAction(action, item, labels[item.action]));
    list.append(action);
  }
  if (!visibleItems.length) {
    list.append(
      element(
        "p",
        waitingMode ? "Ожидаемых ответов сейчас нет." : "Новых действий сейчас нет.",
        "task-home-attention-empty",
      ),
    );
  }

  const nextMode = waitingMode ? "attention" : "waiting";
  const nextTotal = waitingMode ? attentionTotal : waitingTotal;
  const switcher = element("button", undefined, "task-home-attention-switch");
  switcher.type = "button";
  switcher.dataset.homeHeroSwitch = nextMode;
  switcher.setAttribute(
    "aria-label",
    waitingMode
      ? `Показать требуемые ваши действия: ${nextTotal}`
      : `Показать ожидание действий других: ${nextTotal}`,
  );
  switcher.append(
    element("span", waitingMode ? "ТРЕБУЮТСЯ ВАШИ ДЕЙСТВИЯ" : "ЖДЁМ ДЕЙСТВИЯ ДРУГИХ"),
    element("strong", String(nextTotal)),
    element("span", "›", "task-home-attention-switch-chevron"),
  );
  switcher.addEventListener("click", () => {
    taskHomeHeroMode = nextMode;
    renderTaskHomeHero(hero, home);
    requestAnimationFrame(() => hero.querySelector(".task-home-attention-switch")?.focus());
  });
  hero.replaceChildren(heading, list, switcher);
}

function showTaskHome(home, revision = ++screenRevision) {
  if (revision !== screenRevision) return;
  setNavigation("task-home", false);
  title.textContent = "Задания";
  back.classList.add("hidden");
  tasks = home.new_tasks;
  const boundary = connectedBoundary("UX02", home.errors.length ? "partial" : "content");
  boundary.dataset.uiEngine = "next-tasks-home";
  boundary.classList.add("task-home");

  const attention = element("section", undefined, "task-home-attention");
  renderTaskHomeHero(attention, home);
  boundary.append(attention);

  if (home.errors.length) {
    const partial = element("div", undefined, "task-home-partial status");
    partial.append(element("span", "Часть данных временно недоступна."));
    const retry = element("button", "Обновить", "secondary");
    retry.type = "button";
    retry.addEventListener("click", () => {
      clearJsonCache();
      void loadTaskHome(false);
    });
    partial.append(retry);
    boundary.append(partial);
  }

  const primaryActions = element("div", undefined, "task-home-primary-actions");
  const find = element("button", undefined, "task-home-primary task-home-find");
  find.type = "button";
  find.dataset.homeAction = "find";
  const findIcon = element("span", undefined, "task-home-action-icon");
  findIcon.append(searchIcon());
  find.append(
    findIcon,
    element("strong", "Найти задание"),
    element(
      "span",
      home.available_count === null
        ? "Список временно недоступен"
        : `${taskHomeCount(home.available_count, home.available_has_more)} доступно`,
    ),
  );
  find.disabled = home.available_count === null;
  find.addEventListener("click", () => loadCatalog());

  const create = element("button", undefined, "task-home-primary task-home-create");
  create.type = "button";
  create.dataset.homeAction = "create";
  const createIcon = element("span", undefined, "task-home-action-icon");
  createIcon.append(taskHomeIcon("create"));
  create.append(
    createIcon,
    element("strong", "Создать новое"),
    element("span", home.has_draft ? "Продолжить черновик" : "Новое за 2 минуты"),
  );
  create.disabled = home.can_create !== true;
  create.addEventListener("click", () => beginTaskCreationFlow());
  primaryActions.append(find, create);
  boundary.append(primaryActions);

  const work = element("div", undefined, "task-home-work-grid");
  const takenCount = home.taken_count ?? (
    home.active_count === null || home.active_count === undefined
      || home.waiting_count === null || home.waiting_count === undefined
      ? null
      : home.active_count + home.waiting_count
  );
  for (const [eyebrow, label, count, target] of [
    ["ВЗЯТЫЕ МНОЙ", "Что я выполняю", takenCount, "taken"],
    ["СОЗДАННЫЕ МНОЙ", "Что я поручил", home.created_count, "created"],
  ]) {
    const tile = element("button", undefined, "task-home-work-tile");
    tile.type = "button";
    tile.dataset.homeAction = target;
    const tileIcon = element("span", undefined, "task-home-action-icon task-home-work-icon");
    tileIcon.append(taskHomeIcon(target));
    tile.append(
      tileIcon,
      element("strong", taskHomeCount(count), "task-home-work-count"),
      element("strong", label, "task-home-work-label"),
      element("span", eyebrow, "task-home-work-eyebrow"),
    );
    tile.disabled = count === null;
    tile.addEventListener("click", () => taskHomeDestination(target));
    work.append(tile);
  }
  boundary.append(work);

  const archive = element("button", undefined, "task-home-archive");
  archive.type = "button";
  archive.dataset.homeAction = "archive";
  const archiveIcon = element("span", undefined, "task-home-archive-icon");
  archiveIcon.append(taskHomeIcon("archive"));
  const archiveCopy = element("span", undefined, "task-home-archive-copy");
  archiveCopy.append(
    element("strong", "Архив заданий"),
    element("span", "Завершённые, отменённые и истёкшие"),
  );
  archive.append(
    archiveIcon,
    archiveCopy,
    element("strong", taskHomeCount(home.archive_count), "task-home-archive-count"),
  );
  archive.disabled = home.archive_count === null;
  archive.addEventListener("click", () => loadCreatedReviews(true, "archive", "created"));
  boundary.append(archive);

  replaceContent(boundary);
}

async function loadTaskHome(push = true) {
  const revision = ++screenRevision;
  const path = "/api/v1/task-home";
  const cached = cachedJson(path);
  if (push || !location.hash.startsWith("#/tasks")) {
    history.replaceState({ screen: "task-home" }, "", "#/tasks");
  }
  if (cached) showTaskHome(cached, revision);
  else {
    setNavigation("task-home", false);
    title.textContent = "Задания";
    back.classList.add("hidden");
    const loading = connectedBoundary("UX02", "loading");
    loading.dataset.uiEngine = "next-tasks-home";
    loading.classList.add("task-home", "task-home-loading");
    loading.append(
      element("div", undefined, "task-home-loading-attention"),
      element("div", undefined, "task-home-loading-actions"),
      element("div", undefined, "task-home-loading-list"),
    );
    replaceContent(loading);
  }
  try {
    const home = await getJson(path, (refreshed) => {
      if (revision === screenRevision) showTaskHome(refreshed, revision);
    });
    if (revision !== screenRevision || cached) return;
    showTaskHome(home, revision);
  } catch (error) {
    if (revision !== screenRevision || cached) return;
    const failure = connectedBoundary("UX02", "error");
    failure.dataset.uiEngine = "next-tasks-home";
    failure.classList.add("task-home", "task-home-error");
    const retry = element("button", "Повторить", "primary");
    retry.type = "button";
    retry.addEventListener("click", () => loadTaskHome(false));
    failure.append(
      element(
        "p",
        error.message === "session_expired"
          ? "Сессия истекла. Откройте Mini App ещё раз."
          : "Не удалось загрузить главный экран заданий.",
        "status",
      ),
      retry,
    );
    replaceContent(failure);
  }
}

const onboardingFlow = [
  "consent",
  "display_name",
  "city",
  "short_bio",
  "skill_tags",
  "preview",
];

const removedOnboardingSteps = new Set(["current_goal", "help_categories", "availability"]);
const onboardingStepsWithBack = new Set([
  "display_name",
  "city",
  "short_bio",
  "skill_tags",
  "preview",
]);
let onboardingThemeInitialized = false;

const onboardingFields = {
  timezone: {
    eyebrow: "Местное время",
    title: "Укажите часовой пояс",
    hint: "Используйте точное название IANA, например Europe/Moscow.",
    label: "Часовой пояс",
    placeholder: "Europe/Moscow",
    minimum: 3,
    maximum: 64,
    multiline: false,
  },
  display_name: {
    eyebrow: "Знакомство",
    title: "Как к вам обращаться?",
    hint: "Это имя увидят участники в профиле и заданиях.",
    label: "Имя",
    placeholder: "Например, Алекс",
    minimum: 2,
    maximum: 80,
    multiline: false,
  },
  short_bio: {
    eyebrow: "О себе",
    title: "Расскажите о себе",
    hint: "Коротко расскажите о себе или заполните это позже в профиле.",
    label: "О себе",
    placeholder: "От 10 до 500 символов",
    minimum: 10,
    maximum: 500,
    multiline: true,
  },
  skill_tags: {
    eyebrow: "Навыки",
    title: "Что вы умеете?",
    hint: "Добавьте навыки по одному или заполните это позже в профиле.",
    label: "Навыки",
    placeholder: "Python\nUX-дизайн\nКопирайтинг",
    minimum: 1,
    maximum: 1000,
    multiline: true,
  },
};

const onboardingProgress = (step) => {
  const index = Math.max(0, onboardingFlow.indexOf(step));
  const progress = element("div", undefined, "onboarding-progress");
  const copy = element("div", undefined, "onboarding-progress-copy");
  copy.append(
    element("span", `Шаг ${Math.min(index + 1, onboardingFlow.length)} из ${onboardingFlow.length}`),
    element("strong", step === "preview" ? "Проверка анкеты" : "Регистрация в сообществе"),
  );
  const track = element("span", undefined, "onboarding-progress-track");
  const fill = element("span", undefined, "onboarding-progress-fill");
  fill.style.width = `${((index + 1) / onboardingFlow.length) * 100}%`;
  track.append(fill);
  progress.append(copy, track);
  return progress;
};

const onboardingMutation = async (path, body) => {
  const headers = { "Idempotency-Key": newOperationKey() };
  const options = { method: "POST", headers, credentials: "same-origin" };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await apiFetch(path, options);
  if (!response.ok) {
    const error = new Error(requestError(response));
    error.status = response.status;
    throw error;
  }
  return response.json();
};

const onboardingStatus = () => {
  const status = element("p", "", "status hidden onboarding-status");
  status.setAttribute("aria-live", "polite");
  return status;
};

const submitOnboardingAnswer = async (step, value, submit, status) => {
  const controls = submit.closest(".onboarding-card")?.querySelectorAll("button") || [submit];
  for (const control of controls) control.disabled = true;
  status.className = "status onboarding-status";
  status.textContent = "Сохраняем…";
  try {
    showOnboarding(await onboardingMutation("/api/v1/onboarding/answer", { step, value }));
  } catch (error) {
    status.textContent = error?.status === 422
      ? "Проверьте заполнение поля. Значение не соответствует требованиям."
      : "Не удалось сохранить. Повторите попытку.";
    for (const control of controls) control.disabled = false;
    submit.focus({ preventScroll: true });
  }
};

const onboardingTextStep = (view, step) => {
  const config = onboardingFields[step];
  const optional = ["short_bio", "skill_tags"].includes(step);
  const card = element("form", undefined, "onboarding-card onboarding-form");
  card.append(
    element("p", config.eyebrow, "onboarding-eyebrow"),
    element("h2", config.title),
    element("p", config.hint, "onboarding-hint"),
  );
  const label = element(
    "label",
    optional ? `${config.label} (необязательно)` : `${config.label} *`,
    "onboarding-field",
  );
  const input = element(config.multiline ? "textarea" : "input");
  input.name = step;
  input.placeholder = config.placeholder;
  input.maxLength = config.maximum;
  input.required = !optional;
  if (!config.multiline) input.type = "text";
  const stored = view.payload?.[step];
  input.value = Array.isArray(stored) ? stored.join("\n") : stored || "";
  if (config.multiline) input.rows = step === "short_bio" ? 4 : 3;
  const counter = element("span", `${input.value.length} / ${config.maximum}`, "onboarding-counter");
  input.addEventListener("input", () => {
    counter.textContent = `${input.value.length} / ${config.maximum}`;
    counter.classList.toggle("is-limit", input.value.length >= config.maximum);
  });
  label.append(input, counter);
  const submit = element("button", "Продолжить", "primary onboarding-primary");
  submit.type = "submit";
  const actions = element("div", undefined, "onboarding-form-actions");
  actions.append(submit);
  if (optional) {
    const later = element("button", "Заполнить позже", "onboarding-later");
    later.type = "button";
    later.addEventListener("click", () => void submitOnboardingAnswer(step, "", later, status));
    actions.append(later);
  }
  const status = onboardingStatus();
  card.append(label, actions, status);
  card.addEventListener("submit", (event) => {
    event.preventDefault();
    const value = input.value.trim();
    if (optional && !value) {
      void submitOnboardingAnswer(step, "", submit, status);
      return;
    }
    const itemCount = step === "skill_tags"
      ? value.split(/[\n,]+/).filter((item) => item.trim()).length
      : null;
    const validList = itemCount === null || (itemCount >= 1 && itemCount <= 20);
    if (value.length < config.minimum || value.length > config.maximum || !validList) {
      status.className = "status onboarding-status";
      status.textContent = itemCount !== null && !validList
        ? "Укажите от 1 до 20 навыков."
        : `Введите от ${config.minimum} до ${config.maximum} символов.`;
      input.focus({ preventScroll: true });
      return;
    }
    void submitOnboardingAnswer(step, value, submit, status);
  });
  queueMicrotask(() => input.focus({ preventScroll: true }));
  return card;
};

const onboardingCityStep = (view) => {
  const card = element(
    "section",
    undefined,
    "onboarding-card onboarding-form onboarding-city-inline",
  );
  card.append(
    element("p", "Обязательное поле", "onboarding-eyebrow"),
    element("h2", "В каком городе вы живёте?"),
    element(
      "p",
      "По городу мы определим ваш часовой пояс для сроков и времени заданий.",
      "onboarding-hint",
    ),
  );
  const selected = view.payload?.city;
  const searchLabel = element("label", "Город *", "onboarding-field city-search-field");
  const search = element("input");
  search.type = "search";
  search.autocomplete = "off";
  search.placeholder = "Начните вводить название";
  search.value = selected || "";
  searchLabel.append(search);
  const results = element("div", undefined, "city-sheet-results onboarding-city-results");
  results.setAttribute("role", "listbox");
  const selection = element(
    "p",
    selected
      ? `Выбран: ${selected} · ${timezoneOffsetLabel(view.payload?.timezone || "UTC")}`
      : "Выберите город из предложенного списка",
    "onboarding-city-selection",
  );
  const next = element("button", "Продолжить", "primary onboarding-primary onboarding-city-next");
  next.type = "button";
  let pendingCity = selected
    ? { value: selected, label: selected, timezone: view.payload?.timezone || "UTC" }
    : null;
  next.disabled = pendingCity === null;
  const status = onboardingStatus();
  let timer = null;
  const loadResults = async (query) => {
    results.classList.remove("hidden");
    if (!query) {
      results.replaceChildren();
      results.classList.add("hidden");
      return;
    }
    results.replaceChildren(element("p", "Ищем города…", "city-sheet-empty"));
    try {
      const response = await getJson(`/api/v1/task-cities?q=${encodeURIComponent(query)}&limit=6`);
      if (!card.isConnected || search.value.trim() !== query) return;
      if (!response.items.length) {
        results.replaceChildren(element("p", "Города не найдены.", "city-sheet-empty"));
        return;
      }
      results.replaceChildren();
      for (const item of response.items) {
        const option = element("button", undefined, "city-sheet-option");
        option.type = "button";
        option.setAttribute("role", "option");
        option.setAttribute("aria-label", item.label);
        option.setAttribute("aria-selected", String(item.value === pendingCity?.value));
        const copy = element("span", undefined, "city-sheet-copy");
        copy.append(element("strong", item.label), element("small", timezoneOffsetLabel(item.timezone)));
        option.append(
          copy,
          element("span", item.value === pendingCity?.value ? "✓" : "", "city-sheet-check"),
        );
        option.addEventListener("click", () => {
          pendingCity = item;
          search.value = item.label;
          selection.textContent = `Выбран: ${item.label} · ${timezoneOffsetLabel(item.timezone)}`;
          next.disabled = false;
          results.classList.add("hidden");
          next.focus({ preventScroll: true });
        });
        results.append(option);
      }
    } catch {
      results.replaceChildren(element("p", "Не удалось загрузить города.", "city-sheet-empty"));
    }
  };
  search.addEventListener("input", () => {
    clearTimeout(timer);
    pendingCity = null;
    next.disabled = true;
    selection.textContent = "Выберите город из предложенного списка";
    const query = search.value.trim();
    timer = setTimeout(() => void loadResults(query), 200);
  });
  search.addEventListener("focus", () => {
    if (search.value.trim() && !pendingCity) void loadResults(search.value.trim());
  });
  next.addEventListener("click", () => {
    if (!pendingCity) return;
    void submitOnboardingAnswer("city", pendingCity.value, next, status);
  });
  card.append(searchLabel, results, selection, next, status);
  results.classList.add("hidden");
  queueMicrotask(() => search.focus({ preventScroll: true }));
  return card;
};

const onboardingPreview = (view) => {
  const card = element("section", undefined, "onboarding-card onboarding-preview");
  card.append(
    element("p", "Почти готово", "onboarding-eyebrow"),
    element("h2", "Проверьте анкету"),
    element(
      "p",
      view.personal_invitation
        ? "После подтверждения вы сразу станете участником Комьюнити."
        : "После отправки анкету проверит модератор.",
      "onboarding-hint",
    ),
  );
  if (view.application_status === "rejected") {
    const rejected = element("div", undefined, "onboarding-review-note is-rejected");
    rejected.append(
      element("strong", "Анкету нужно уточнить"),
      element("span", view.review_comment || "Проверьте данные и отправьте анкету снова."),
    );
    card.append(rejected);
  }
  const rows = element("dl", undefined, "onboarding-summary");
  const summary = [
    ["Имя", view.payload?.display_name],
    ["Город", view.payload?.city],
    ["Часовой пояс", view.payload?.timezone ? `${view.payload.timezone} · ${timezoneOffsetLabel(view.payload.timezone)}` : null],
    ["О себе", view.payload?.short_bio],
    ["Навыки", Array.isArray(view.payload?.skill_tags) ? view.payload.skill_tags.join(", ") : null],
  ];
  for (const [label, value] of summary) {
    rows.append(element("dt", label), element("dd", value || "—"));
  }
  const rejected = view.application_status === "rejected";
  const submit = element(
    "button",
    rejected
      ? "Исправить анкету"
      : view.personal_invitation ? "Вступить в Комьюнити" : "Отправить на проверку",
    "primary onboarding-primary",
  );
  submit.type = "button";
  const status = onboardingStatus();
  submit.addEventListener("click", async () => {
    submit.disabled = true;
    status.className = "status onboarding-status";
    status.textContent = rejected
      ? "Открываем анкету…"
      : view.personal_invitation ? "Завершаем регистрацию…" : "Отправляем анкету…";
    try {
      showOnboarding(
        await onboardingMutation(
          rejected ? "/api/v1/onboarding/reopen" : "/api/v1/onboarding/submit",
        ),
      );
    } catch {
      status.textContent = rejected
        ? "Не удалось открыть анкету. Повторите попытку."
        : "Не удалось отправить анкету. Проверьте данные и повторите.";
      submit.disabled = false;
    }
  });
  card.append(rows, submit, status);
  return card;
};

const onboardingSubmitted = (view) => {
  const card = element("section", undefined, "onboarding-card onboarding-outcome");
  const icon = element("span", "✓", "onboarding-outcome-icon");
  card.append(
    icon,
    element("p", "Анкета отправлена", "onboarding-eyebrow"),
    element("h2", "Ждём решение модератора"),
    element(
      "p",
      "Регистрация сохранена. После одобрения при следующем открытии Mini App появится главный экран заданий.",
      "onboarding-hint",
    ),
  );
  const state = element("div", undefined, "onboarding-review-note");
  state.append(element("strong", "Статус"), element("span", "На проверке"));
  card.append(state);
  return card;
};

const onboardingApproved = () => {
  const card = element("section", undefined, "onboarding-card onboarding-outcome");
  card.append(
    element("span", "✓", "onboarding-outcome-icon"),
    element("p", "Регистрация завершена", "onboarding-eyebrow"),
    element("h2", "Вы в Комьюнити"),
    element(
      "p",
      "Профиль активирован. Теперь вам доступны участники и задания сообщества.",
      "onboarding-hint",
    ),
  );
  const open = element("button", "Перейти к заданиям", "primary onboarding-primary");
  open.type = "button";
  open.addEventListener("click", () => {
    clearJsonCache();
    location.hash = "/tasks";
    location.reload();
  });
  card.append(open);
  return card;
};

const returnToPreviousOnboardingStep = async () => {
  back.disabled = true;
  back.setAttribute("aria-busy", "true");
  try {
    showOnboarding(await onboardingMutation("/api/v1/onboarding/back"));
  } catch {
    back.disabled = false;
    back.removeAttribute("aria-busy");
    setHeaderControl("back", {
      label: "Предыдущий шаг",
      onBack: () => void returnToPreviousOnboardingStep(),
    });
  }
};

function showOnboarding(view) {
  screenRevision += 1;
  const onboardingUrl = new URL(location.href);
  onboardingUrl.hash = "/onboarding";
  if (!onboardingThemeInitialized) {
    onboardingThemeInitialized = true;
    onboardingUrl.searchParams.set("preset", "neon");
    onboardingUrl.searchParams.set("theme", "light");
    applyThemePreset("neon");
    applyPreviewTheme("light");
  }
  history.replaceState({ screen: "onboarding" }, "", onboardingUrl);
  setNavigation("onboarding", false);
  const canGoBack = view.application_status === "draft" && onboardingStepsWithBack.has(view.step);
  setHeaderControl(canGoBack ? "back" : null, {
    label: "Предыдущий шаг",
    hideTitle: false,
    onBack: canGoBack ? () => void returnToPreviousOnboardingStep() : null,
  });
  back.disabled = false;
  back.removeAttribute("aria-busy");
  title.textContent = "Регистрация";
  moderationNav.hidden = true;
  const boundary = connectedBoundary("UX03", view.application_status);
  boundary.dataset.uiEngine = "next-onboarding";
  boundary.classList.add("onboarding");
  if (view.application_status === "approved") {
    boundary.append(onboardingApproved());
  } else if (view.application_status === "submitted" || view.step === "submitted") {
    boundary.append(onboardingSubmitted(view));
  } else {
    boundary.append(onboardingProgress(view.step));
    if (view.step === "consent") {
      const card = element("section", undefined, "onboarding-card onboarding-consent");
      card.append(
        element("p", "Добро пожаловать", "onboarding-eyebrow"),
        element("h2", "Вступление в сообщество"),
        element(
          "p",
          view.personal_invitation
            ? "Заполните короткую анкету. После подтверждения вы сразу вступите в Комьюнити."
            : "Заполните короткую анкету. Данные профиля будут видны другим участникам после проверки модератором.",
          "onboarding-hint",
        ),
      );
      const terms = element("div", undefined, "onboarding-terms");
      terms.append(
        element("span", "01"), element("p", "Указывайте достоверную информацию о себе."),
        element("span", "02"), element("p", "Соблюдайте правила и уважайте других участников."),
        element("span", "03"), element("p", "Вы сможете изменить профиль после одобрения."),
      );
      const accept = element("button", "Согласен, продолжить", "primary onboarding-primary");
      accept.type = "button";
      const status = onboardingStatus();
      accept.addEventListener("click", () => void submitOnboardingAnswer("consent", "accept", accept, status));
      card.append(terms, accept, status);
      boundary.append(card);
    } else if (view.step === "city") {
      boundary.append(onboardingCityStep(view));
    } else if (view.step === "timezone") {
      boundary.append(onboardingTextStep(view, "timezone"));
    } else if (view.step === "preview") {
      boundary.append(onboardingPreview(view));
    } else if (removedOnboardingSteps.has(view.step)) {
      const card = element("section", undefined, "onboarding-card onboarding-outcome");
      card.append(element("p", "Обновляем анкету…", "status muted"));
      boundary.append(card);
      queueMicrotask(async () => {
        try {
          showOnboarding(await onboardingMutation("/api/v1/onboarding/answer", { step: view.step, value: "" }));
        } catch {
          card.replaceChildren(element("p", "Не удалось обновить старый черновик анкеты.", "status"));
        }
      });
    } else if (onboardingFields[view.step]) {
      boundary.append(onboardingTextStep(view, view.step));
    } else {
      boundary.append(element("p", "Не удалось определить текущий шаг регистрации.", "status"));
    }
  }
  replaceContent(boundary);
}

function showOnboardingAccessRequired() {
  screenRevision += 1;
  history.replaceState({ screen: "onboarding-access" }, "", "#/onboarding");
  setNavigation("onboarding", false);
  title.textContent = "Регистрация";
  back.classList.add("hidden");
  const card = element("section", undefined, "onboarding-card onboarding-outcome");
  card.append(
    element("span", "↗", "onboarding-outcome-icon"),
    element("p", "Нужно приглашение", "onboarding-eyebrow"),
    element("h2", "Откройте ссылку сообщества"),
    element(
      "p",
      "Регистрация начинается по персональной ссылке-приглашению. Запросите её у администратора и откройте Mini App из этой ссылки.",
      "onboarding-hint",
    ),
  );
  const boundary = connectedBoundary("UX03", "invitation-required", card);
  boundary.dataset.uiEngine = "next-onboarding";
  boundary.classList.add("onboarding");
  replaceContent(boundary);
}

function showMembershipGate(payload, retry) {
  screenRevision += 1;
  history.replaceState({ screen: "membership-required" }, "", "#/membership");
  setNavigation("onboarding", false);
  title.textContent = "Комьюнити";
  back.classList.add("hidden");
  const unavailable = payload.code === "membership_check_unavailable";
  const card = element("section", undefined, "onboarding-card onboarding-outcome");
  card.append(
    element("span", unavailable ? "↻" : "✓", "onboarding-outcome-icon"),
    element("p", unavailable ? "Проверка недоступна" : "Условие вступления", "onboarding-eyebrow"),
    element("h2", unavailable ? "Не удалось связаться с Telegram" : "Вступите в сообщество"),
    element(
      "p",
      unavailable
        ? "Ничего не потеряно. Попробуйте проверить участие ещё раз."
        : "Вступите в обязательные чаты, затем вернитесь и нажмите «Проверить».",
      "onboarding-hint",
    ),
  );
  for (const resource of payload.resources || []) {
    const row = element("div", undefined, "membership-gate-resource");
    const copy = element("span");
    copy.append(
      element("strong", resource.title),
      element("small", resource.joined ? "Участие подтверждено" : "Нужно вступить"),
    );
    row.append(copy);
    if (!resource.joined) {
      const open = element("button", "Открыть", "secondary");
      open.type = "button";
      open.addEventListener("click", () => {
        if (globalThis.Telegram?.WebApp?.openTelegramLink) {
          globalThis.Telegram.WebApp.openTelegramLink(resource.join_url);
        } else {
          globalThis.open(resource.join_url, "_blank", "noopener,noreferrer");
        }
      });
      row.append(open);
    }
    card.append(row);
  }
  const check = element("button", "Проверить", "primary admin-full");
  const status = element("p", "", "status hidden");
  check.type = "button";
  check.addEventListener("click", async () => {
    check.disabled = true;
    status.className = "status";
    status.textContent = "Проверяем участие…";
    try {
      await retry();
    } catch {
      status.textContent = "Не удалось проверить. Попробуйте ещё раз.";
      check.disabled = false;
    }
  });
  const boundary = connectedBoundary("UX03", "membership-required", card, check, status);
  boundary.dataset.uiEngine = "next-onboarding";
  boundary.classList.add("onboarding");
  replaceContent(boundary);
}

async function membershipPayload(response) {
  try {
    const payload = await response.json();
    return payload?.code?.startsWith("membership_") ? payload : null;
  } catch {
    return null;
  }
}

async function bootstrapTaskHome(authAttempted = false) {
  try {
    const me = await apiFetch("/api/v1/me", { credentials: "same-origin" });
    if (me.status === 401 && !authAttempted) {
      const initData = await telegramInitData();
      if (!initData) throw new Error("telegram_init_data_missing");
      const invitation = invitationStartParameter(initData);
      const authHeaders = { "Content-Type": "text/plain; charset=utf-8" };
      if (typeof invitation === "string" && invitation) {
        authHeaders["X-Community-Invitation"] = invitation;
      }
      const auth = await apiFetch("/api/v1/auth/telegram", {
        method: "POST",
        headers: authHeaders,
        body: initData,
        credentials: "same-origin",
      });
      if (!auth.ok) {
        const gate = await membershipPayload(auth);
        if (gate) return showMembershipGate(gate, () => bootstrapTaskHome(false));
        if (auth.status === 401 || auth.status === 403) return showOnboardingAccessRequired();
        throw new Error("telegram_auth_failed");
      }
      return bootstrapTaskHome(true);
    }
    if (me.status === 403) {
      const gate = await membershipPayload(me);
      if (gate) return showMembershipGate(gate, () => bootstrapTaskHome(true));
      const onboarding = await apiFetch("/api/v1/onboarding", { credentials: "same-origin" });
      if (!onboarding.ok) throw new Error("onboarding_failed");
      return showOnboarding(await onboarding.json());
    }
    if (me.status === 503) {
      const gate = await membershipPayload(me);
      if (gate) return showMembershipGate(gate, () => bootstrapTaskHome(true));
    }
    if (!me.ok) throw new Error("bootstrap_failed");
    const profile = await me.json();
    storeJson("/api/v1/me", profile);
    currentMemberId = profile.member_id;
    setMemberTimezone(profile.timezone || "UTC");
    void configureRoleNavigation();
    const initialHash = location.hash;
    const presentation = presentationFromLocation();
    const presentationId = presentation?.screen.id;
    const resourceId = presentation?.resourceId;
    const directMember = initialHash.match(/^#\/members\/([0-9a-f-]{36})$/i);
    const directInvitation = initialHash.match(/^#\/moderation\/invitations(?:\/(new))?$/i);
    const directAdministration = initialHash.match(
      /^#\/moderation\/(access|team|administrators(?:\/([0-9a-f-]{36}))?|administrators\/new)$/i,
    );
    const directCreditRecipient = initialHash.match(
      /^#\/moderation\/credits\/recipients\/([0-9a-f-]{36})$/i,
    );
    if (initialHash === "#/settings") showSettings(false);
    else if (/^#\/profile(?:\/.*)?$/.test(initialHash)) loadProfile(false);
    else if (directMember) {
      history.replaceState(
        { screen: "member-profile", memberId: directMember[1] },
        "",
        initialHash,
      );
      showMemberProfile(directMember[1], false);
    } else if (initialHash === "#/moderation/credits") {
      history.replaceState({ screen: "credit-grant-home" }, "", initialHash);
      loadCreditGrantHome(false);
    } else if (initialHash === "#/moderation/credits/search") {
      history.replaceState({ screen: "credit-grant-home" }, "", "#/moderation/credits");
      loadCreditGrantHome(false);
    } else if (initialHash === "#/moderation/credits/history") {
      history.replaceState({ screen: "credit-grant-history" }, "", initialHash);
      loadCreditGrantHistory(false);
    } else if (directCreditRecipient) {
      history.replaceState(
        { screen: "credit-grant-form", memberId: directCreditRecipient[1] },
        "",
        initialHash,
      );
      showCreditGrantForm(directCreditRecipient[1], false);
    } else if (/^#\/moderation\/credits\/(confirm|success)$/.test(initialHash)) {
      history.replaceState({ screen: "credit-grant-home" }, "", "#/moderation/credits");
      loadCreditGrantHome(false);
    } else if (directAdministration?.[1] === "access") {
      history.replaceState({ screen: "moderation-access" }, "", initialHash);
      loadAdministrationAccess(false);
    } else if (directAdministration?.[1] === "team") {
      history.replaceState({ screen: "moderation-team" }, "", initialHash);
      loadAdministrationTeam(false);
    } else if (initialHash === "#/moderation/community-reviews") {
      history.replaceState({ screen: "moderation-community-reviews" }, "", initialHash);
      loadCommunityReviews(false);
    } else if (directInvitation?.[1] === "new") {
      history.replaceState({ screen: "personal-invitation-create" }, "", initialHash);
      showPersonalInvitationCreate(false);
    } else if (directInvitation) {
      history.replaceState({ screen: "personal-invitations" }, "", "#/moderation/invitations");
      loadPersonalInvitations(false);
    } else if (directAdministration?.[1] === "administrators/new") {
      history.replaceState({ screen: "administrator-candidates" }, "", initialHash);
      loadAdministratorCandidates(false);
    } else if (directAdministration?.[2]) {
      history.replaceState(
        { screen: "administrator-rights", memberId: directAdministration[2], isNew: false },
        "",
        initialHash,
      );
      showAdministratorRights(directAdministration[2], false, null, false);
    } else if (presentationId === "T01" || presentationId === "T02") {
      history.replaceState({ screen: "catalog" }, "", initialHash);
      await loadCatalog(false);
    }
    else if (presentationId === "T04B") beginTaskCreationFlow(false);
    else if (["T05", "T06", "T08"].includes(presentationId)) {
      const forceEdit = presentationId === "T05";
      history.replaceState(
        { screen: forceEdit ? "task-creation" : "task-preview", draftId: resourceId },
        "",
        presentationLocationFor(forceEdit ? "T05" : "T06", resourceId),
      );
      openTaskCreation(forceEdit, forceEdit ? null : "stale");
    } else if (["P01", "P05", "P08"].includes(presentationId)) {
      loadParticipants(presentationId === "P05" ? "leaderboard" : presentationId === "P08" ? "pulse" : "members");
    } else if (presentationId === "M01" || presentationId === "M02") {
      history.replaceState({ screen: "assignments" }, "", initialHash);
      await loadAssignments(false);
      if (presentationId === "M02") showTakenAssignments();
    } else if (presentationId === "M09" || presentationId === "M10") {
      const parameters = new URLSearchParams(initialHash.split("?", 2)[1] || "");
      const scope = parameters.get("scope");
      const archiveRole = parameters.get("archive_view");
      await loadCreatedReviews(
        false,
        scope === "archive" ? "archive" : "active",
        archiveRole === "performed" ? "performed" : "created",
      );
    } else if (["T03", "T03A"].includes(presentationId) && resourceId) {
      if (presentationId === "T03A") {
        history.replaceState(
          { screen: "task", taskId: resourceId },
          "",
          presentationLocationFor("T03", resourceId),
        );
      }
      const page = await getJson("/api/v1/tasks");
      tasks = page.items;
      const task = tasks.find((item) => item.id === resourceId);
      if (task) showTaskDetail(task, false);
      else await loadCatalog(false);
    } else if (["P02", "P03", "P04"].includes(presentationId) && resourceId) {
      showMemberProfile(resourceId, false);
    } else if (["M03", "M04", "M05", "M06", "M07", "M08", "M14", "M15"].includes(presentationId) && resourceId) {
      showAssignmentDetail(resourceId, false);
    } else if (["M11", "M12", "M13"].includes(presentationId) && resourceId) {
      showCreatedReview(resourceId, false);
    } else if (presentationId === "S01") {
      loadModeration(false);
    } else if (["S02", "S03", "S04"].includes(presentationId) && resourceId) {
      if (presentationId !== "S02") {
        history.replaceState(
          { screen: "moderation-case", caseId: resourceId },
          "",
          presentationLocationFor("S02", resourceId),
        );
      }
      showModerationCase(resourceId, false);
    } else {
      await loadTaskHome(false);
    }
  } catch {
    setNavigation("task-home", false);
    replaceContent(
      element(
        "p",
        "Не удалось открыть главный экран заданий. Проверьте локальную сессию.",
        "status",
      ),
    );
  }
}

catalogNav.addEventListener("click", () => void loadTaskHome());
participantsNav.addEventListener("click", () => loadParticipants("members"));
profileNav.addEventListener("click", () => showSettings());
moderationNav.addEventListener("click", () => loadModeration());
back.addEventListener("click", () => {
  if (headerBackAction) {
    const action = headerBackAction;
    headerBackAction = null;
    action();
  } else if (activeProfileState?.route === "/profile") {
    if (activeProfileState.fromSettings && activeProfileState.closeHistoryDelta > 0) {
      history.go(-activeProfileState.closeHistoryDelta);
    }
    else showSettings(false);
  } else if (activeProfileState?.route && activeProfileState.route !== "/profile") {
    const route = activeProfileState.route;
    let destination = "/profile";
    if (route === "/profile/links/new" || /^\/profile\/links\/[0-9a-f-]{36}$/i.test(route)) destination = "/profile/links";
    if (route.endsWith("/delete")) {
      destination = activeProfileState.deleteOrigin === "edit" ? route.replace(/\/delete$/, "") : "/profile/links";
    }
    const linkId = route.match(/^\/profile\/links\/([0-9a-f-]{36})/i)?.[1];
    activeProfileState.returnFocus = destination === "/profile"
      ? `[data-profile-action="${route.split("/").at(-1)}"]`
      : activeProfileState.deleteOrigin === "edit"
        ? `[data-link-delete-id="${linkId}"]`
        : activeProfileState.deleteOrigin === "list" && linkId
          ? `[data-link-trash-id="${linkId}"]`
          : linkId
            ? `[data-link-id="${linkId}"]`
            : ".profile-pencil, [data-profile-add-link]";
    activeProfileState.draft = null;
    openProfileRoute(activeProfileState, screenRevision, destination, false);
  } else if (history.state?.screen === "member-profile" && !memberProfileHasInternalHistory) {
    loadParticipants("members");
  } else if (history.state?.screen === "participants" && history.state.view === "leaderboard") {
    returnFocusLeaderboardTab = true;
    loadParticipants("members");
  } else {
    history.back();
  }
});
globalThis.addEventListener("popstate", (event) => {
  if (event.state?.screen === "task-home") {
    void loadTaskHome(false);
  } else if (event.state?.screen === "catalog") {
    void loadCatalog(false);
  } else if (event.state?.screen === "participants") {
    loadParticipants(
      event.state.view || "members",
      event.state.period || "week",
      event.state.metric || "experience",
    );
  } else if (event.state?.screen === "task") {
    const task = tasks.find((item) => item.id === event.state.taskId);
    if (task) showTaskDetail(task, false);
  } else if (event.state?.screen === "assignments") {
    showAssignments();
  } else if (event.state?.screen === "assignments-taken") {
    showTakenAssignments();
  } else if (event.state?.screen === "created-assignments") {
    loadCreatedReviews(
      false,
      event.state.scope || "active",
      event.state.archiveRole || "created",
    );
  } else if (event.state?.screen === "assignment-review") {
    showCreatedReview(event.state.assignmentId, false, event.state.returnTo || null);
  } else if (event.state?.screen === "assignment") {
    showAssignmentDetail(event.state.assignmentId, false);
  } else if (event.state?.screen === "profile") {
    loadProfile(false);
  } else if (event.state?.screen === "settings") {
    showSettings(false);
  } else if (event.state?.screen === "member-profile") {
    showMemberProfile(event.state.memberId, false);
  } else if (event.state?.screen === "moderation") {
    loadModeration(false);
  } else if (event.state?.screen === "moderation-access") {
    loadAdministrationAccess(false);
  } else if (event.state?.screen === "moderation-team") {
    loadAdministrationTeam(false);
  } else if (event.state?.screen === "moderation-community-reviews") {
    loadCommunityReviews(false);
  } else if (event.state?.screen === "credit-grant-home") {
    loadCreditGrantHome(false);
  } else if (event.state?.screen === "credit-grant-form") {
    showCreditGrantForm(event.state.memberId, false);
  } else if (event.state?.screen === "credit-grant-confirm") {
    showCreditGrantConfirmation(false);
  } else if (event.state?.screen === "credit-grant-history") {
    loadCreditGrantHistory(false);
  } else if (event.state?.screen === "credit-grant-success") {
    loadCreditGrantHome(false);
  } else if (event.state?.screen === "personal-invitations") {
    loadPersonalInvitations(false);
  } else if (event.state?.screen === "personal-invitation-create") {
    showPersonalInvitationCreate(false, event.state.invitation || null);
  } else if (event.state?.screen === "administrator-candidates") {
    loadAdministratorCandidates(false);
  } else if (event.state?.screen === "administrator-rights") {
    showAdministratorRights(
      event.state.memberId,
      Boolean(event.state.isNew),
      event.state.candidate || null,
      false,
    );
  } else if (event.state?.screen === "moderation-case") {
    showModerationCase(event.state.caseId, false);
  } else if (event.state?.screen === "task-creation") {
    openTaskCreation(true);
  } else if (event.state?.screen === "task-recovery") {
    beginTaskCreationFlow(false);
  } else if (event.state?.screen === "task-preview") {
    openTaskCreation(false, "stale");
  } else {
    void loadTaskHome(false);
  }
});
void bootstrapTaskHome();
