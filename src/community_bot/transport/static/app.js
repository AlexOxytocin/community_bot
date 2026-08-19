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
let returnFocusReviewId = null;
let returnFocusModeration = false;
let returnFocusModerationCaseId = null;
let returnFocusProfile = false;
let screenRevision = 0;
let currentMemberId = null;

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

const createdAssignmentsButton = element("button", "Созданные мной");
createdAssignmentsButton.type = "button";
createdAssignmentsButton.addEventListener("click", () => loadCreatedReviews());

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

function profileEditor(me, state, revision) {
  const form = element("form", undefined, "task-form");
  const fieldLabel = element("label", "Поле профиля");
  const field = element("select");
  for (const [value, label] of editableProfileFields) {
    const option = element("option", label);
    option.value = value;
    field.append(option);
  }
  fieldLabel.append(field);
  const valueLabel = element("label", "Новое значение");
  const input = element("textarea");
  const profileValue = (name) => Array.isArray(me[name])
    ? me[name].join(", ")
    : (me[name] ?? "");
  const draft = state.profileEdit ||= {
    field: field.value,
    value: profileValue(field.value),
    operationKey: null,
    message: "",
  };
  field.value = draft.field;
  input.value = draft.value;
  valueLabel.append(input);
  const save = element("button", "Сохранить поле", "primary");
  save.type = "submit";
  const status = element("p", draft.message, draft.message ? "status" : "status hidden");
  status.setAttribute("aria-live", "polite");
  field.addEventListener("change", () => {
    draft.field = field.value;
    draft.value = profileValue(field.value);
    draft.operationKey = null;
    draft.message = "";
    input.value = draft.value;
  });
  input.addEventListener("input", () => {
    draft.value = input.value;
    draft.operationKey = null;
    draft.message = "";
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    save.disabled = true;
    status.className = "status";
    status.textContent = "Сохраняем профиль…";
    draft.message = status.textContent;
    draft.operationKey ||= newOperationKey();
    try {
      const updated = await submissionRequest(
        "/api/v1/me/profile",
        "PUT",
        draft.operationKey,
        { field: draft.field, value: draft.value },
      );
      if (revision !== screenRevision) return;
      state.profile = { me: updated, member: state.profile.member };
      state.profileEdit = null;
      renderProfile(state, revision);
      try {
        const member = await getJson(
          "/api/v1/members/" + encodeURIComponent(updated.member_id),
        );
        if (revision !== screenRevision) return;
        state.profile = { me: updated, member };
        renderProfile(state, revision);
      } catch {
        // The authoritative profile mutation already succeeded; keep its response.
      }
    } catch (error) {
      if (revision !== screenRevision) return;
      if (!retryableSubmissionError(error)) draft.operationKey = null;
      draft.message = error?.status === 422
        ? "Проверьте значение поля."
        : error?.status === 409
          ? "Запрос изменился. Повторите сохранение."
          : "Не удалось сохранить. Повторите попытку — запрос останется тем же.";
      status.textContent = draft.message;
      save.disabled = false;
    }
  });
  form.append(fieldLabel, valueLabel, status, save);
  return form;
}

function profileDetails(me, member, state, revision) {
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
  card.append(profileEditor(me, state, revision));
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
    const row = element("li");
    const button = element("button", undefined, "card");
    button.type = "button";
    button.append(
      element("h4", String(item.rank) + ". " + item.display_name),
      element("p", "Опыт: " + String(item.experience), "meta"),
      element("p", "Получатели помощи: " + String(item.unique_recipients), "meta"),
      element("p", "Надёжность: " + reliabilityText(item.reliability), "meta"),
      element("p", "Неявки: " + String(item.no_show), "meta"),
    );
    button.addEventListener("click", () => showMemberProfile(item.member_id));
    row.append(button);
    list.append(row);
  }
  boundary.append(list);
  return boundary;
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
          renderMemberProfile(state, revision);
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
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    value.disabled = true;
    comment.disabled = true;
    status.className = "status";
    status.textContent = "Сохраняем оценку…";
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
      renderMemberProfile(state, revision);
    } catch (error) {
      if (revision !== screenRevision) return;
      if (!retryableSubmissionError(error)) resetPendingAction();
      status.textContent = error?.status === 422
        ? "Комментарий должен содержать от 10 до 300 символов."
        : error?.status === 409
          ? "Черновик изменился. Повторите сохранение."
          : "Оценка недоступна или не удалось сохранить. Повторите попытку.";
      submit.disabled = false;
      value.disabled = false;
      comment.disabled = false;
    }
  });
  form.append(valueLabel, commentLabel, status, submit);
  return form;
}

function renderMemberProfile(state, revision) {
  if (revision !== screenRevision) return;
  if (state.error) {
    return replaceContent(element("p", "Профиль участника недоступен.", "status"));
  }
  if (!state.member) {
    return replaceContent(element("p", "Загружаем профиль…", "status muted"));
  }
  const nodes = [safeMemberDetails(state.member)];
  if (state.message) nodes.push(element("p", state.message, "status success"));
  if (state.member.member_id !== currentMemberId) nodes.push(karmaForm(state, revision));
  replaceContent(...nodes);
}

