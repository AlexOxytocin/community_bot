import { applyPlatformTheme } from "/mini-assets/platform.js";

applyPlatformTheme();

const content = document.getElementById("content");
const title = document.getElementById("screen-title");
const back = document.getElementById("back");
const shell = document.getElementById("app");
const catalogNav = document.getElementById("catalog-nav");
const profileNav = document.getElementById("profile-nav");
const assignmentsNav = document.getElementById("assignments-nav");
const participantsNav = document.getElementById("participants-nav");
const moderationNav = document.getElementById("moderation-nav");
const heading = title.parentElement;
let tasks = [];
let assignments = [];
let ownedTasks = [];
let ownedReviews = [];
let catalogFilters = { format: "", minReward: "" };
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

const element = (tag, text, className) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
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
  content.replaceChildren(...nodes);
  resetScrollPosition();
  queueMicrotask(resetScrollPosition);
  requestAnimationFrame(resetScrollPosition);
};

const connectedScreenIds = new Set(`
T01 T02 T03 T03A T04B T05 T06 T08
P01 P02 P03 P04 P05 P06 P07
M01 M02 M03 M04 M05 M06 M07 M08 M09 M10 M11 M12 M13 M14 M15
S01 S02 S03 S04
`.trim().split(/\s+/));
const productRouteFor = (id) => {
  if (["T01", "T02"].includes(id)) return "#/catalog";
  if (["T03", "T03A"].includes(id)) return "#/tasks/:task_id";
  if (id.startsWith("T")) return "#/compose/tasks/:draft_id?";
  if (["M01", "M02", "M09"].includes(id)) return "#/work";
  if (id.startsWith("M")) return "#/work/:resource_id";
  if (["P01", "P05"].includes(id)) return "#/members";
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

const setNavigation = (screen, context) => {
  heading.querySelector(".heading-action")?.remove();
  shell.classList.toggle("context-screen", context);
  shell.classList.toggle("catalog-screen", screen === "catalog");
  shell.classList.toggle("participants-screen", screen === "participants");
  shell.classList.toggle("profile-screen", screen === "profile");
  shell.classList.remove("task-detail-screen");
  catalogNav.setAttribute("aria-pressed", String(screen === "catalog"));
  profileNav.setAttribute("aria-pressed", String(screen === "profile"));
  assignmentsNav.setAttribute("aria-pressed", String(screen === "assignments"));
  participantsNav.setAttribute("aria-pressed", String(screen === "participants"));
  moderationNav.setAttribute("aria-pressed", String(screen === "moderation"));
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
}) => {
  title.textContent = headingText;
  const card = element("article", undefined, "card detail route-accent confirm-screen");
  card.append(element("p", "Подтверждение", "badge"), element("p", description, "muted"));
  const actions = element("div", undefined, "confirm-actions");
  const edit = element("button", "Изменить", "secondary");
  edit.type = "button";
  edit.addEventListener("click", onEdit);
  const confirm = element("button", confirmLabel, "primary");
  confirm.type = "button";
  if (transitionId) markTransition(confirm, transitionId, transitionTrigger);
  const status = element("p", "", "status hidden");
  status.setAttribute("aria-live", "polite");
  confirm.addEventListener("click", () => onConfirm({ confirm, edit, status }));
  actions.append(edit, confirm);
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
    await getJson("/api/v1/moderation/cases?limit=1");
    moderationNav.hidden = false;
  } catch {
    moderationNav.hidden = true;
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

const formatDate = (value) => new Intl.DateTimeFormat("ru", {
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
}[value] || value);

const createdAssignmentsButton = element("button", "Созданные мной", "back");
createdAssignmentsButton.type = "button";
createdAssignmentsButton.addEventListener("click", () => loadCreatedReviews());

const newOperationKey = () => {
  const words = new Uint32Array(2);
  crypto.getRandomValues(words);
  const value = ((BigInt(words[0]) << 32n) | BigInt(words[1])) & 0x7fffffffffffffffn;
  return (value || 1n).toString();
};

function showCatalog(revision = ++screenRevision) {
  if (revision !== screenRevision) return;
  setNavigation("catalog", false);
  title.textContent = "Задания";
  back.classList.add("hidden");
  const create = element("button", "+ Создать", "secondary compact-create");
  create.type = "button";
  create.addEventListener("click", () => beginTaskCreationFlow());
  const boundary = element("section", undefined, "state-view catalog-view");
  boundary.dataset.screenId = "T01";
  boundary.dataset.uiEngine = "concept-05";
  boundary.dataset.template = "list";
  const visibleTasks = tasks.filter((task) => (
    (!catalogFilters.format || task.format === catalogFilters.format)
    && (!catalogFilters.minReward || task.credit_reward_per_performer >= Number(catalogFilters.minReward))
  ));
  boundary.dataset.state = visibleTasks.length ? "content" : "empty";
  const activeFilterCount = Object.values(catalogFilters).filter(Boolean).length;
  const actions = element("div", undefined, "catalog-actions");
  const filterTrigger = element("button", undefined, "secondary catalog-filter-button");
  filterTrigger.type = "button";
  filterTrigger.append(slidersIcon(), element("span", "Фильтры"));
  if (activeFilterCount) {
    filterTrigger.classList.add("is-active");
    filterTrigger.setAttribute("aria-label", `Фильтры, выбрано: ${activeFilterCount}`);
    filterTrigger.append(element("span", String(activeFilterCount), "catalog-filter-count"));
  }
  markTransition(filterTrigger, "PE-012", "open_filters");
  filterTrigger.addEventListener("click", () => showCatalogFilters());
  actions.append(filterTrigger, create);
  const availableStatus = element(
    "p",
    visibleTasks.length ? `Доступно заданий: ${visibleTasks.length}` : "Доступных заданий нет",
    "visually-hidden",
  );
  availableStatus.setAttribute("role", "status");
  boundary.append(actions, availableStatus);
  if (!visibleTasks.length) {
    boundary.append(element("p", "Новые задания появятся здесь.", "compact-empty"));
    replaceContent(boundary);
    restoreModerationFocus();
    restoreProfileFocus();
    return;
  }
  const list = element("div", undefined, "list");
  let focusTarget = null;
  for (const task of visibleTasks) {
    const button = taskListCard(task);
    button.addEventListener("click", () => showTaskDetail(task));
    if (task.id === returnFocusTaskId) focusTarget = button;
    list.append(button);
  }
  boundary.append(list);
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
  const meta = element("div", undefined, "task-meta");
  meta.append(
    element("span", `✦ ${task.credit_reward_per_performer} кред.`),
    element("span", `${task.performer_slots} ${task.performer_slots === 1 ? "место" : "места"}`),
  );
  const deadline = element(
    "time",
    task.deadline_at
      ? `до ${new Intl.DateTimeFormat("ru", { day: "numeric", month: "short" }).format(new Date(task.deadline_at))}`
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

function showCatalogFilters(push = true) {
  const nextState = { screen: "catalog-filters" };
  if (push) history.pushState(nextState, "", presentationLocationFor("T02"));
  else history.replaceState(nextState, "", presentationLocationFor("T02"));
  setNavigation("", true);
  title.textContent = "Фильтры заданий";
  back.classList.remove("hidden");
  const form = element("form", undefined, "task-form card");
  const formatLabel = element("label", "Формат");
  const format = element("select");
  format.append(new Option("Любой", ""), new Option("Онлайн", "online"), new Option("Офлайн", "offline"));
  format.value = catalogFilters.format;
  formatLabel.append(format);
  const rewardLabel = element("label", "Награда от");
  const reward = element("input");
  reward.type = "number";
  reward.min = "1";
  reward.value = catalogFilters.minReward;
  rewardLabel.append(reward);
  const apply = element("button", "Применить", "primary");
  apply.type = "submit";
  form.append(formatLabel, rewardLabel, apply);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    catalogFilters = { format: format.value, minReward: reward.value };
    history.replaceState({ screen: "catalog" }, "", presentationLocationFor("T01"));
    showCatalog();
  });
  replaceContent(connectedBoundary("T02", "content", form));
  format.focus({ preventScroll: true });
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
  const values = draft.values;
  const form = element("form", undefined, "task-form");
  form.classList.add("creation-form");
  form.innerHTML = '<fieldset class="type-field"><legend>Тип задания *</legend><select class="visually-hidden" name="task_kind" aria-label="Тип задания *" required><option value="solo">Личное</option><option value="group">Групповое</option></select><div class="type-segmented"><button type="button" data-kind="solo">Личное</button><button type="button" data-kind="group">Групповое</button></div></fieldset><div class="form-grid two-columns" data-format-row><label class="section">Число исполнителей *<input name="performer_slots" aria-label="Число исполнителей *" type="number" min="1" required></label><label class="section">Формат *<select name="format" aria-label="Формат *" required><option value="online">Онлайн</option><option value="offline">Офлайн</option></select></label></div><label class="section">Категория *<select name="category_id" aria-label="Категория *" required></select></label><label class="section">Название *<input name="title" aria-label="Название *" required><small>Коротко и с понятным результатом</small></label><label class="section">Что нужно сделать *<textarea name="description" aria-label="Что нужно сделать *" required></textarea></label><label class="section">Критерии приёмки *<textarea name="completion_criteria" aria-label="Критерии приёмки *" required></textarea><small>Проверяемые условия, по которым принимается каждый слот</small></label><div class="form-grid two-columns"><label class="section">Размер *<select name="time_size" aria-label="Размер *" required></select></label><label class="section">Награда за исполнителя *<input name="credit_reward_per_performer" aria-label="Награда за исполнителя *" type="number" min="1" required></label></div><p class="reserve-summary"><span>Резерв</span><strong data-reserve>—</strong></p><label class="section">Срок *<input name="deadline_at" aria-label="Срок *" type="datetime-local" required></label><label class="section">Материалы<textarea name="material_text" aria-label="Материалы"></textarea><small>Ссылка или короткий текст</small></label>';
  for (const item of state.categories) form.category_id.append(new Option(item.icon + " " + item.name, item.id));
  for (const item of state.time_sizes) form.time_size.append(new Option(item.value.toUpperCase() + " · " + item.label, item.value));
  for (const name of ["task_kind", "category_id", "time_size", "format"]) if (values[name]) form[name].value = values[name];
  let groupSlots = values.task_kind === "group" && Number(values.performer_slots) >= 2
    ? Number(values.performer_slots) : 2;
  const syncTaskKind = () => {
    const group = form.task_kind.value === "group";
    for (const button of form.querySelectorAll("[data-kind]")) {
      button.setAttribute("aria-pressed", String(button.dataset.kind === form.task_kind.value));
    }
    form.performer_slots.disabled = !group;
    form.performer_slots.min = group ? "2" : "1";
    form.performer_slots.value = String(group ? groupSlots : 1);
    updateReserve();
  };
  for (const button of form.querySelectorAll("[data-kind]")) {
    button.addEventListener("click", () => {
      if (form.task_kind.value === "group" && Number(form.performer_slots.value) >= 2) {
        groupSlots = Number(form.performer_slots.value);
      }
      form.task_kind.value = button.dataset.kind;
      syncTaskKind();
    });
  }
  for (const name of ["title", "description", "completion_criteria"]) form[name].value = values[name] || "";
  form.credit_reward_per_performer.value = values.credit_reward_per_performer || "";
  form.deadline_at.value = values.deadline_at?.slice(0, 16) || "";
  const deadlineMin = new Date(Date.now() + 60_000);
  deadlineMin.setSeconds(0, 0);
  form.deadline_at.min = new Date(deadlineMin - deadlineMin.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
  form.performer_slots.value = values.performer_slots || 1;
  form.material_text.value = values.materials?.text || values.materials?.url || "";
  const submit = element("button", "Предварительный просмотр", "primary");
  submit.type = "submit";
  submit.setAttribute("aria-label", "Предварительный просмотр");
  const reserve = form.querySelector("[data-reserve]");
  const updateReserve = () => {
    const slots = Number(form.performer_slots.value || 0);
    const reward = Number(form.credit_reward_per_performer.value || 0);
    reserve.textContent = slots && reward ? `${slots * reward} кредитов` : "—";
  };
  form.performer_slots.addEventListener("input", updateReserve);
  form.performer_slots.addEventListener("input", () => {
    if (form.task_kind.value === "group" && Number(form.performer_slots.value) >= 2) {
      groupSlots = Number(form.performer_slots.value);
    }
  });
  form.credit_reward_per_performer.addEventListener("input", updateReserve);
  const deadlineStatus = element("p", "Выберите будущий срок.", "status hidden");
  deadlineStatus.id = "deadline-status";
  deadlineStatus.setAttribute("aria-live", "polite");
  form.deadline_at.setAttribute("aria-describedby", deadlineStatus.id);
  const updateDeadlineValidity = () => {
    const expired = form.deadline_at.validity.rangeUnderflow;
    form.deadline_at.setAttribute("aria-invalid", String(expired));
    deadlineStatus.classList.toggle("hidden", !expired);
    submit.disabled = expired;
  };
  form.deadline_at.addEventListener("input", updateDeadlineValidity);
  form.deadline_at.parentElement.append(deadlineStatus);
  const saveStatus = element("p", "", "status hidden");
  saveStatus.setAttribute("aria-live", "polite");
  form.append(submit, saveStatus);
  let selectedCity = values.format === "offline" ? values.city || "" : "";
  let cityField = null;
  let cityTimer = null;
  const syncFormat = () => {
    if (form.format.value !== "offline") {
      selectedCity = "";
      cityField?.remove();
      cityField = null;
      return;
    }
    if (cityField) return;
    cityField = element("label", "Город *", "section city-field");
    const input = element("input");
    input.name = "city";
    input.autocomplete = "off";
    input.placeholder = "Начните вводить город";
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-expanded", "false");
    input.required = true;
    input.value = selectedCity;
    const results = element("div", undefined, "city-results hidden");
    results.id = "task-city-results";
    results.setAttribute("role", "listbox");
    input.setAttribute("aria-controls", results.id);
    const choose = (item) => {
      selectedCity = item.value;
      input.value = item.label;
      input.setCustomValidity("");
      input.setAttribute("aria-expanded", "false");
      results.classList.add("hidden");
    };
    input.addEventListener("input", () => {
      selectedCity = "";
      input.setCustomValidity("Выберите город из списка.");
      clearTimeout(cityTimer);
      const query = input.value.trim();
      if (!query) {
        results.classList.add("hidden");
        input.setAttribute("aria-expanded", "false");
        return;
      }
      cityTimer = setTimeout(async () => {
        const response = await getJson(`/api/v1/task-cities?q=${encodeURIComponent(query)}&limit=8`);
        if (!cityField?.isConnected || input.value.trim() !== query) return;
        results.replaceChildren();
        for (const item of response.items) {
          const option = element("button", item.label, "city-option");
          option.type = "button";
          option.setAttribute("role", "option");
          option.addEventListener("click", () => choose(item));
          results.append(option);
        }
        results.classList.toggle("hidden", !response.items.length);
        input.setAttribute("aria-expanded", String(Boolean(response.items.length)));
      }, 200);
    });
    input.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        results.querySelector("button")?.focus();
      }
    });
    cityField.append(input, results);
    form.querySelector("[data-format-row]").after(cityField);
  };
  form.format.addEventListener("change", syncFormat);
  syncFormat();
  syncTaskKind();
  updateReserve();
  updateDeadlineValidity();
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
      }
      await taskCreationCommand({ action: "save", draft_id: target.id, expected_revision: target.revision, form: { ...value, credit_reward_per_performer: Number(value.credit_reward_per_performer), performer_slots: Number(value.performer_slots), deadline_at: new Date(value.deadline_at).toISOString(), materials } });
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
        city.reportValidity();
      }
      saveStatus.textContent = error.message === "invalid_task_city"
        ? "Выберите город из списка."
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
  title.textContent = "Создать задание";
  back.classList.remove("hidden");
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

