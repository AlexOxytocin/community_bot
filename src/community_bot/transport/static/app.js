import { applyPlatformTheme } from "/mini-assets/platform.js";

applyPlatformTheme();

const content = document.getElementById("content");
const title = document.getElementById("screen-title");
const welcome = document.getElementById("welcome");
const back = document.getElementById("back");
const catalogNav = document.getElementById("catalog-nav");
const assignmentsNav = document.getElementById("assignments-nav");
const moderationNav = document.getElementById("moderation-nav");
let tasks = [];
let assignments = [];
let pendingKey = null;
let returnFocusTaskId = null;
let returnFocusAssignmentId = null;
let returnFocusModeration = false;
let screenRevision = 0;

const element = (tag, text, className) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
};

const replaceContent = (...nodes) => content.replaceChildren(...nodes);

const section = (heading, value) => {
  const node = element("section", undefined, "section");
  node.append(element("h3", heading), element("p", value, "muted"));
  return node;
};

const setNavigation = (screen) => {
  catalogNav.setAttribute("aria-pressed", String(screen === "catalog"));
  assignmentsNav.setAttribute("aria-pressed", String(screen === "assignments"));
  moderationNav.setAttribute("aria-pressed", String(screen === "moderation"));
};

const restoreModerationFocus = () => {
  if (returnFocusModeration) moderationNav.focus();
  returnFocusModeration = false;
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

const newOperationKey = () => {
  const words = new Uint32Array(2);
  crypto.getRandomValues(words);
  const value = ((BigInt(words[0]) << 32n) | BigInt(words[1])) & 0x7fffffffffffffffn;
  return (value || 1n).toString();
};

function renderCatalog() {
  screenRevision += 1;
  pendingKey = null;
  setNavigation("catalog");
  title.textContent = "Каталог";
  back.classList.add("hidden");
  if (!tasks.length) {
    replaceContent(element("p", "Сейчас нет доступных заданий.", "status muted"));
    restoreModerationFocus();
    return;
  }
  const list = element("div", undefined, "list");
  let focusTarget = null;
  for (const task of tasks) {
    const button = element("button", undefined, "card");
    button.type = "button";
    button.append(
      element("h3", task.title),
      element("p", task.description, "muted"),
      element(
        "p",
        String(task.credit_reward_per_performer)
          + " кредитов · уровень "
          + String(task.minimum_level),
        "meta",
      ),
    );
    button.addEventListener("click", () => showTaskDetail(task));
    if (task.id === returnFocusTaskId) focusTarget = button;
    list.append(button);
  }
  replaceContent(list);
  focusTarget?.focus();
  returnFocusTaskId = null;
  restoreModerationFocus();
}

function showTaskDetail(task, push = true) {
  screenRevision += 1;
  returnFocusTaskId = task.id;
  setNavigation("");
  title.textContent = "Карточка задания";
  back.classList.remove("hidden");
  if (push) history.pushState({ screen: "task", taskId: task.id }, "", "#task");
  const detail = element("article", undefined, "card detail");
  detail.append(element("h3", task.title), section("Описание", task.description));
  detail.append(section("Критерии выполнения", task.completion_criteria));
  detail.append(section("Как выполнять", task.performer_instructions));
  for (const [key, value] of Object.entries(task.public_input)) {
    detail.append(section(key, String(value)));
  }
  for (const value of Object.values(task.materials)) {
    detail.append(section("Материал", value));
  }
  const status = element("p", "", "status hidden");
  status.setAttribute("aria-live", "polite");
  const accept = element("button", "Принять задание", "primary");
  accept.type = "button";
  accept.addEventListener("click", () => acceptTask(task, accept, status));
  detail.append(status, accept);
  replaceContent(detail);
  back.focus();
}

async function acceptTask(task, button, status) {
  button.disabled = true;
  status.className = "status";
  status.textContent = "Принимаем задание…";
  pendingKey ||= newOperationKey();
  try {
    const response = await fetch(
      "/api/v1/tasks/" + task.id + "/assignments",
      {
        method: "POST",
        headers: { "Idempotency-Key": pendingKey },
        credentials: "same-origin",
      },
    );
    const payload = await response.json();
    if (!response.ok) {
      pendingKey = null;
      throw new Error(payload.code || "request_failed");
    }
    status.className = "status success";
    status.textContent = "Задание принято. Можно переходить к выполнению.";
    button.remove();
  } catch (error) {
    status.textContent = error instanceof TypeError
      ? "Сеть недоступна. Повторите попытку — запрос останется тем же."
      : "Задание сейчас недоступно. Вернитесь в каталог и попробуйте другое.";
    button.disabled = false;
  }
}

function renderAssignments(revision = ++screenRevision) {
  if (revision !== screenRevision) return;
  setNavigation("assignments");
  title.textContent = "Взятые мной";
  back.classList.add("hidden");
  if (!assignments.length) {
    replaceContent(element("p", "Активных назначений пока нет.", "status muted"));
    restoreModerationFocus();
    return;
  }
  const intro = element("p", "Активные назначения", "muted");
  const list = element("ul", undefined, "list");
  let focusTarget = null;
  for (const assignment of assignments) {
    const button = element("button", undefined, "card");
    button.type = "button";
    const deadline = element("p", "Срок: ", "meta");
    deadline.append(time(assignment.task_deadline_at));
    button.append(
      element("h3", assignment.task_title),
      element("p", assignmentStatus(assignment.assignment_status), "muted"),
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
  replaceContent(intro, list);
  focusTarget?.focus();
  returnFocusAssignmentId = null;
  restoreModerationFocus();
}

async function loadAssignments(push = true) {
  const revision = ++screenRevision;
  if (push) history.pushState({ screen: "assignments" }, "", "#assignments");
  setNavigation("assignments");
  title.textContent = "Взятые мной";
  back.classList.add("hidden");
  replaceContent(element("p", "Загружаем активные назначения…", "status muted"));
  try {
    const response = await fetch(
      "/api/v1/assignments?status=active&limit=20",
      { credentials: "same-origin" },
    );
    if (!response.ok) throw new Error(requestError(response));
    if (revision !== screenRevision) return;
    assignments = (await response.json()).items;
    if (revision !== screenRevision) return;
    renderAssignments(revision);
  } catch (error) {
    if (revision !== screenRevision) return;
    const retry = element("button", "Повторить", "primary");
    retry.type = "button";
    retry.addEventListener("click", () => loadAssignments(false));
    replaceContent(...assignmentError(error.message, retry));
  }
}

async function showAssignmentDetail(assignmentId, push = true) {
  const revision = ++screenRevision;
  returnFocusAssignmentId = assignmentId;
  if (push) {
    history.pushState(
      { screen: "assignment", assignmentId },
      "",
      "#assignment/" + assignmentId,
    );
  }
  setNavigation("");
  title.textContent = "Активное назначение";
  back.classList.remove("hidden");
  replaceContent(element("p", "Загружаем назначение…", "status muted"));
  try {
    const response = await fetch(
      "/api/v1/assignments/" + assignmentId,
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
    replaceContent(detail);
    back.focus();
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

async function loadModeration(push = true) {
  const revision = ++screenRevision;
  returnFocusModeration = true;
  if (push) history.pushState({ screen: "moderation" }, "", "#moderation");
  setNavigation("moderation");
  title.textContent = "Очередь модерации";
  back.classList.remove("hidden");
  replaceContent(element("p", "Загружаем открытые кейсы…", "status muted"));
  back.focus();
  try {
    const response = await fetch(
      "/api/v1/moderation/cases?limit=20",
      { credentials: "same-origin" },
    );
    if (!response.ok) throw new Error(requestError(response));
    const cases = (await response.json()).items;
    if (revision !== screenRevision) return;
    if (!cases.length) {
      replaceContent(element("p", "Открытых кейсов нет.", "status muted"));
      return;
    }
    const list = element("ul", undefined, "list");
    for (const item of cases) {
      const card = element("article", undefined, "card");
      const opened = element("p", "Открыт: ", "meta");
      opened.append(time(item.opened_at));
      card.append(
        element("h3", moderationCaseType(item.case_type)),
        element("p", moderationStatus(item.status), "muted"),
        opened,
      );
      if (item.current_code) {
        card.append(element("p", "Текущее решение: " + item.current_code, "meta"));
      }
      const row = element("li");
      row.append(card);
      list.append(row);
    }
    replaceContent(list);
  } catch (error) {
    if (revision !== screenRevision) return;
    const retry = element("button", "Повторить", "primary");
    retry.type = "button";
    retry.addEventListener("click", () => loadModeration(false));
    replaceContent(...moderationError(error.message, retry));
  }
}

async function bootstrap() {
  try {
    const [me, catalog] = await Promise.all([
      fetch("/api/v1/me", { credentials: "same-origin" }),
      fetch("/api/v1/tasks", { credentials: "same-origin" }),
    ]);
    if (!me.ok || !catalog.ok) throw new Error("bootstrap_failed");
    const [profile, page] = await Promise.all([me.json(), catalog.json()]);
    welcome.textContent = profile.display_name
      + ", выберите понятное задание и помогите сообществу.";
    tasks = page.items;
    const initialScreen = location.hash;
    history.replaceState({ screen: "catalog" }, "", "#catalog");
    renderCatalog();
    if (initialScreen === "#moderation") loadModeration();
  } catch {
    replaceContent(
      element(
        "p",
        "Не удалось загрузить каталог. Откройте Mini App ещё раз.",
        "status",
      ),
    );
  }
}

catalogNav.addEventListener("click", () => {
  history.pushState({ screen: "catalog" }, "", "#catalog");
  renderCatalog();
});
assignmentsNav.addEventListener("click", () => loadAssignments());
moderationNav.addEventListener("click", () => loadModeration());
back.addEventListener("click", () => history.back());
globalThis.addEventListener("popstate", (event) => {
  if (event.state?.screen === "task") {
    const task = tasks.find((item) => item.id === event.state.taskId);
    if (task) showTaskDetail(task, false);
  } else if (event.state?.screen === "assignments") {
    renderAssignments();
  } else if (event.state?.screen === "assignment") {
    showAssignmentDetail(event.state.assignmentId, false);
  } else if (event.state?.screen === "moderation") {
    loadModeration(false);
  } else {
    renderCatalog();
  }
});
bootstrap();