async function showMemberProfile(memberId, push = true) {
  const revision = ++screenRevision;
  const state = { member: null, error: false, karma: null, message: "" };
  if (push) history.pushState({ screen: "member-profile", memberId }, "", "#member-profile");
  setNavigation("profile");
  title.textContent = "Профиль участника";
  back.classList.remove("hidden");
  renderMemberProfile(state, revision);
  back.focus();
  try {
    state.member = await getJson("/api/v1/members/" + encodeURIComponent(memberId));
  } catch {
    state.error = true;
  }
  renderMemberProfile(state, revision);
}

function renderProfile(state, revision) {
  if (revision !== screenRevision) return;
  const profileBoundary = state.profile
    ? profileDetails(state.profile.me, state.profile.member, state, revision)
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
    replaceContent(
      createdAssignmentsButton,
      element("p", "Активных назначений пока нет.", "status muted"),
    );
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
  replaceContent(createdAssignmentsButton, intro, list);
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

const decisionLabels = {
  full: "Принять полностью",
  partial: "Принять частично",
  reject: "Отклонить",
};

async function loadCreatedReviews(push = true) {
  const revision = ++screenRevision;
  if (push) history.pushState({ screen: "created-assignments" }, "", "#created-assignments");
  setNavigation("assignments");
  title.textContent = "Созданные мной";
  back.classList.add("hidden");
  replaceContent(element("p", "Загружаем результаты…", "status muted"));
  try {
    const reviews = (await getJson("/api/v1/assignment-reviews")).items;
    if (revision !== screenRevision) return;
    if (!reviews.length) {
      replaceContent(element("p", "Результатов, ожидающих решения, пока нет.", "status muted"));
      return;
    }
    const list = element("ul", undefined, "list");
    for (const review of reviews) {
      const button = element("button", undefined, "card");
      button.type = "button";
      button.append(
        element("h3", review.task_title),
        element("p", "Исполнитель: " + review.performer_display_name, "muted"),
        element("p", review.result, "muted"),
      );
      button.addEventListener("click", () => showCreatedReview(review.id));
      if (review.id === returnFocusReviewId) queueMicrotask(() => button.focus());
      const item = element("li");
      item.append(button);
      list.append(item);
    }
    returnFocusReviewId = null;
    replaceContent(list);
  } catch (error) {
    if (revision !== screenRevision) return;
    const retry = element("button", "Повторить", "primary");
    retry.type = "button";
    retry.addEventListener("click", () => loadCreatedReviews(false));
    replaceContent(...assignmentError(error.message, retry));
  }
}

async function showCreatedReview(assignmentId, push = true) {
  const revision = ++screenRevision;
  returnFocusReviewId = assignmentId;
  if (push) history.pushState({ screen: "assignment-review", assignmentId }, "", "#assignment-review/" + assignmentId);
  setNavigation("");
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
    for (const decision of review.available_decisions) {
      const button = element("button", decisionLabels[decision], "primary");
      button.type = "button";
      let operationKey = null;
      button.addEventListener("click", async () => {
        if (decision === "reject" && !globalThis.confirm(
          "Отклонить результат? Выплата и резерв останутся заморожены на 24 часа для возможного спора. Повторная отправка результата не откроется.",
        )) return;
        button.disabled = true;
        status.className = "status";
        status.textContent = "Сохраняем решение…";
        operationKey ||= newOperationKey();
        try {
          await submissionRequest(
            "/api/v1/assignment-reviews/" + encodeURIComponent(assignmentId) + "/decision",
            "POST",
            operationKey,
            { decision },
          );
          history.replaceState({ screen: "created-assignments" }, "", "#created-assignments");
          await loadCreatedReviews(false);
        } catch (error) {
          status.textContent = "Не удалось сохранить решение. Повторите запрос — ключ останется тем же.";
          if (!retryableSubmissionError(error)) operationKey = null;
          button.disabled = false;
        }
      });
      detail.append(button);
    }
    detail.append(status);
    replaceContent(detail);
    back.focus();
  } catch (error) {
    if (revision === screenRevision) replaceContent(...assignmentError(error.message));
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

function renderDispute(assignment) {
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
  const status = element("p", "", "status hidden");
  status.setAttribute("aria-live", "polite");
  let operationKey = null;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const normalized = comment.value.trim();
    if (!normalized || !globalThis.confirm(
      "Подать спор? Комментарий увидит только команда модерации.",
    )) return;
    submit.disabled = true;
    status.className = "status";
    status.textContent = "Подаём спор…";
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
      status.textContent = error instanceof TypeError
        ? "Сеть недоступна. Повторите запрос — он останется тем же."
        : "Не удалось подать спор. Проверьте комментарий и состояние назначения.";
      if (!retryableSubmissionError(error)) operationKey = null;
      submit.disabled = false;
    }
  });
  form.append(label, submit, status);
  return form;
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
    if (assignment.reject_dispute_deadline_at) {
      detail.append(dateSection("Подать спор до", assignment.reject_dispute_deadline_at));
    }
    if (assignment.case_status) {
      detail.append(section("Спор", "Передан команде модерации"));
    } else if (assignment.assignment_status === "rejected_pending_dispute") {
      detail.append(section(
        "Условия спора",
        assignment.can_dispute
          ? "Опишите причину до указанного срока. Комментарий увидит только команда модерации."
          : "Срок подачи спора истёк.",
      ));
    }
    if (assignment.can_dispute) detail.append(renderDispute(assignment));
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
    let focusTarget = null;
    for (const item of cases) {
      const actionable = item.case_type === "dispute" && item.status === "open";
      const card = element(actionable ? "button" : "article", undefined, "card");
      if (actionable) card.type = "button";
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
      if (actionable) {
        card.addEventListener("click", () => showModerationCase(item.id));
        if (item.id === returnFocusModerationCaseId) focusTarget = card;
      }
      const row = element("li");
      row.append(card);
      list.append(row);
    }
    replaceContent(list);
    focusTarget?.focus();
    returnFocusModerationCaseId = null;
  } catch (error) {
    if (revision !== screenRevision) return;
    const retry = element("button", "Повторить", "primary");
    retry.type = "button";
    retry.addEventListener("click", () => loadModeration(false));
    replaceContent(...moderationError(error.message, retry));
  }
}