const boundaryError = (heading, message, retry) => {
  const node = element("section", undefined, "section profile-boundary");
  node.append(element("h3", heading));
  node.append(element("p", message, "status"));
  node.append(retry);
  return node;
};

const valueSection = (heading, value) => {
  const normalized = Array.isArray(value) ? value.join(", ") : value;
  return normalized == null || normalized === ""
    ? null
    : section(heading, String(normalized));
};

const reliabilityText = (value) => value == null ? "Недостаточно данных" : String(value);
const reliabilityPercent = (value) => value == null ? "—" : `${Math.round(Number(value) * 100)}%`;
const valueOrDash = (value) => value == null ? "—" : String(value);
const initialsFor = (name) => name.split(/\s+/).filter(Boolean).slice(0, 2)
  .map((part) => part[0]).join("").toUpperCase() || "?";

const editableProfileFields = [
  ["display_name", "Имя"],
  ["city", "Город"],
  ["timezone", "Часовой пояс"],
  ["short_bio", "О себе"],
  ["current_goal", "Текущая цель"],
  ["help_categories", "Категории помощи"],
  ["skill_tags", "Навыки"],
  ["availability", "Доступность"],
];

const profileValue = (me, field) => Array.isArray(me[field])
  ? me[field].join(", ")
  : (me[field] ?? "");

