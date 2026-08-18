import { applyPlatformTheme } from "/mini-assets/platform.js";

applyPlatformTheme();

const content = document.getElementById("content");
const title = document.getElementById("screen-title");
const welcome = document.getElementById("welcome");
const back = document.getElementById("back");
const catalogNav = document.getElementById("catalog-nav");
const profileNav = document.getElementById("profile-nav");
const assignmentsNav = document.getElementById("assignments-nav");
const moderationNav = document.getElementById("moderation-nav");
let tasks = [];
let assignments = [];
let pendingKey = null;
let returnFocusTaskId = null;
let returnFocusAssignmentId = null;
let returnFocusModeration = false;
let returnFocusProfile = false;
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
  profileNav.setAttribute("aria-pressed", String(screen === "profile"));
  assignmentsNav.setAttribute("aria-pressed", String(screen === "assignments"));
  moderationNav.setAttribute("aria-pressed", String(screen === "moderation"));
};

const restoreModerationFocus = () => {
  if (returnFocusModeration) moderationNav.focus();
  returnFocusModeration = false;
};

const restoreProfileFocus = () => {
  if (returnFocusProfile) profileNav.focus();
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

const getJson = async (path) => {
  const response = await fetch(path, { credentials: "same-origin" });
  if (!response.ok) throw new Error(requestError(response));
  return response.json();
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
  const create = element("button", "Создать задание", "primary");
  create.type = "button";
  create.addEventListener("click", () => openTaskCreation(true));
  if (!tasks.length) {
    replaceContent(create, element("p", "Сейчас нет доступных заданий.", "status muted"));
    restoreModerationFocus();
    restoreProfileFocus();
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
  replaceContent(create, list);
  focusTarget?.focus();
  returnFocusTaskId = null;
  restoreModerationFocus();
  restoreProfileFocus();
}

async function taskCreationCommand(body) {
  const response = await fetch("/api/v1/task-creation", {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": newOperationKey() },
    credentials: "same-origin",
    body: JSON.stringify(body),
  });
  return submissionResponse(response);
}

function renderTaskCreation(state) {
  const draft = state.draft;
  if (!draft) return replaceContent(element("p", "Черновик недоступен.", "status"));
  if (state.preview && !state.needs_edit) {
    const card = element("article", undefined, "card detail");
    card.append(element("h3", state.preview.title), section("Описание", state.preview.description));
    card.append(section("Критерии", state.preview.completion_criteria));
    card.append(section("Резерв", String(state.preview.reward_total) + " кредитов"));
    const publish = element("button", "Опубликовать", "primary");
    publish.type = "button";
    publish.addEventListener("click", async () => {
      publish.disabled = true;
      try {
        const result = await taskCreationCommand({ action: "publish", draft_id: draft.id, expected_revision: draft.revision });
        history.replaceState({ screen: "catalog" }, "", "#catalog");
        const home = element("button", "В каталог", "primary");
        home.addEventListener("click", renderCatalog);
        replaceContent(element("p", "Задание опубликовано: " + result.task_id, "status success"), home);
      } catch { publish.disabled = false; }
    });
    card.append(publish);
    return replaceContent(card);
  }
  const values = draft.values;
  const form = element("form", undefined, "task-form");
  form.innerHTML = '<label class="section">Тип<select name="task_kind"><option value="solo">Личное</option><option value="group">Групповое</option></select></label><label class="section">Категория<select name="category_id"></select></label><label class="section">Размер<select name="time_size"></select></label><label class="section">Награда<input name="credit_reward_per_performer" type="number" min="1" required></label><label class="section">Формат<select name="format"><option value="online">Онлайн</option><option value="offline">Офлайн</option></select></label><label class="section">Название<input name="title" required></label><label class="section">Описание<textarea name="description" required></textarea></label><label class="section">Критерии выполнения<textarea name="completion_criteria" required></textarea></label><label class="section">Срок<input name="deadline_at" type="datetime-local" required></label><label class="section">Число исполнителей<input name="performer_slots" type="number" min="1" required></label><label class="section">Город для офлайн-задания<input name="city"></label><label class="section">Материалы<textarea name="material_text"></textarea></label><label class="section">Ссылка<input name="material_url" type="url"></label>';
  for (const item of state.categories) form.category_id.append(new Option(item.icon + " " + item.name, item.id));
  for (const item of state.time_sizes) form.time_size.append(new Option(item.value.toUpperCase() + " · " + item.label, item.value));
  for (const name of ["task_kind", "category_id", "time_size", "format"]) if (values[name]) form[name].value = values[name];
  for (const name of ["title", "description", "completion_criteria", "city"]) form[name].value = values[name] || "";
  form.credit_reward_per_performer.value = values.credit_reward_per_performer || "";
  form.deadline_at.value = values.deadline_at?.slice(0, 16) || "";
  form.performer_slots.value = values.performer_slots || 1;
  form.material_text.value = values.materials?.text || "";
  form.material_url.value = values.materials?.url || "";
  const submit = element("button", "Предпросмотр", "primary");
  submit.type = "submit";
  form.append(submit);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    const value = Object.fromEntries(new FormData(form));
    const materials = Object.fromEntries([["text", value.material_text], ["url", value.material_url]].filter(([, item]) => item));
    try {
      await taskCreationCommand({ action: "save", draft_id: draft.id, expected_revision: draft.revision, form: { ...value, credit_reward_per_performer: Number(value.credit_reward_per_performer), performer_slots: Number(value.performer_slots), deadline_at: new Date(value.deadline_at).toISOString(), materials } });
      await openTaskCreation(false, false);
    } catch { submit.disabled = false; }
  });
  replaceContent(state.needs_edit ? element("p", "Предпросмотр устарел. Обновите данные.", "status") : form, form);
}