async function showModerationCase(caseId, push = true) {
  const revision = ++screenRevision;
  returnFocusModerationCaseId = caseId;
  if (push) {
    history.pushState(
      { screen: "moderation-case", caseId },
      "",
      "#moderation-case/" + caseId,
    );
  }
  setNavigation("moderation");
  title.textContent = "Решение по спору";
  back.classList.remove("hidden");
  replaceContent(element("p", "Загружаем спор…", "status muted"));
  back.focus();
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
    form.append(label, reasonLabel, review, status);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const normalizedReason = reason.value.trim();
      if (!normalizedReason) {
        reason.focus();
        return;
      }
      select.disabled = true;
      reason.disabled = true;
      review.remove();
      const confirmation = section(
        "Подтверждение",
        (resolutionLabels[select.value] || select.value) + ". " + normalizedReason,
      );
      const edit = element("button", "Изменить");
      edit.type = "button";
      const confirm = element("button", "Подтвердить решение", "primary");
      confirm.type = "button";
      let operationKey = null;
      edit.addEventListener("click", () => {
        confirmation.remove();
        edit.remove();
        confirm.remove();
        select.disabled = false;
        reason.disabled = false;
        status.className = "status hidden";
        form.insertBefore(review, status);
        reason.focus();
      });
      confirm.addEventListener("click", async () => {
        edit.disabled = true;
        confirm.disabled = true;
        status.className = "status";
        status.textContent = "Применяем решение…";
        operationKey ||= newOperationKey();
        try {
          await submissionRequest(
            "/api/v1/moderation/cases/" + encodeURIComponent(caseId) + "/resolution",
            "POST",
            operationKey,
            {
              expected_revision: dispute.revision,
              code: select.value,
              reason: normalizedReason,
            },
          );
          history.back();
        } catch (error) {
          status.textContent = error?.status === 409
            ? "Кейс уже изменился или больше недоступен. Вернитесь в очередь."
            : "Не удалось применить решение. Повторите запрос — ключ останется тем же.";
          if (!retryableSubmissionError(error)) operationKey = null;
          edit.disabled = false;
          confirm.disabled = false;
          confirm.focus();
        }
      });
      form.insertBefore(confirmation, status);
      form.insertBefore(edit, status);
      form.insertBefore(confirm, status);
      confirm.focus();
    });
    detail.append(form);
    replaceContent(detail);
    select.focus();
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
    currentMemberId = profile.member_id;
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
  } else if (event.state?.screen === "created-assignments") {
    loadCreatedReviews(false);
  } else if (event.state?.screen === "assignment-review") {
    showCreatedReview(event.state.assignmentId, false);
  } else if (event.state?.screen === "assignment") {
    showAssignmentDetail(event.state.assignmentId, false);
  } else if (event.state?.screen === "profile") {
    loadProfile(false);
  } else if (event.state?.screen === "member-profile") {
    showMemberProfile(event.state.memberId, false);
  } else if (event.state?.screen === "moderation") {
    loadModeration(false);
  } else if (event.state?.screen === "moderation-case") {
    showModerationCase(event.state.caseId, false);
  } else if (event.state?.screen === "task-creation") {
    openTaskCreation(false, false);
  } else {
    renderCatalog();
  }
});
bootstrap();