function profileFields(me, state, revision) {
  const section = element("section", undefined, "profile-section profile-fields");
  section.append(element("h3", "Параметры профиля", "section-label"));
  const list = element("div", undefined, "profile-field-list");
  for (const [field, label] of editableProfileFields) {
    const draft = state.profileEdit?.field === field ? state.profileEdit : null;
    if (!draft) {
      const row = element("button", undefined, "profile-field-row");
      row.type = "button";
      row.append(
        element("span", label),
        element("strong", profileValue(me, field) || "Не указано"),
      );
      row.addEventListener("click", () => {
        state.profileEdit = {
          field,
          value: profileValue(me, field),
          operationKey: null,
          message: "",
        };
        showProfileState(state, revision);
        content.querySelector(`[data-profile-field="${field}"]`)?.focus({ preventScroll: true });
      });
      list.append(row);
      continue;
    }
    const form = element("form", undefined, "profile-field-editor");
    const inputLabel = element("label", label, "visually-hidden");
    const multiline = ["short_bio", "current_goal", "availability"].includes(field);
    const input = element(multiline ? "textarea" : "input");
    input.dataset.profileField = field;
    input.value = draft.value;
    inputLabel.append(input);
    input.addEventListener("input", () => {
      draft.value = input.value;
      draft.operationKey = null;
      draft.message = "";
    });
    const actions = element("div", undefined, "profile-field-actions");
    const save = element("button", "Сохранить", "primary");
    save.type = "submit";
    markTransition(save, "PE-063", "authoritative_profile_success");
    const cancel = element("button", "Отмена", "secondary");
    cancel.type = "button";
    cancel.addEventListener("click", () => {
      state.profileEdit = null;
      showProfileState(state, revision);
    });
    actions.append(save, cancel);
    const status = element("p", draft.message, draft.message ? "profile-field-status" : "hidden");
    status.setAttribute("aria-live", "polite");
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      save.disabled = true;
      cancel.disabled = true;
      status.className = "profile-field-status";
      status.textContent = "Сохраняем…";
      draft.operationKey ||= newOperationKey();
      try {
        const updated = await submissionRequest(
          "/api/v1/me/profile",
          "PUT",
          draft.operationKey,
          { field, value: draft.value },
        );
        if (revision !== screenRevision) return;
        state.profile = { me: updated, member: state.profile.member };
        state.profileEdit = null;
        showProfileState(state, revision);
      } catch (error) {
        if (revision !== screenRevision) return;
        if (!retryableSubmissionError(error)) draft.operationKey = null;
        draft.message = error?.status === 422
          ? "Проверьте значение поля."
          : error?.status === 409
            ? "Значение уже изменилось. Повторите сохранение."
            : "Не удалось сохранить. Повторите попытку — запрос останется тем же.";
        status.textContent = draft.message;
        save.disabled = false;
        cancel.disabled = false;
      }
    });
    form.append(inputLabel, actions, status);
    list.append(form);
  }
  section.append(list);
  return section;
}

function profileDetails(me, member, state, revision) {
  const view = element("section", undefined, "profile-dashboard");
  const identity = element("div", undefined, "profile-identity");
  const identityCopy = element("div", undefined, "identity-copy");
  identity.append(
    element("span", initialsFor(me.display_name), "avatar"),
    identityCopy,
  );
  identityCopy.append(
    element("h2", me.display_name),
    element("p", me.level?.display_name ? `Уровень ${me.level.number} · ${me.level.display_name}` : "Профиль участника", "muted"),
  );
  const metrics = element("div", undefined, "metric-grid");
  for (const [value, label] of [
    [valueOrDash(me.credit_balance), "Кредиты"],
    [valueOrDash(me.experience_total), "Опыт"],
    [valueOrDash(member.karma?.score), "Карма"],
  ]) {
    const metric = element("article", undefined, "metric-card");
    metric.append(element("strong", value), element("span", label));
    metrics.append(metric);
  }
  const indicators = element("section", undefined, "profile-section");
  const indicatorList = element("div", undefined, "indicator-list");
  indicators.append(element("h3", "Мои показатели", "section-label"), indicatorList);
  for (const [label, value] of [
    ["Завершено заданий", me.statistics?.completed_tasks],
    ["Создано заданий", me.statistics?.created_tasks],
    ["Надёжность", reliabilityPercent(member.reliability?.rate)],
  ]) {
    const row = element("p", undefined, "indicator-row");
    row.append(element("span", label), element("strong", valueOrDash(value)));
    indicatorList.append(row);
  }
  view.append(identity, metrics, indicators, profileFields(me, state, revision));
  return view;
}

function leaderboardDetails(items) {
  const boundary = element("section", undefined, "leaderboard-boundary");
  if (!items.length) {
    boundary.append(element("p", "В лидерборде пока никого нет.", "status muted"));
    return boundary;
  }
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
      element("span", `${item.experience} XP`, "leaderboard-value"),
    );
    button.addEventListener("click", () => showMemberProfile(item.member_id));
    row.append(button);
    list.append(row);
  }
  boundary.append(list);
  return boundary;
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
      .filter(Boolean).slice(0, 3).join(" · ") || member.availability;
    copy.append(identity);
    if (metadata) copy.append(element("span", metadata, "member-row-metadata"));
    const stats = element("span", undefined, "member-row-stats");
    stats.append(
      element("span", `Карма ${member.karma.score}`),
      element("span", `Надёжность ${reliabilityPercent(member.reliability?.rate)}`),
    );
    copy.append(stats);
    button.append(
      element("span", initialsFor(member.display_name), "member-avatar"),
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
  title.textContent = state.view === "leaderboard" ? "Лидерборд" : "Участники";
  const boundary = element("section", undefined, "state-view participants-view");
  boundary.dataset.screenId = state.view === "leaderboard" ? "P05" : "P01";
  boundary.dataset.uiEngine = "concept-05";
  boundary.dataset.state = state.loading ? "loading" : state.error ? "error" : "content";
  const tabs = element("div", undefined, "segmented participants-tabs");
  const membersTab = element("button", "Участники");
  const leaderboardTab = element("button", "Лидерборд");
  membersTab.type = leaderboardTab.type = "button";
  leaderboardTab.dataset.transitionId = "PE-057";
  leaderboardTab.dataset.transitionTrigger = "open_leaderboard";
  membersTab.setAttribute("aria-pressed", String(state.view === "members"));
  leaderboardTab.setAttribute("aria-pressed", String(state.view === "leaderboard"));
  membersTab.addEventListener("click", () => switchParticipantsView(state, revision, "members"));
  leaderboardTab.addEventListener(
    "click",
    () => switchParticipantsView(state, revision, "leaderboard"),
  );
  tabs.append(membersTab, leaderboardTab);
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
    periods.setAttribute("aria-label", "Период лидерборда");
    for (const [period, label] of [
      ["week", "Неделя"],
      ["month", "Месяц"],
      ["all", "Всё время"],
    ]) {
      const button = element("button", label);
      button.type = "button";
      button.setAttribute("aria-pressed", String(state.period === period));
      button.addEventListener("click", () => selectLeaderboardPeriod(state, revision, period));
      periods.append(button);
    }
    boundary.append(periods);
  }
  if (state.loading) {
    boundary.append(element("p", "Загружаем данные…", "status muted"));
  } else if (state.error) {
    const retry = element("button", "Повторить", "secondary");
    retry.type = "button";
    retry.addEventListener("click", () => {
      if (state.view === "leaderboard") void loadParticipantsLeaderboard(state, revision);
      else void loadMembers(state, revision);
    });
    boundary.append(element("p", "Не удалось загрузить данные.", "status"), retry);
  } else if (state.view === "leaderboard") {
    boundary.append(leaderboardDetails(state.leaderboards[state.period] || []));
  } else {
    boundary.append(memberListDetails(state.members || []));
  }
  replaceContent(boundary);
  if (state.focusHeading) {
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
  const path = `/api/v1/leaderboard?limit=30&period=${period}`;
  const cached = cachedJson(path);
  if (cached) state.leaderboards[period] = cached.items;
  state.loading = !cached;
  state.error = false;
  showParticipantsState(state, revision);
  try {
    const page = await getJson(path, (refreshed) => {
      if (
        revision !== screenRevision
        || request !== state.leaderboardRequest
        || state.period !== period
      ) return;
      state.leaderboards[period] = refreshed.items;
      state.loading = false;
      state.error = false;
      showParticipantsState(state, revision);
    });
    if (revision !== screenRevision || request !== state.leaderboardRequest) return;
    if (cached) return;
    state.leaderboards[period] = page.items;
  } catch {
    if (revision !== screenRevision || request !== state.leaderboardRequest) return;
    state.error = !cached;
  }
  state.loading = false;
  showParticipantsState(state, revision);
}