async function openTaskCreation(start, push = true) {
  if (push) history.pushState({ screen: "task-creation" }, "", "#task-creation");
  setNavigation("");
  title.textContent = "Создать задание";
  back.classList.remove("hidden");
  replaceContent(element("p", "Загружаем черновик…", "status muted"));
  try {
    if (start) await taskCreationCommand({ action: "start" });
    renderTaskCreation(await getJson("/api/v1/task-creation"));
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

function profileDetails(me, member) {
  const card = element("article", undefined, "card detail");
  const fields = [
    ["Город", me.city],
    ["Часовой пояс", me.timezone],
    ["О себе", me.short_bio],
    ["Текущая цель", me.current_goal],
    ["Категории помощи", me.help_categories],
    ["Навыки", me.skill_tags],
    ["Доступность", me.availability],
    ["Баланс", me.credit_balance],
    ["Опыт", me.experience_total],
    ["Уровень", me.level && me.level.display_name
      ? String(me.level.number) + " · " + me.level.display_name
      : null],
    ["Карма", member.karma
      ? String(member.karma.score) + " · оценок: " + String(member.karma.count)
      : null],
    ["Надёжность", member.reliability ? reliabilityText(member.reliability.rate) : null],
    ["Принято заданий", member.reliability && member.reliability.accepted],
    ["Подтверждённый вес", member.reliability && member.reliability.approved_weight],
    ["Неявки", member.reliability && member.reliability.no_show],
  ];
  card.append(element("h3", me.display_name));
  for (const [heading, value] of fields) {
    const item = valueSection(heading, value);
    if (item) card.append(item);
  }
  return card;
}

function leaderboardDetails(items) {
  const boundary = element("section", undefined, "profile-boundary");
  boundary.append(element("h3", "Таблица вклада"));
  if (!items.length) {
    boundary.append(element("p", "Таблица вклада пока пуста.", "status muted"));
    return boundary;
  }
  const list = element("ol", undefined, "list leaderboard");
  for (const item of items) {
    const row = element("li", undefined, "card");
    row.append(
      element("h4", String(item.rank) + ". " + item.display_name),
      element("p", "Опыт: " + String(item.experience), "meta"),
      element("p", "Получатели помощи: " + String(item.unique_recipients), "meta"),
      element("p", "Надёжность: " + reliabilityText(item.reliability), "meta"),
      element("p", "Неявки: " + String(item.no_show), "meta"),
    );
    list.append(row);
  }
  boundary.append(list);
  return boundary;
}

function renderProfile(state, revision) {
  if (revision !== screenRevision) return;
  const profileBoundary = state.profile
    ? profileDetails(state.profile.me, state.profile.member)
    : state.profileError
      ? boundaryError("Мои показатели", "Не удалось загрузить профиль.", state.profileRetry)
      : element("p", "Загружаем профиль…", "status muted");
  const leaderboardBoundary = state.leaderboard
    ? leaderboardDetails(state.leaderboard)
    : state.leaderboardError
      ? boundaryError(
        "Таблица вклада",
        "Не удалось загрузить таблицу вклада.",
        state.leaderboardRetry,
      )
      : element("p", "Загружаем таблицу вклада…", "status muted");
  replaceContent(profileBoundary, leaderboardBoundary);
}

async function loadOwnProfile(state, revision) {
  state.profile = null;
  state.profileError = false;
  renderProfile(state, revision);
  try {
    const me = await getJson("/api/v1/me");
    if (revision !== screenRevision) return;
    const member = await getJson("/api/v1/members/" + encodeURIComponent(me.member_id));
    if (revision !== screenRevision) return;
    state.profile = { me, member };
  } catch {
    if (revision !== screenRevision) return;
    state.profileError = true;
  }
  renderProfile(state, revision);
}

async function loadLeaderboard(state, revision) {
  state.leaderboard = null;
  state.leaderboardError = false;
  renderProfile(state, revision);
  try {
    const page = await getJson("/api/v1/leaderboard?limit=30");
    if (revision !== screenRevision) return;
    state.leaderboard = page.items;
  } catch {
    if (revision !== screenRevision) return;
    state.leaderboardError = true;
  }
  renderProfile(state, revision);
}

function loadProfile(push = true) {
  const revision = ++screenRevision;
  const state = { profile: null, leaderboard: null, profileError: false, leaderboardError: false };
  state.profileRetry = element("button", "Повторить профиль", "primary");
  state.profileRetry.type = "button";
  state.profileRetry.addEventListener("click", () => loadOwnProfile(state, revision));
  state.leaderboardRetry = element("button", "Повторить таблицу", "primary");
  state.leaderboardRetry.type = "button";
  state.leaderboardRetry.addEventListener("click", () => loadLeaderboard(state, revision));
  returnFocusProfile = true;
  if (push) history.pushState({ screen: "profile" }, "", "#profile");
  setNavigation("profile");
  title.textContent = "Профиль";
  back.classList.remove("hidden");
  renderProfile(state, revision);
  back.focus();
  void loadOwnProfile(state, revision);
  void loadLeaderboard(state, revision);
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

const submissionMessage = (error) => error instanceof TypeError
  ? "Сеть недоступна. Повторите запрос — он останется тем же."
  : "Не удалось сохранить результат. Проверьте назначение и повторите.";

const retryableSubmissionError = (error) => error instanceof TypeError || error?.status >= 500;

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
  const response = await fetch(path, {
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

function renderSubmission(assignment, draft) {
  const submissionRevision = screenRevision;
  const boundary = element("section", undefined, "submission");
  boundary.append(element("h3", "Отправить результат"));
  const status = element("p", "", "status hidden");
  status.setAttribute("aria-live", "polite");

  if (!draft) {
    const begin = element("button", "Начать отправку", "primary");
    begin.type = "button";
    let beginKey = null;
    begin.addEventListener("click", async () => {
      begin.disabled = true;
      status.className = "status";
      status.textContent = "Открываем черновик…";
      beginKey ||= newOperationKey();
      try {
        const response = await fetch(
          "/api/v1/assignments/" + encodeURIComponent(assignment.id) + "/submission-drafts",
          {
            method: "POST",
            headers: { "Idempotency-Key": beginKey },
            credentials: "same-origin",
          },
        );
        const payload = await submissionResponse(response);
        const next = renderSubmission(assignment, payload);
        boundary.replaceWith(next);
        next.querySelector("textarea")?.focus();
      } catch (error) {
        status.textContent = submissionMessage(error);
        if (!retryableSubmissionError(error)) beginKey = null;
        begin.disabled = false;
      }
    });
    boundary.append(status, begin);
    return boundary;
  }

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
    const previewCard = element("section", undefined, "section submission-preview");
    previewCard.append(
      element("h4", "Предпросмотр"),
      element("p", typeof saved.result === "string" ? saved.result : ""),
    );
    const confirm = element("button", "Подтвердить отправку", "primary");
    confirm.type = "button";
    confirm.addEventListener("click", async () => {
      confirm.disabled = true;
      status.className = "status";
      status.textContent = "Отправляем результат…";
      confirmKey ||= newOperationKey();
      try {
        await submissionRequest(
          "/api/v1/submission-drafts/" + encodeURIComponent(saved.id) + "/confirm",
          "POST",
          confirmKey,
          { expected_revision: saved.revision },
        );
        if (submissionRevision === screenRevision) {
          await showAssignmentDetail(assignment.id, false);
        }
      } catch (error) {
        status.textContent = submissionMessage(error);
        if (!retryableSubmissionError(error)) confirmKey = null;
        confirm.disabled = false;
      }
    });
    previewCard.append(confirm);
    form.querySelector(".submission-preview")?.remove();
    form.append(previewCard);
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
  if (draft.result !== null) addPreview(draft);
  return boundary;
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
    if (assignment.assignment_status === "accepted"
      && assignment.submission_contract === "freeform_result_v1") {
      detail.append(renderSubmission(assignment, null));
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

async function bootstrap(authAttempted = false) {
  try {
    const me = await fetch("/api/v1/me", { credentials: "same-origin" });
    if (me.status === 401 && !authAttempted) {
      const initData = globalThis.Telegram?.WebApp?.initData;
      if (!initData) throw new Error("telegram_init_data_missing");
      const auth = await fetch("/api/v1/auth/telegram", {
        method: "POST",
        headers: { "Content-Type": "text/plain; charset=utf-8" },
        body: initData,
        credentials: "same-origin",
      });
      if (!auth.ok) throw new Error("telegram_auth_failed");
      return bootstrap(true);
    }
    const catalog = await fetch("/api/v1/tasks", { credentials: "same-origin" });
    if (!me.ok || !catalog.ok) throw new Error("bootstrap_failed");
    const [profile, page] = await Promise.all([me.json(), catalog.json()]);
    welcome.textContent = profile.display_name
      + ", выберите понятное задание и помогите сообществу.";
    tasks = page.items;
    const initialScreen = location.hash;
    history.replaceState({ screen: "catalog" }, "", "#catalog");
    renderCatalog();
    if (initialScreen === "#profile") loadProfile();
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
profileNav.addEventListener("click", () => loadProfile());
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
  } else if (event.state?.screen === "profile") {
    loadProfile(false);
  } else if (event.state?.screen === "moderation") {
    loadModeration(false);
  } else if (event.state?.screen === "task-creation") {
    openTaskCreation(false, false);
  } else {
    renderCatalog();
  }
});
bootstrap();
