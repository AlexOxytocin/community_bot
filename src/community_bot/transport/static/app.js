import { applyPlatformTheme } from "/mini-assets/platform.js";

applyPlatformTheme();

const content = document.getElementById("content");
const title = document.getElementById("screen-title");
const welcome = document.getElementById("welcome");
const back = document.getElementById("back");
let tasks = [];
let pendingKey = null;
let returnFocusTaskId = null;

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

const newOperationKey = () => {
  const words = new Uint32Array(2);
  crypto.getRandomValues(words);
  const value = ((BigInt(words[0]) << 32n) | BigInt(words[1])) & 0x7fffffffffffffffn;
  return (value || 1n).toString();
};

function renderCatalog() {
  pendingKey = null;
  title.textContent = "Каталог";
  back.classList.add("hidden");
  if (!tasks.length) {
    replaceContent(element("p", "Сейчас нет доступных заданий.", "status muted"));
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
    button.addEventListener("click", () => showDetail(task));
    if (task.id === returnFocusTaskId) focusTarget = button;
    list.append(button);
  }
  replaceContent(list);
  focusTarget?.focus();
  returnFocusTaskId = null;
}

function showDetail(task) {
  returnFocusTaskId = task.id;
  title.textContent = "Карточка задания";
  back.classList.remove("hidden");
  history.pushState({ taskId: task.id }, "", "#task");
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
    renderCatalog();
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

back.addEventListener("click", () => history.back());
globalThis.addEventListener("popstate", renderCatalog);
bootstrap();