function selectLeaderboardPeriod(state, revision, period) {
  if (state.period === period) return;
  state.period = period;
  state.error = false;
  history.replaceState(
    { screen: "participants", view: "leaderboard", period },
    "",
    presentationLocationFor("P05"),
  );
  if (state.leaderboards[period] === undefined) void loadParticipantsLeaderboard(state, revision);
  else {
    state.leaderboardRequest += 1;
    state.loading = false;
    showParticipantsState(state, revision);
  }
}

function switchParticipantsView(state, revision, view) {
  state.view = view;
  state.error = false;
  state.focusHeading = view === "leaderboard";
  history.replaceState(
    { screen: "participants", view, period: state.period },
    "",
    presentationLocationFor(view === "leaderboard" ? "P05" : "P01"),
  );
  if (view === "leaderboard" && state.leaderboards[state.period] === undefined) {
    void loadParticipantsLeaderboard(state, revision);
  } else if (view === "members" && state.members === null) {
    void loadMembers(state, revision);
  } else {
    showParticipantsState(state, revision);
  }
}

function loadParticipants(view = "members", period = "week") {
  const revision = ++screenRevision;
  const state = {
    view,
    query: "",
    members: null,
    period,
    leaderboards: {},
    leaderboardRequest: 0,
    loading: false,
    error: false,
  };
  switchParticipantsView(state, revision, view);
}

function safeMemberDetails(member) {
  const card = element("article", undefined, "card detail");
  card.append(element("h3", member.display_name));
  const fields = [
    ["Telegram", member.telegram_username ? "@" + member.telegram_username : null],
    ["Город", member.city],
    ["О себе", member.short_bio],
    ["Текущая цель", member.current_goal],
    ["Категории помощи", member.help_categories],
    ["Навыки", member.skill_tags],
    ["Доступность", member.availability],
    ["Опыт", member.experience_total],
    ["Уровень", member.level_number],
    ["Карма", String(member.karma.score) + " · оценок: " + String(member.karma.count)],
    ["Надёжность", reliabilityText(member.reliability.rate)],
  ];
  for (const [heading, value] of fields) {
    const item = valueSection(heading, value);
    if (item) card.append(item);
  }
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
    edit.disabled = true;
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
      edit.disabled = false;
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
  back.classList.remove("hidden");
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
  const details = safeMemberDetails(state.member);
  const nodes = [details];
  if (state.message) nodes.push(element("p", state.message, "status success"));
  if (state.member.member_id !== currentMemberId) {
    const rate = element("button", "Оценить карму", "primary");
    rate.type = "button";
    rate.addEventListener("click", () => openKarmaEditor(state, revision));
    details.append(rate);
  }
  replaceContent(connectedBoundary("P02", "content", ...nodes));
}

async function showMemberProfile(memberId, push = true) {
  const revision = ++screenRevision;
  const state = { member: null, error: false, karma: null, message: "" };
  if (push) history.pushState({ screen: "member-profile", memberId }, "", presentationLocationFor("P02", memberId));
  setNavigation("", true);
  title.textContent = "Профиль участника";
  back.classList.remove("hidden");
  showMemberState(state, revision);
  back.focus({ preventScroll: true });
  try {
    state.member = await getJson("/api/v1/members/" + encodeURIComponent(memberId));
  } catch {
    state.error = true;
  }
  showMemberState(state, revision);
}

function showProfileState(state, revision) {
  if (revision !== screenRevision) return;
  const profileBoundary = state.profile
    ? profileDetails(state.profile.me, state.profile.member, state, revision)
    : state.profileError
      ? boundaryError("Мои показатели", "Не удалось загрузить профиль.", state.profileRetry)
      : element("p", "Загружаем профиль…", "status muted");
  replaceContent(connectedBoundary(
    "P06",
    state.profile ? "content" : state.profileError ? "error" : "loading",
    profileBoundary,
  ));
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
}

function loadProfile(push = true) {
  const revision = ++screenRevision;
  const cachedMe = cachedJson("/api/v1/me");
  const cachedMember = cachedMe
    ? cachedJson("/api/v1/members/" + encodeURIComponent(cachedMe.member_id))
    : null;
  const state = {
    profile: cachedMe && cachedMember ? { me: cachedMe, member: cachedMember } : null,
    profileError: false,
  };
  state.profileRetry = element("button", "Повторить профиль", "secondary");
  state.profileRetry.type = "button";
  state.profileRetry.addEventListener("click", () => loadOwnProfile(state, revision));
  returnFocusProfile = true;
  if (push) history.replaceState({ screen: "profile" }, "", presentationLocationFor("P06"));
  setNavigation("profile", false);
  title.textContent = "Профиль";
  back.classList.add("hidden");
  showProfileState(state, revision);
  back.focus({ preventScroll: true });
  void loadOwnProfile(state, revision);
}

function showTaskDetail(task, push = true) {
  screenRevision += 1;
  returnFocusTaskId = task.id;
  setNavigation("", true);
  shell.classList.add("task-detail-screen");
  title.textContent = "Карточка задания";
  back.classList.remove("hidden");
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
      onEdit: () => history.back(),
      onConfirm: ({ confirm, edit, status: actionStatus }) => {
        edit.disabled = true;
        void acceptTask(task, confirm, actionStatus).finally(() => { edit.disabled = false; });
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
    history.replaceState({ screen: "assignment", assignmentId: payload.id }, "", presentationLocationFor("M03", payload.id));
    await showAssignmentDetail(payload.id, false);
  } catch (error) {
    status.textContent = error instanceof TypeError
      ? "Сеть недоступна. Повторите попытку — запрос останется тем же."
      : "Задание сейчас недоступно. Вернитесь к заданиям и попробуйте другое.";
    if (!retryableSubmissionError(error)) pendingAcceptKeys.delete(task.id);
    button.disabled = false;
  }
}

function showAssignments(revision = ++screenRevision) {
  if (revision !== screenRevision) return;
  setNavigation("assignments", false);
  title.textContent = "Мои задания";
  back.classList.add("hidden");
  const boundary = element("section", undefined, "state-view");
  boundary.dataset.screenId = "M01";
  boundary.dataset.uiEngine = "concept-05";
  boundary.dataset.state = assignments.length ? "content" : "empty";
  boundary.append(element("p", "Работа и проверки в одном месте", "screen-subtitle"));
  const tabs = element("div", undefined, "segmented root-tabs");
  const active = element("button", `В работе · ${assignments.length}`, "active-tab");
  active.type = "button";
  active.addEventListener("click", () => showTakenAssignments());
  createdAssignmentsButton.classList.remove("active-tab");
  createdAssignmentsButton.disabled = false;
  tabs.append(active, createdAssignmentsButton);
  boundary.append(tabs);
  if (!assignments.length) {
    boundary.append(element("p", "Активных заданий пока нет.", "compact-empty"));
    replaceContent(boundary);
    restoreModerationFocus();
    return;
  }
  const summary = element("button", undefined, "card assignment-card");
  summary.type = "button";
  summary.append(
    element("h3", "Взятые мной"),
    element("p", `${assignments.length} активных назначений`, "muted"),
  );
  summary.addEventListener("click", () => showTakenAssignments());
  boundary.append(summary);
  replaceContent(boundary);
  restoreModerationFocus();
}

function showTakenAssignments() {
  screenRevision += 1;
  history.replaceState({ screen: "assignments-taken" }, "", presentationLocationFor("M02"));
  setNavigation("assignments", false);
  title.textContent = "Мои задания";
  back.classList.add("hidden");
  const boundary = connectedBoundary("M02", "content");
  boundary.append(element("p", "Взятые мной", "screen-subtitle"));
  const tabs = element("div", undefined, "segmented root-tabs");
  const active = element("button", `В работе · ${assignments.length}`, "active-tab");
  active.type = "button";
  active.disabled = true;
  createdAssignmentsButton.classList.remove("active-tab");
  createdAssignmentsButton.disabled = false;
  tabs.append(active, createdAssignmentsButton);
  boundary.append(tabs);
  const list = element("ul", undefined, "list");
  let focusTarget = null;
  for (const assignment of assignments) {
    const button = element("button", undefined, "card assignment-card");
    button.type = "button";
    const chips = element("div", undefined, "card-chips");
    chips.append(element("span", assignmentStatus(assignment.assignment_status), "chip"));
    const deadline = element("p", "Срок: ", "meta");
    deadline.append(time(assignment.task_deadline_at));
    button.append(
      chips,
      element("h3", assignment.task_title),
      deadline,
    );
    if (assignment.result_summary) {
      button.append(element("p", assignment.result_summary, "muted"));
    }
    button.addEventListener("click", () => showAssignmentDetail(assignment.id));
    if (assignment.id === returnFocusAssignmentId) focusTarget = button;
    const item = element("li");
    item.append(button);
    list.append(item);
  }
  boundary.append(list);
  replaceContent(boundary);
  focusTarget?.focus({ preventScroll: true });
  returnFocusAssignmentId = null;
  restoreModerationFocus();
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
  completed: "Завершено",
  cancelled: "Отменено",
}[value] || value);

function showOwnedTask(task, push = true) {
  if (push) history.pushState({ screen: "owned-task", task }, "", presentationLocationFor("M10", task.id));
  setNavigation("", true);
  title.textContent = "Созданное задание";
  back.classList.remove("hidden");
  const detail = element("article", undefined, "card detail");
  detail.append(
    element("h3", task.title),
    section("Статус", createdTaskStatus(task.status)),
    section("Слоты", `${task.assignees.length}/${task.performer_slots}`),
  );
  for (const assignee of task.assignees) {
    detail.append(section(assignee.display_name, assignmentStatus(assignee.status)));
  }
  if (task.cancellation_action) {
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
    onEdit: () => showOwnedTask(task, false),
    onConfirm: async ({ confirm, edit, status }) => {
      confirm.disabled = true;
      edit.disabled = true;
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
        edit.disabled = false;
      }
    },
  });
}

function renderCreatedAssignments(revision) {
  if (revision !== screenRevision) return;
  setNavigation("assignments", false);
  title.textContent = "Мои задания";
  back.classList.add("hidden");
  const boundary = connectedBoundary("M09", "content");
  boundary.classList.add("owned-tasks-view");
  const tabs = element("div", undefined, "segmented root-tabs");
  let focusTarget = null;
  const active = element("button", `В работе · ${assignments.length}`);
  active.type = "button";
  active.addEventListener("click", () => showTakenAssignments());
  createdAssignmentsButton.classList.add("active-tab");
  createdAssignmentsButton.disabled = true;
  tabs.append(active, createdAssignmentsButton);
  boundary.append(tabs);
  if (!ownedTasks.length) {
    boundary.append(element("p", "Созданных заданий пока нет.", "compact-empty"));
  } else {
    const list = element("ul", undefined, "list owned-task-list");
    for (const task of ownedTasks) {
      const card = element("button", undefined, "card owned-task-card");
      card.type = "button";
      const chips = element("div", undefined, "card-chips");
      chips.append(element("span", createdTaskStatus(task.status), "chip muted-chip"));
      if (task.cancellation_status === "pending") {
        chips.append(element("span", "Отмена ожидает", "chip"));
      }
      card.append(
        chips,
        element("h3", task.title),
        element(
          "p",
          `Исполнители ${task.assignees.length}/${task.performer_slots} · ${formatDate(task.deadline_at)}`,
          "meta",
        ),
      );
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
      if (task.id === returnFocusOwnedTaskId) focusTarget = card;
      const item = element("li");
      item.append(card);
      list.append(item);
    }
    boundary.append(list);
  }
  if (ownedReviews.length) {
    const reviewList = element("ul", undefined, "list owned-review-list");
    for (const review of ownedReviews) {
      const button = element("button", undefined, "card owned-task-card");
      button.type = "button";
      button.append(
        element("span", "Ожидает проверки", "chip"),
        element("h3", review.task_title),
        element("p", "Исполнитель: " + review.performer_display_name, "meta"),
      );
      button.addEventListener("click", () => showCreatedReview(review.id));
      if (review.id === returnFocusReviewId) focusTarget = button;
      const item = element("li");
      item.append(button);
      reviewList.append(item);
    }
    boundary.append(reviewList);
  }
  replaceContent(boundary);
  focusTarget?.focus({ preventScroll: true });
  returnFocusOwnedTaskId = null;
  returnFocusReviewId = null;
  const scrollTop = Number(history.state?.scrollTop || 0);
  if (scrollTop) queueMicrotask(() => content.closest(".screen")?.scrollTo({ top: scrollTop }));
}

async function loadCreatedReviews(push = true) {
  const revision = ++screenRevision;
  if (push) history.replaceState({ screen: "created-assignments" }, "", presentationLocationFor("M09"));
  const ownedPath = "/api/v1/owned-tasks";
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
    retry.addEventListener("click", () => loadCreatedReviews(false));
    replaceContent(element("p", "Не удалось загрузить созданные задания.", "status"), retry);
  }
}

async function showCreatedReview(assignmentId, push = true) {
  const revision = ++screenRevision;
  returnFocusReviewId = assignmentId;
  if (push) history.pushState({ screen: "assignment-review", assignmentId }, "", presentationLocationFor("M11", assignmentId));
  setNavigation("", true);
  title.textContent = "Решение по результату";
  back.classList.remove("hidden");
  replaceContent(element("p", "Загружаем результат…", "status muted"));
  try {
    const review = await getJson("/api/v1/assignment-reviews/" + encodeURIComponent(assignmentId));
    if (revision !== screenRevision) return;
    const detail = element("article", undefined, "card detail");
    const status = element("p", "", "status hidden");
    status.setAttribute("aria-live", "polite");
    detail.append(
      element("h3", review.task_title),
      section("Исполнитель", review.performer_display_name),
      section("Результат", review.result),
    );
    if (review.review_deadline_at) {
      detail.append(dateSection("Срок решения", review.review_deadline_at));
    }
    for (const [index, decision] of review.available_decisions.entries()) {
      const button = element("button", decisionLabels[decision], index ? "secondary" : "primary");
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
          history.replaceState(
            { screen: "review-outcome", assignmentId },
            "",
            presentationLocationFor("M13", assignmentId),
          );
          title.textContent = "Решение сохранено";
          const done = element("button", "К созданным заданиям", "primary");
          done.type = "button";
          done.addEventListener("click", () => {
            history.replaceState({ screen: "created-assignments" }, "", presentationLocationFor("M09"));
            void loadCreatedReviews(false);
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
        history.pushState(
          { screen: "assignment-review-confirm", assignmentId },
          "",
          presentationLocationFor("M12", assignmentId),
        );
        showActionConfirmation({
          screenId: "M12",
          headingText: "Подтвердить решение",
          description: decision === "reject"
            ? "Выплата и резерв останутся заморожены на 24 часа для возможного спора. Повторная отправка результата не откроется."
            : `Решение: ${decisionLabels[decision]}.`,
          confirmLabel: decisionLabels[decision],
          transitionId: "PE-040",
          transitionTrigger: "authoritative_review_success",
          onEdit: () => history.back(),
          onConfirm: saveDecision,
        });
      });
      detail.append(button);
    }
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

function submissionPanel(assignment, draft) {
  const submissionRevision = screenRevision;
  const boundary = element("section", undefined, "submission");
  boundary.append(element("h3", "Отправить результат"));
  const status = element("p", "", "status hidden");
  status.setAttribute("aria-live", "polite");

  if (!draft) {
    const begin = element("button", "Начать отправку", "primary");
    begin.type = "button";
    markTransition(begin, "PE-030", "open_result_versions");
    let beginKey = null;
    begin.addEventListener("click", async () => {
      begin.disabled = true;
      status.className = "status";
      status.textContent = "Открываем черновик…";
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
        const payload = await submissionResponse(response);
        const next = submissionPanel(assignment, payload);
        boundary.replaceWith(next);
        next.querySelector("textarea")?.focus({ preventScroll: true });
      } catch (error) {
        status.textContent = submissionMessage(error);
        if (!retryableSubmissionError(error)) beginKey = null;
        begin.disabled = false;
      }
    });
    boundary.append(status, begin);
    return boundary;
  }

  boundary.dataset.screenId = "M04";
  boundary.dataset.uiEngine = "concept-05";

  const form = element("form", undefined, "submission-form");
  const label = element("label", "Результат", "section");
  const input = document.createElement("textarea");
  input.name = "result";
  input.required = true;
  input.rows = 6;
  input.value = typeof draft.result === "string" ? draft.result : "";
  label.htmlFor = "submission-result";
  input.id = "submission-result";
  label.append(input);
  const preview = element("button", "Предпросмотр", "primary");
  preview.type = "submit";
  let saveKey = null;
  let confirmKey = null;

  const addPreview = (saved) => {
    history.replaceState(
      { screen: "assignment-result-preview", assignmentId: assignment.id },
      "",
      presentationLocationFor("M05", assignment.id),
    );
    title.textContent = "Предпросмотр результата";
    const card = element("article", undefined, "card detail preview-grid");
    card.append(element("p", "Предпросмотр", "badge"), element("p", typeof saved.result === "string" ? saved.result : ""));
    const proceed = element("button", "Продолжить", "primary");
    proceed.type = "button";
    proceed.addEventListener("click", () => {
      history.replaceState(
        { screen: "assignment-submission-confirm", assignmentId: assignment.id },
        "",
        presentationLocationFor("M06", assignment.id),
      );
      showActionConfirmation({
        screenId: "M06",
        headingText: "Подтвердить отправку",
        description: typeof saved.result === "string" ? saved.result : "",
        confirmLabel: "Отправить результат",
        transitionId: "PE-034",
        transitionTrigger: "authoritative_submit_success",
        onEdit: () => {
          history.replaceState(
            { screen: "assignment-submission", assignmentId: assignment.id },
            "",
            presentationLocationFor("M04", assignment.id),
          );
          title.textContent = "Редактор результата";
          replaceContent(connectedBoundary("M04", "content", submissionPanel(assignment, saved)));
          content.querySelector("textarea")?.focus({ preventScroll: true });
        },
        onConfirm: async ({ confirm, edit, status: actionStatus }) => {
          confirm.disabled = true;
          edit.disabled = true;
          actionStatus.className = "status";
          actionStatus.textContent = "Отправляем результат…";
          confirmKey ||= newOperationKey();
          try {
            await submissionRequest(
              "/api/v1/submission-drafts/" + encodeURIComponent(saved.id) + "/confirm",
              "POST",
              confirmKey,
              { expected_revision: saved.revision },
            );
            if (submissionRevision === screenRevision) {
              const done = element("button", "К заданию", "primary");
              done.type = "button";
              done.addEventListener("click", () => history.back());
              title.textContent = "Результат отправлен";
              history.replaceState(
                { screen: "assignment-submission-success", assignmentId: assignment.id },
                "",
                presentationLocationFor("M07", assignment.id),
              );
              replaceContent(connectedBoundary("M07", "success", element("p", "Результат сохранён и отправлен на проверку.", "status success"), done));
            }
          } catch (error) {
            actionStatus.textContent = submissionMessage(error);
            if (!retryableSubmissionError(error)) confirmKey = null;
            confirm.disabled = false;
            edit.disabled = false;
          }
        },
      });
    });
    card.append(proceed);
    replaceContent(connectedBoundary("M05", "content", card));
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    preview.disabled = true;
    status.className = "status";
    status.textContent = "Сохраняем предпросмотр…";
    saveKey ||= newOperationKey();
    try {
      const saved = await submissionRequest(
        "/api/v1/submission-drafts/" + encodeURIComponent(draft.id),
        "PUT",
        saveKey,
        { expected_revision: draft.revision, payload: { result: input.value } },
      );
      draft = saved;
      saveKey = null;
      status.className = "status success";
      status.textContent = "Предпросмотр сохранён. Подтвердите отправку.";
      addPreview(saved);
    } catch (error) {
      status.textContent = submissionMessage(error);
      if (!retryableSubmissionError(error)) saveKey = null;
    } finally {
      preview.disabled = false;
    }
  });
  form.append(label, preview);
  boundary.append(form, status);
  if (draft.result !== null) input.value = draft.result;
  return boundary;
}

function openSubmissionEditor(assignment, push = true) {
  if (push) {
    history.pushState(
      { screen: "assignment-submission", assignmentId: assignment.id },
      "",
      presentationLocationFor("M04", assignment.id),
    );
  }
  setNavigation("", true);
  title.textContent = "Редактор результата";
  back.classList.remove("hidden");
  replaceContent(connectedBoundary("M04", "content", submissionPanel(assignment, null)));
  content.querySelector("button")?.focus({ preventScroll: true });
}

function disputePanel(assignment) {
  const form = element("form", undefined, "submission-form");
  const label = element("label", "Почему результат нужно пересмотреть", "section");
  const comment = document.createElement("textarea");
  comment.id = "dispute-comment";
  comment.name = "comment";
  comment.required = true;
  comment.rows = 5;
  label.htmlFor = comment.id;
  label.append(comment);
  const submit = element("button", "Подать спор", "primary");
  submit.type = "submit";
  markTransition(submit, "PE-044", "open_dispute_materials");
  const status = element("p", "", "status hidden");
  status.setAttribute("aria-live", "polite");
  let operationKey = null;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const normalized = comment.value.trim();
    if (!normalized) return;
    showActionConfirmation({
      screenId: "M14",
      headingText: "Подтвердить спор",
      description: normalized + " Комментарий увидит только команда модерации.",
      confirmLabel: "Подать спор",
      transitionId: "PE-044",
      transitionTrigger: "open_dispute_materials",
      onEdit: () => {
        openDisputeEditor(assignment, false);
        const restored = content.querySelector("#dispute-comment");
        if (restored) restored.value = normalized;
        restored?.focus({ preventScroll: true });
      },
      onConfirm: async ({ confirm, edit, status: actionStatus }) => {
        confirm.disabled = true;
        edit.disabled = true;
        actionStatus.className = "status";
        actionStatus.textContent = "Подаём спор…";
        operationKey ||= newOperationKey();
        try {
          await submissionRequest(
            "/api/v1/assignments/" + encodeURIComponent(assignment.id) + "/disputes",
            "POST",
            operationKey,
            { comment: normalized },
          );
          await showAssignmentDetail(assignment.id, false);
        } catch (error) {
          if (error?.status === 409) {
            await showAssignmentDetail(assignment.id, false);
            return;
          }
          actionStatus.textContent = error instanceof TypeError
            ? "Сеть недоступна. Повторите запрос — он останется тем же."
            : "Не удалось подать спор. Проверьте комментарий и состояние назначения.";
          if (!retryableSubmissionError(error)) operationKey = null;
          confirm.disabled = false;
          edit.disabled = false;
        }
      },
    });
  });
  form.append(label, submit, status);
  return form;
}

function openDisputeEditor(assignment, push = true) {
  const nextState = { screen: "assignment-dispute", assignmentId: assignment.id };
  const location = presentationLocationFor("M14", assignment.id);
  if (push) history.pushState(nextState, "", location);
  else history.replaceState(nextState, "", location);
  setNavigation("", true);
  title.textContent = "Открытие спора";
  back.classList.remove("hidden");
  replaceContent(connectedBoundary("M14", "content", disputePanel(assignment)));
  content.querySelector("textarea")?.focus({ preventScroll: true });
}

function cancellationPanel(assignment) {
  const form = element("form", undefined, "submission-form");
  const heading = element("h3", "Отказаться от задания");
  const label = element("label", "Причина отказа", "section");
  const reason = document.createElement("textarea");
  reason.id = "assignment-cancellation-reason";
  reason.name = "reason";
  reason.required = true;
  reason.maxLength = 1000;
  reason.rows = 4;
  label.htmlFor = reason.id;
  label.append(reason);
  const submit = element("button", "Подтвердить отказ", "secondary danger");
  submit.type = "submit";
  markTransition(submit, "PE-036", "withdrawal_outcome");
  const status = element("p", "", "status hidden");
  status.setAttribute("aria-live", "polite");
  let operationKey = null;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const normalized = reason.value.trim();
    if (!normalized) return;
    showActionConfirmation({
      screenId: "M08",
      headingText: "Подтвердить отказ",
      description: normalized + " Слот будет освобождён.",
      confirmLabel: "Отказаться от задания",
      transitionId: "PE-036",
      transitionTrigger: "withdrawal_outcome",
      onEdit: () => {
        openCancellationEditor(assignment, false);
        const restored = content.querySelector("#assignment-cancellation-reason");
        if (restored) restored.value = normalized;
        restored?.focus({ preventScroll: true });
      },
      onConfirm: async ({ confirm, edit, status: actionStatus }) => {
        confirm.disabled = true;
        edit.disabled = true;
        actionStatus.className = "status";
        actionStatus.textContent = "Отказываемся от задания…";
        operationKey ||= newOperationKey();
        try {
          await submissionRequest(
            "/api/v1/assignments/" + encodeURIComponent(assignment.id) + "/cancellation",
            "POST",
            operationKey,
            { reason: normalized },
          );
          history.replaceState({ screen: "assignments" }, "", presentationLocationFor("M01"));
          await loadAssignments(false);
        } catch (error) {
          actionStatus.textContent = error instanceof TypeError
            ? "Сеть недоступна. Повторите запрос — он останется тем же."
            : "Не удалось отказаться. Проверьте состояние назначения и повторите.";
          if (!retryableSubmissionError(error)) operationKey = null;
          confirm.disabled = false;
          edit.disabled = false;
        }
      },
    });
  });
  form.append(heading, label, submit, status);
  return form;
}

function openCancellationEditor(assignment, push = true) {
  const nextState = { screen: "assignment-cancellation", assignmentId: assignment.id };
  const location = presentationLocationFor("M08", assignment.id);
  if (push) history.pushState(nextState, "", location);
  else history.replaceState(nextState, "", location);
  setNavigation("", true);
  title.textContent = "Отказ от задания";
  back.classList.remove("hidden");
  replaceContent(connectedBoundary("M08", "content", cancellationPanel(assignment)));
  content.querySelector("textarea")?.focus({ preventScroll: true });
}

async function showAssignmentDetail(assignmentId, push = true) {
  const revision = ++screenRevision;
  returnFocusAssignmentId = assignmentId;
  if (push) {
    history.pushState(
      { screen: "assignment", assignmentId },
      "",
      presentationLocationFor("M03", assignmentId),
    );
  }
  setNavigation("", true);
  title.textContent = "Активное назначение";
  back.classList.remove("hidden");
  replaceContent(element("p", "Загружаем назначение…", "status muted"));
  try {
    const response = await apiFetch(
      "/api/v1/assignments/" + encodeURIComponent(assignmentId),
      { credentials: "same-origin" },
    );
    if (!response.ok) throw new Error(requestError(response));
    const assignment = await response.json();
    if (revision !== screenRevision) return;
    const detail = element("article", undefined, "card detail");
    detail.append(
      element("h3", assignment.task_title),
      section("Статус", assignmentStatus(assignment.assignment_status)),
      dateSection("Срок", assignment.task_deadline_at),
      section("Описание", assignment.description),
      section("Критерии выполнения", assignment.completion_criteria),
      section("Как выполнять", assignment.performer_instructions),
    );
    if (assignment.result_summary) {
      detail.append(section("Последний результат", assignment.result_summary));
    }
    if (assignment.review_deadline_at) {
      detail.append(dateSection("Срок проверки", assignment.review_deadline_at));
    }
    if (assignment.reject_dispute_deadline_at) {
      detail.append(dateSection("Подать спор до", assignment.reject_dispute_deadline_at));
    }
    if (assignment.case_status) {
      const disputeStatus = section("Спор", "Передан команде модерации");
      disputeStatus.dataset.screenId = "M15";
      disputeStatus.dataset.uiEngine = "concept-05";
      detail.append(disputeStatus);
    } else if (assignment.assignment_status === "rejected_pending_dispute") {
      detail.append(section(
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
      submit.addEventListener("click", () => openSubmissionEditor(assignment));
      actions.append(submit);
    }
    if (assignment.can_dispute) {
      const dispute = element("button", "Подать спор", "secondary");
      dispute.type = "button";
      dispute.addEventListener("click", () => openDisputeEditor(assignment));
      actions.append(dispute);
    }
    if (assignment.can_cancel) {
      const cancel = element("button", "Отказаться от задания", "secondary danger");
      cancel.type = "button";
      cancel.addEventListener("click", () => openCancellationEditor(assignment));
      actions.append(cancel);
    }
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
    return [element("p", "Очередь модерации недоступна для этого аккаунта.", "status")];
  }
  return [
    element("p", "Не удалось загрузить очередь модерации.", "status"),
    retry,
  ];
};

function showModerationCases(cases, revision) {
  if (revision !== screenRevision) return;
  const focusedCaseId = returnFocusModerationCaseId
    || document.activeElement?.closest?.(".moderation-card")?.dataset.caseId;
  setNavigation("moderation", false);
  title.textContent = "Модерация";
  back.classList.add("hidden");
  setHeadingAction(element("span", String(cases.length), "queue-count"));
  const boundary = element("section", undefined, "state-view");
  boundary.dataset.screenId = "S01";
  boundary.dataset.uiEngine = "concept-05";
  boundary.dataset.state = cases.length ? "content" : "empty";
  boundary.append(element("p", "Открытые обращения", "screen-subtitle"));
  if (!cases.length) {
    boundary.append(element("p", "Открытых обращений нет.", "compact-empty"));
    replaceContent(boundary);
    return;
  }
  const list = element("ul", undefined, "list");
  let focusTarget = null;
  for (const item of cases) {
    const actionable = item.case_type === "dispute" && item.status === "open";
    const card = element(actionable ? "button" : "article", undefined, "card moderation-card");
    card.dataset.caseId = item.id;
    if (actionable) card.type = "button";
    const chips = element("div", undefined, "card-chips");
    chips.append(element("span", moderationStatus(item.status), "chip"));
    if (item.case_type !== "dispute") chips.append(element("span", "Проверка", "chip muted-chip"));
    const opened = element("p", "Открыт: ", "meta");
    opened.append(time(item.opened_at));
    card.append(chips, element("h3", moderationCaseType(item.case_type)), opened);
    if (item.current_code) card.append(element("p", "Текущее решение: " + item.current_code, "meta"));
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
}

async function loadModeration(push = true) {
  const revision = ++screenRevision;
  const path = "/api/v1/moderation/cases?limit=20";
  const cached = cachedJson(path);
  returnFocusModeration = true;
  if (push) history.replaceState({ screen: "moderation" }, "", presentationLocationFor("S01"));
  if (cached) {
    showModerationCases(cached.items, revision);
  } else {
    setNavigation("moderation", false);
    title.textContent = "Модерация";
    back.classList.add("hidden");
    replaceContent(
      element("p", "Открытые обращения", "screen-subtitle"),
      element("p", "Загружаем очередь…", "compact-empty"),
    );
  }
  try {
    const page = await getJson(path, (refreshed) => {
      if (revision === screenRevision) showModerationCases(refreshed.items, revision);
    });
    if (revision !== screenRevision) return;
    if (cached) return;
    showModerationCases(page.items, revision);
  } catch (error) {
    if (revision !== screenRevision || cached) return;
    const retry = element("button", "Повторить", "primary");
    retry.type = "button";
    retry.addEventListener("click", () => loadModeration(false));
    replaceContent(element("p", "Открытые обращения", "screen-subtitle"), ...moderationError(error.message, retry));
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
  back.classList.remove("hidden");
  replaceContent(element("p", "Загружаем спор…", "status muted"));
  back.focus({ preventScroll: true });
  try {
    const dispute = await getJson(
      "/api/v1/moderation/cases/" + encodeURIComponent(caseId),
    );
    if (revision !== screenRevision) return;
    const detail = element("article", undefined, "card detail");
    detail.append(
      element("h3", dispute.task_title),
      section("Источник", dispute.task_origin === "community" ? "Сообщество" : "Участник"),
      section("Награда", String(dispute.credit_reward_per_performer) + " кредитов"),
      section("Причина спора", dispute.dispute_reason),
    );
    if (dispute.result_summary) detail.append(section("Результат", dispute.result_summary));

    const form = element("form", undefined, "submission");
    const label = element("label", "Решение");
    const select = element("select");
    select.name = "resolution";
    for (const code of dispute.allowed_resolution_codes) {
      const option = element("option", resolutionLabels[code] || code);
      option.value = code;
      select.append(option);
    }
    label.append(select);
    const reasonLabel = element("label", "Причина решения");
    const reason = element("textarea");
    reason.name = "reason";
    reason.required = true;
    reason.rows = 4;
    reasonLabel.append(reason);
    const status = element("p", "", "status hidden");
    status.setAttribute("aria-live", "polite");
    const review = element("button", "Проверить решение", "primary");
    review.type = "submit";
    let operationKey = null;
    form.append(label, reasonLabel, review, status);
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
          const queue = element("button", "К очереди", "primary");
          queue.type = "button";
          queue.addEventListener("click", () => loadModeration(false));
          replaceContent(connectedBoundary("S04", "success", element("p", "Решение применено.", "status success"), queue));
        } catch (error) {
          actionStatus.textContent = error?.status === 409
            ? "Кейс уже изменился или больше недоступен. Вернитесь в очередь."
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
          : "Не удалось загрузить спор. Вернитесь в очередь и повторите.",
        "status",
      ),
    );
  }
}

async function bootstrap(authAttempted = false) {
  try {
    const me = await apiFetch("/api/v1/me", { credentials: "same-origin" });
    if (me.status === 401 && !authAttempted) {
      const initData = globalThis.Telegram?.WebApp?.initData;
      if (!initData) throw new Error("telegram_init_data_missing");
      const auth = await apiFetch("/api/v1/auth/telegram", {
        method: "POST",
        headers: { "Content-Type": "text/plain; charset=utf-8" },
        body: initData,
        credentials: "same-origin",
      });
      if (!auth.ok) throw new Error("telegram_auth_failed");
      return bootstrap(true);
    }
    if (!me.ok) throw new Error("bootstrap_failed");
    const [profile, page] = await Promise.all([me.json(), getJson("/api/v1/tasks")]);
    storeJson("/api/v1/me", profile);
    currentMemberId = profile.member_id;
    void configureRoleNavigation();
    tasks = page.items;
    const initialPresentation = presentationFromLocation();
    history.replaceState({ screen: "catalog" }, "", presentationLocationFor("T01"));
    showCatalog();
    const presentationId = initialPresentation?.screen.id;
    const resourceId = initialPresentation?.resourceId;
    if (presentationId === "T02") {
      showCatalogFilters(false);
    } else if (presentationId === "T04B") {
      beginTaskCreationFlow(false);
    } else if (["T05", "T06", "T08"].includes(presentationId)) {
      const forceEdit = presentationId === "T05";
      const screenId = forceEdit ? "T05" : "T06";
      history.replaceState(
        { screen: forceEdit ? "task-creation" : "task-preview", draftId: resourceId },
        "",
        presentationLocationFor(screenId, resourceId),
      );
      openTaskCreation(forceEdit, forceEdit ? null : "stale");
    } else if (presentationId === "P01" || presentationId === "P05") {
      loadParticipants(presentationId === "P05" ? "leaderboard" : "members");
    } else if (presentationId === "P06" || presentationId === "P07") {
      history.replaceState({ screen: "profile" }, "", presentationLocationFor("P06"));
      loadProfile(false);
    } else if (presentationId === "M01" || presentationId === "M02") {
      history.replaceState({ screen: "assignments" }, "", presentationLocationFor("M01"));
      loadAssignments(false);
    } else if (presentationId === "M09" || presentationId === "M10") {
      history.replaceState({ screen: "created-assignments" }, "", presentationLocationFor("M09"));
      loadCreatedReviews(false);
    } else if (presentationId === "S01") {
      history.replaceState({ screen: "moderation" }, "", presentationLocationFor("S01"));
      loadModeration(false);
    } else if (["T03", "T03A"].includes(presentationId) && resourceId) {
      const task = tasks.find((item) => item.id === resourceId);
      if (task) {
        history.replaceState({ screen: "task", taskId: task.id }, "", presentationLocationFor("T03", task.id));
        showTaskDetail(task, false);
      }
    } else if (["P02", "P03", "P04"].includes(presentationId) && resourceId) {
      history.replaceState({ screen: "member-profile", memberId: resourceId }, "", presentationLocationFor("P02", resourceId));
      showMemberProfile(resourceId, false);
    } else if (["M03", "M04", "M05", "M06", "M07", "M08", "M14", "M15"].includes(presentationId) && resourceId) {
      history.replaceState({ screen: "assignment", assignmentId: resourceId }, "", presentationLocationFor("M03", resourceId));
      showAssignmentDetail(resourceId, false);
    } else if (["M11", "M12", "M13"].includes(presentationId) && resourceId) {
      history.replaceState({ screen: "assignment-review", assignmentId: resourceId }, "", presentationLocationFor("M11", resourceId));
      showCreatedReview(resourceId, false);
    } else if (["S02", "S03", "S04"].includes(presentationId) && resourceId) {
      history.replaceState({ screen: "moderation-case", caseId: resourceId }, "", presentationLocationFor("S02", resourceId));
      showModerationCase(resourceId, false);
    }
  } catch {
    replaceContent(
      element(
        "p",
        "Не удалось загрузить задания. Откройте Mini App ещё раз.",
        "status",
      ),
    );
  }
}

catalogNav.addEventListener("click", () => {
  void loadCatalog();
});
assignmentsNav.addEventListener("click", () => loadAssignments());
participantsNav.addEventListener("click", () => loadParticipants("members"));
profileNav.addEventListener("click", () => loadProfile());
moderationNav.addEventListener("click", () => loadModeration());
back.addEventListener("click", () => {
  if (history.state?.screen === "participants" && history.state.view === "leaderboard") {
    returnFocusLeaderboardTab = true;
    loadParticipants("members");
  } else {
    history.back();
  }
});
globalThis.addEventListener("popstate", (event) => {
  if (event.state?.screen === "participants") {
    loadParticipants(event.state.view || "members", event.state.period || "week");
  } else if (event.state?.screen === "task") {
    const task = tasks.find((item) => item.id === event.state.taskId);
    if (task) showTaskDetail(task, false);
  } else if (event.state?.screen === "assignments") {
    showAssignments();
  } else if (event.state?.screen === "assignments-taken") {
    showTakenAssignments();
  } else if (event.state?.screen === "created-assignments") {
    loadCreatedReviews(false);
  } else if (event.state?.screen === "assignment-review") {
    showCreatedReview(event.state.assignmentId, false);
  } else if (event.state?.screen === "assignment") {
    showAssignmentDetail(event.state.assignmentId, false);
  } else if (event.state?.screen === "profile") {
    loadProfile(false);
  } else if (event.state?.screen === "profile-settings") {
    loadProfile(false);
  } else if (event.state?.screen === "member-profile") {
    showMemberProfile(event.state.memberId, false);
  } else if (event.state?.screen === "moderation") {
    loadModeration(false);
  } else if (event.state?.screen === "moderation-case") {
    showModerationCase(event.state.caseId, false);
  } else if (event.state?.screen === "task-creation") {
    openTaskCreation(true);
  } else if (event.state?.screen === "task-recovery") {
    beginTaskCreationFlow(false);
  } else if (event.state?.screen === "task-preview") {
    openTaskCreation(false, "stale");
  } else {
    void loadCatalog(false);
  }
});
globalThis.addEventListener("hashchange", () => {
  if (!presentationFromLocation()) {
    history.replaceState({ screen: "catalog" }, "", presentationLocationFor("T01"));
    void loadCatalog(false);
  }
});
bootstrap();
