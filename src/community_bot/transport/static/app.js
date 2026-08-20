import { applyPlatformTheme } from "/mini-assets/platform.js";

applyPlatformTheme();

const content = document.getElementById("content");
const title = document.getElementById("screen-title");
const welcome = document.getElementById("welcome");
const back = document.getElementById("back");
const shell = document.getElementById("app");
const catalogNav = document.getElementById("catalog-nav");
const profileNav = document.getElementById("profile-nav");
const assignmentsNav = document.getElementById("assignments-nav");
const participantsNav = document.getElementById("participants-nav");
const moderationNav = document.getElementById("moderation-nav");
const managementNav = document.getElementById("management-nav");
let tasks = [];
let assignments = [];
const pendingAcceptKeys = new Map();
let pendingTaskCreation = null;
let returnFocusTaskId = null;
let returnFocusAssignmentId = null;
let returnFocusReviewId = null;
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

const replaceContent = (...nodes) => content.replaceChildren(...nodes);

const screenStateSets = [
  "loading§content§error§permission_closed",
  "loading§content§error§permission_closed§validation§confirm§disabled_reason",
  "loading§content§error§permission_closed§disabled_reason",
  "loading§content§error§permission_closed§empty",
  "loading§content§error§permission_closed§validation§confirm",
  "loading§content§error§permission_closed§confirm",
  "loading§content§error§permission_closed§empty§disabled_reason",
  "loading§content§error§permission_closed§success",
  "loading§content§error§permission_closed§confirm§disabled_reason",
].map((states) => states.split("§"));

const presentationInventory = `
A01\tLaunch / bootstrap\t\tloading§offline§auth error\t0
A02\tНедоступная сессия\tПовторить\texpired§revoked§unsupported§error\t0
A03\tПриглашение\tПродолжить\tinvalid§expired§exhausted§revoked\t1
A04\tПравила и consent\tПринять правила\tdisabled§loading§error\t2
A05\tАнкета регистрации\tПродолжить\t8 profile fields§autosave§validation\t1
A05A\tPreview и отправка заявки\tОтправить заявку\tchanged§loading§error§success\t2
A06\tОжидает одобрения\tОбновить статус\tpending§loading§error\t2
A06A\tЗаявка отклонена\tИсправить и отправить\treview comment§reopened§success\t2
A07\tОграниченный доступ\tРазрешённое действие\tstatus§blocked actions§expiry\t0
T01\tКаталог заданий\tСоздать задание\tfilters§cursor§TEST marker§empty\t3
T02\tФильтры каталога\tПрименить\tcategory§format§deadline§reward§level\t4
T03\tПолная карточка задания\tПринять\tsnapshot fields§open§full§expired§unavailable\t0
T03A\tПодтверждение обязательства\tПринять слот\tdeadline§criteria§withdrawal consequences§limits\t5
T04\tSolo / group\tПродолжить\tsolo=1§group≥2\t4
T04A\tВыбор шаблона\tИспользовать / Без шаблона\tapproved§inactive§empty§error\t6
T04B\tЧерновики заданий\tПродолжить черновик\tcurrent§saved§stale revision§cancel\t3
T05\tРедактор задания\tПроверить\tall engine fields§schema§autosave§balance\t4
T06\tPreview задания\tОпубликовать\timmutable snapshot§reserve§role variant\t0
T07\tConfirm публикации\tОпубликовать\texact revision§loading§conflict§error\t5
T08\tОпубликовано\tОткрыть задание\tsuccess§exact replay\t7
M01\tМои задания\tКонтекст карточки\ttaken§created§recent§archive\t3
M02\tВзятые мной\tОткрыть назначение\tactive§submitted§dispute§terminal§cursor\t3
M03\tНазначение\tПродолжить\tall task fields§exact state§deadlines\t0
M04\tРедактор результата\tПроверить\tsaved result schema / freeform result§autosave\t4
M04A\tВерсии результата\tОткрыть версию\timmutable versions§current§empty\t6
M05\tPreview результата\tОтправить\tschema labels§criteria§changed revision\t0
M06\tConfirm отправки\tОтправить\texact revision§loading§deadline race§error\t5
M07\tРезультат отправлен\tК заданию\tversion N§review deadline§exact replay\t7
M08\tОтказ исполнителя\tПодтвердить отказ\treason§timing§reliability consequence\t4
M09\tСозданные мной\tОткрыть задание\tdraft§recruiting§closed§settling§terminal\t3
M10\tСозданное задание / слоты\tКонтекст слота\tfree§accepted§submitted§terminal§cancellations\t0
M11\tПроверка результата\tВыбрать решение\tlatest/all versions§criteria§72h§conflict\t0
M12\tРешение по результату\tПроверить решение\tfull§half-ceil partial§reject; no invented comment\t4
M13\tРешение сохранено\tК заданию\tledger outcome§dispute window§exact replay\t7
M14\tОткрытие спора\tОтправить спор\t24h§обязательный comment\t4
M14A\tМатериалы спора\t\tappend-only evidence history§visibility\t3
M15\tСтатус спора\tРазрешённое действие\topen§resolved§appealed§frozen settlement\t0
M16\tАпелляция\tПодать апелляцию\tодна§7 дней§reason§conflict-safe\t1
M17\tЗакрытие набора / отмена автора\tПодтвердить\tfree-slot refund§occupied performers§deadline\t1
M18\tОтвет на запрос отмены\tСогласиться / Продолжить\tpending§obsolete§accepted§declined\t1
M19\tСтатус отмены задания\tК заданию\tresponses§closed intake§cancelled§obsolete\t2
P01\tУчастники\tОткрыть карточку\tactive-only§name/@username ≥3§cursor\t3
P02\tКарточка участника\tОценить карму\tsafe profile fields§aggregate§eligibility\t0
P03\tОценка кармы\tСохранить\t+1§0§−1§comment 10–300§edit\t4
P04\tКарма сохранена\tК профилю\taggregate§exact replay\t7
P05\tЛидерборд\tОткрыть карточку\tall-time XP§tie-breaks§own rank§cursor\t3
P06\tСобственный профиль\tИзменить профиль\tprofile§balance§XP/level§karma§statistics\t0
P07\tРедактор профиля\tСохранить\t8 editable fields§dirty§validation§success\t4
P08\tБаланс\tИстория операций\tcredit§experience§level progress\t0
P09\tИстория операций\tОткрыть операцию\t10 ledger types§cursor§empty§error\t6
P10\tОперация\tОткрыть связанный объект\tdelta§source§reversal link§unavailable target\t2
S01\tОчередь кейсов\tОткрыть кейс\tdispute§appeal§fraud admin-only§filters\t3
S02\tКейс модерации\tК preview решения\ttask snapshot§versions§evidence§history\t0
S03\tPreview решения\tПодтвердить решение\t7 outcome codes§reason§effect preview§stale revision\t4
S04\tРешение сохранено\tК очереди\tledger/reliability/audit outcome§exact replay\t7
S05\tОчередь регистраций\tОткрыть заявку\tsubmitted§empty§error\t6
S06\tЗаявка участника\tВыбрать решение\tall profile fields§consent§prior comment\t2
S07\tРешение по регистрации\tПодтвердить\tapprove§reject§comment§single grant\t1
S08\tНовая санкция\tПроверить\tnotice§warning§restriction§suspension§ban\t1
S09\tАктивные санкции\tОткрыть санкцию\tactive§expiring§role visibility§empty\t6
S10\tСанкция и история\tОтозвать, если разрешено\tactions§reason§period§issue/revoke/expire\t2
S11\tОплаченные выполнения\tОткрыть выполнение\tpaid§reversible§filters§empty\t6
S12\tОткрытие fraud-case\tПодтвердить открытие\treason§evidence reference§reversal precheck\t1
G01\tHub управления\tОткрыть capability\tpermission-shaped tiles§loading§error\t6
G02\tПриглашения\tСоздать приглашение\tactive§exhausted§expired§revoked\t6
G03\tНовое приглашение\tСоздать\tintended Telegram ID§uses§expiry§validation\t1
G04\tПриглашение / использования\tОтозвать\tcreator§uses§redemptions§confirm\t2
G05\tУправление участниками\tОткрыть участника\tstatus§role§permission filters§non-active privacy\t6
G06\tАдмин-карточка участника\tРазрешённое действие\tprofile§role§status§restrictions§histories\t2
G07\tСтатус / роль\tПодтвердить\tactive↔paused§member↔moderator§admin super-only\t1
G08\tКатегории / шаблоны\tОткрыть объект\tversioned§active/inactive§empty§error\t6
G08A\tКатегория\tВключить / выключить\tmetadata read-only§active/inactive§exact toggle\t2
G08B\tШаблон и версии\tСоздать версию\tall template fields§schemas§active history\t2
G09\tРедактор версии шаблона\tПроверить версию\tinput/result JSON Schema§limits§validation\t1
G10\tВсе задания / выполнения\tОткрыть объект\torigin§status§deadline§filters§cursor\t6
G11\tКорректировка ledger\tПроверить операцию\tcredit/experience delta§reason§comment\t1
G12\tConfirm корректировки / reversal\tПрименить\tsource link§totals§exact replay§insufficient balance\t8
G13\tRaw-карма\tОткрыть vote\tauthor§value§comment§audited read§filters\t6
G14\tVote и история версий\tРазрешённая модерация\trevisions§actor§audit§permission\t2
G14C\tExclude / restore версии кармы\tПодтвердить\texact revision§reason§no auto-sanction\t1
G14A\tИстория надёжности\tОткрыть source\troot§responsibility chain§outcome corrections\t2
G14B\tLedger участника\tПроверить корректировку\tall types§reversal links§cursor\t6
G15\tЖурнал действий\tОткрыть запись\tactor§action§entity§reason§pagination\t6
G15A\tЗапись аудита\tОткрыть разрешённый объект\tbefore/after safe projection§immutable\t2
G16\tВерсии конфигурации\tЗагрузить версию\tactive§candidates§history§hashes\t6
G16A\tВерсия конфигурации\tАктивировать / сравнить\tlevels§alert policy§assignment limit§hash\t2
G17\tЗагрузка и проверка config\tПроверить\tschema/version/hash§duplicate/conflict§valid/invalid\t1
G18\tАктивация конфигурации\tАктивировать\texact version/hash§reason§backfill outcome\t8
G19\tЗадание сообщества\tПроверить карточку\tall snapshot fields§slots§reward 1–4§independent reviewer\t1
G20\tPreview задания сообщества\tОпубликовать / На подтверждение\trole variant§conflict checks§exact revision\t2
G21\tОчередь публикаций\tОткрыть карточку\tpending§empty§permission\t6
G22\tПодтверждение публикации\tПодтвердить / Отклонить\treason§exact revision§success\t2
G22A\tОчередь community review\tОткрыть результат\tempty§conflict-closed§reviewer-required\t6
G22B\tCommunity result review\tВыбрать решение\tcriteria§versions§72h§issued reward\t2
G22C\tЗамена проверяющего\tПодтвердить замену\tindependence§generation§new 72h window\t1
G22D\tОтмена community assignment\tПодтвердить\tcommunity/system reason§audit§appealable\t1
G23\tInteraction alerts\tОткрыть алерт\tprivate pair§count/window/config§empty\t6
G23A\tRisk signals\tОткрыть сигнал\treview-only§no automatic effects§privacy\t6
G24\tInteraction alert\tСохранить итог\tassignments§private notes§legitimate/monitor/penalty\t2
G25\tШтраф по алерту\tПодтвердить пакет\tone/both§unreserved balance§atomic§exact once\t1
G26\tАдминистраторы\tИзменить роль\tsuper permission boundary§self-disabled\t6
G27\tАпелляции\tОткрыть апелляцию\tone/7d§empty§permission\t6
G28\tРешение по апелляции\tПодтвердить новый outcome\texact reversals§corrections§paid slot occupied\t2
`.trim().split("\n").map((record) => {
  const [id, label, primary, fields, stateSet] = record.split("\t");
  return {
    id,
    family: id[0],
    label,
    primary,
    fields: fields.split("§"),
    states: screenStateSets[Number(stateSet)],
  };
});

const productRoutePatterns = [
  "#/start",
  "#/catalog",
  "#/tasks/:task_id",
  "#/compose/tasks/:draft_id?",
  "#/work",
  "#/work/:resource_id",
  "#/members",
  "#/members/:member_id",
  "#/profile",
  "#/moderation/:case_id?",
  "#/admin/:resource_type?/:resource_id?",
];
const presentationStates = [...new Set(presentationInventory.flatMap((screen) => screen.states))];
const presentationScreen = (id) => presentationInventory.find((screen) => screen.id === id);
const disabledPresentationIds = new Set(
  "A03 A04 A05 A05A A06A M16 M17 M18 S07 S08 S10 S12 G03 G04 G07 G08A G09 G11 G12 G14C G17 G18 G19 G20 G22 G22B G22C G22D G24 G25 G26 G28".split(" "),
);
const connectedPresentationIds = new Set(
  "T03A T07 M04 M06 M08 M12 M14 P03 P07 S03".split(" "),
);
const rootPresentationIds = new Set("T01 M01 P01 P06 S01 G01".split(" "));
const dialogPresentationIds = new Set("T03A T07 M06 G12 G18".split(" "));
const successPresentationIds = new Set("T08 M07 M13 P04 S04".split(" "));
const navigationClassFor = (id) => rootPresentationIds.has(id)
  ? "root"
  : dialogPresentationIds.has(id)
    ? "dialog"
    : successPresentationIds.has(id) ? "success" : "context";
const localFallbackOverrides = {
  "PE-004": "A02", "PE-009": "A02", "PE-019": "T04A", "PE-023": "M09",
  "PE-031": "M03", "PE-035": "M02", "PE-041": "M09", "PE-042": "M02",
  "PE-043": "M03", "PE-045": "M14", "PE-054": "M09", "PE-055": "M02",
  "PE-060": "P01", "PE-069": "A02", "PE-077": "S01", "PE-078": "S01",
  "PE-094": "G06", "PE-108": "G16A",
};
const localTransitions = `
PE-001 A01 A02 auth_failure replace error
PE-002 A01 A03 valid_invitation replace content
PE-003 A01 A07 restricted_status replace permission_closed
PE-004 A01 T01 active_member replace loading
PE-009 A06 T01 registration_approved replace loading
PE-010 A06 A06A registration_rejected replace content
PE-012 T01 T02 open_filters push content
PE-013 T01 T03 open_task push loading
PE-014 T01 T04 create_task push content
PE-015 T03 T03A accept_task push confirm
PE-016 T04 T04A choose_template_path push content
PE-017 T04 T04B resume_draft_path push content
PE-018 T04A T05 use_template_or_freeform push content
PE-019 T04B T05 resume_draft push content
PE-020 T05 T06 preview_task push content
PE-021 T06 T07 publish_task push confirm
PE-023 T08 M10 open_published_task replace loading
PE-025 M01 M02 open_accepted_tab stay content
PE-026 M01 M09 open_created_tab stay content
PE-027 M02 M03 open_assignment push loading
PE-028 M03 M04 create_or_extend_submission push content
PE-029 M03 M08 withdraw_assignment push content
PE-031 M04A M04 continue_submission pop content
PE-032 M04 M05 preview_result push content
PE-033 M05 M06 submit_result push confirm
PE-035 M07 M03 open_assignment replace loading
PE-037 M09 M10 open_created_task push loading
PE-038 M10 M11 open_review push loading
PE-039 M11 M12 choose_review_decision push content
PE-041 M13 M10 open_created_task replace loading
PE-042 M13 M03 open_assignment replace loading
PE-043 M13 M14 open_reject_dispute push content
PE-045 M14A M15 open_dispute_status replace loading
PE-046 M15 M16 open_appeal push content
PE-048 G27 G28 open_appeal push loading
PE-051 M10 M17 request_group_cancellation push content
PE-054 M19 M10 open_created_task_outcome replace loading
PE-055 M19 M03 open_assignment_outcome replace loading
PE-056 P01 P02 open_member push loading
PE-057 P01 P05 open_leaderboard stay loading
PE-058 P02 P03 rate_karma push content
PE-060 P04 P02 return_to_member replace loading
PE-061 P06 P07 edit_profile push content
PE-062 P06 P08 open_balance push content
PE-064 P08 P09 open_ledger push loading
PE-065 P09 P10 open_operation push loading
PE-066 S01 S02 open_case push loading
PE-067 S02 S03 preview_resolution push content
PE-069 S04 S01 return_to_case_queue replace loading
PE-070 S01 S05 open_registration_queue stay loading
PE-071 S05 S06 open_application push loading
PE-072 S06 S07 choose_registration_decision push content
PE-074 S01 S11 open_paid_assignments stay loading
PE-075 S11 S12 open_fraud_case push content
PE-077 G06 S08 issue_sanction push content
PE-078 S02 S08 issue_case_sanction push content
PE-081 S09 S10 open_sanction push loading
PE-082 G01 G02 open_invitations push loading
PE-083 G02 G03 create_invitation push content
PE-084 G02 G04 open_invitation push loading
PE-085 G01 G05 open_member_admin push loading
PE-086 G05 G06 open_admin_member push loading
PE-087 G06 G07 change_role_or_status push content
PE-088 G01 G08 open_catalog_admin push loading
PE-089 G08 G08A open_category push loading
PE-090 G08 G08B open_template push loading
PE-091 G08B G09 create_template_version push content
PE-092 G01 G10 open_all_tasks push loading
PE-093 G06 G11 correct_member_ledger push content
PE-094 G14B G11 correct_ledger push content
PE-095 G11 G12 preview_ledger_change push confirm
PE-097 G01 G13 open_raw_karma push loading
PE-098 G13 G14 open_karma_vote push loading
PE-099 G14 G14C moderate_karma_version push content
PE-100 G06 G14A open_reliability_history push loading
PE-101 G06 G14B open_member_ledger push loading
PE-102 G01 G15 open_audit push loading
PE-103 G15 G15A open_audit_record push loading
PE-104 G01 G16 open_config_versions push loading
PE-105 G16 G16A open_config_version push loading
PE-106 G16 G17 upload_config push content
PE-107 G16A G18 activate_config push confirm
PE-108 G17 G18 activate_validated_config push confirm
PE-109 G01 G19 create_community_task push content
PE-110 G19 G20 preview_community_task push content
PE-113 G21 G22 open_publication_request push loading
PE-115 G01 G22A open_community_reviews push loading
PE-116 G22A G22B open_community_result push loading
PE-121 G01 G23 open_interaction_alerts push loading
PE-122 G01 G23A open_risk_signals push loading
PE-123 G23 G24 open_interaction_alert push loading
PE-127 G01 G26 open_administrators push loading
PE-128 G01 G27 open_appeals push loading
`.trim().split("\n").map((row) => {
  const [id, source, target, trigger, historyMode, state] = row.split(" ");
  return {
    id, source, target, trigger, historyMode, state,
    fallback: localFallbackOverrides[id] || source,
  };
});
const transitionsFrom = (id) => localTransitions.filter((edge) => edge.source === id);
const productRouteFor = (id) => {
  if (id.startsWith("A")) return "#/start";
  if (["T01", "T02"].includes(id)) return "#/catalog";
  if (["T03", "T03A"].includes(id)) return "#/tasks/:task_id";
  if (id.startsWith("T")) return "#/compose/tasks/:draft_id?";
  if (["M01", "M02", "M09"].includes(id)) return "#/work";
  if (id.startsWith("M")) return "#/work/:resource_id";
  if (["P01", "P05"].includes(id)) return "#/members";
  if (["P02", "P03", "P04"].includes(id)) return "#/members/:member_id";
  if (id.startsWith("P")) return "#/profile";
  if (id.startsWith("S")) return "#/moderation/:case_id?";
  return "#/admin/:resource_type?/:resource_id?";
};
const resourceRoute = (pattern, resourceId, resourceType) => {
  const required = pattern.match(/:\w+(?!\?)/g) || [];
  if (required.length && !resourceId) return null;
  const values = [resourceType, resourceId].filter(Boolean).map(encodeURIComponent);
  let index = 0;
  return pattern
    .replace(/\/:(\w+)\?/g, () => values[index] ? `/${values[index++]}` : "")
    .replace(/:(\w+)/g, () => values[index++] || "");
};

const presentationLocationFor = (id, resourceId, resourceType) => {
  const pattern = productRouteFor(id);
  const route = resourceRoute(pattern, resourceId, resourceType);
  return route ? `${route}?view_state=${id.toLowerCase()}` : null;
};
const templateIds = {
  list: new Set("T01 T04A T04B M01 M02 M04A M09 M14A P01 P05 S01 S05 S09 S11 G02 G05 G08 G10 G13 G16 G21 G22A G23 G23A G26 G27".split(" ")),
  editor: new Set("A03 A05 T02 T04 T05 M04 M08 M12 M14 M16 M17 M18 P03 P07 S03 S07 S08 S12 G03 G07 G09 G11 G14C G17 G19 G22C G22D G25".split(" ")),
  preview: new Set("A05A T06 M05 G20".split(" ")),
  confirm: new Set("T03A T07 M06 G12 G18".split(" ")),
  outcome: new Set("A01 A02 A06 A06A A07 T08 M07 M13 P04 S04".split(" ")),
  history: new Set("P09 S10 G14 G14A G14B G15".split(" ")),
  hub: new Set(["G01"]),
};
const presentationTemplate = (id) => Object.entries(templateIds)
  .find(([, ids]) => ids.has(id))?.[0] || "detail";

const presentationState = (screen, requestedState) => {
  const defaultState = disabledPresentationIds.has(screen.id) ? "disabled_reason" : "content";
  return presentationStates.includes(requestedState) ? requestedState : defaultState;
};

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
  shell.classList.toggle("context-screen", context);
  catalogNav.setAttribute("aria-pressed", String(screen === "catalog"));
  profileNav.setAttribute("aria-pressed", String(screen === "profile"));
  assignmentsNav.setAttribute("aria-pressed", String(screen === "assignments"));
  participantsNav.setAttribute("aria-pressed", String(screen === "participants"));
  moderationNav.setAttribute("aria-pressed", String(screen === "moderation"));
  managementNav.setAttribute("aria-pressed", String(screen === "management"));
};

const presentationContent = `
A01\tЗапуск сообщества\tзапуск Mini App\t\tСессия|Проверяем вход через Telegram§Продолжение|Откроется только разрешённый раздел
A02\tСессия недоступна\tсессию\tПовторить вход\tПричина|Ссылка устарела или доступ был отозван§Что делать|Откройте Mini App из актуального сообщения Telegram
A03\tПроверка приглашения\tприглашение\tПродолжить\tПолучатель|Приглашение предназначено вашему Telegram-профилю§Срок действия|Использовать до 24 августа, 20:00
A04\tПравила сообщества\tправила сообщества\tПринять правила\tОбязательство|Уважать участников и не публиковать приватные данные§Согласие|Версия правил сохранится вместе с заявкой
A05\tАнкета участника\tанкету участника\tПродолжить\tПрофиль|Имя, город, часовой пояс и короткое описание§Помощь|Цель, категории, навыки и доступность
A05A\tПроверка анкеты\tпредпросмотр анкеты\tОтправить заявку\tЛичные данные|Показаны только поля будущего профиля§После отправки|Заявка перейдёт команде сообщества
A06\tЗаявка на рассмотрении\tстатус заявки\tОбновить статус\tСостояние|Команда сообщества ещё рассматривает анкету§После решения|Доступный раздел появится при обновлении
A06A\tЗаявку нужно исправить\tзамечания к заявке\tИсправить анкету\tКомментарий команды|Уточните, чем вы готовы помогать§Повторная отправка|Сохранённые поля можно отредактировать
A07\tОграниченный доступ\tограничения аккаунта\tОткрыть разрешённый раздел\tСтатус|Часть действий временно недоступна§Доступные действия|Собственный профиль и разрешённые разделы
T01\tКаталог\tкаталог заданий\tСоздать задание\tПроверить доступность пандуса у библиотеки|Открыто · Помощь сообществу|4 кредита · до 20:00§Вычитать памятку для новых участников|Открыто · Онлайн|3 кредита · 2 места§Собрать контакты районных волонтёров|Открыто · 30 минут|4 кредита · до завтра
T02\tФильтры каталога\tфильтры каталога\tПрименить фильтры\tКатегория|Помощь сообществу§Условия|Онлайн · до завтра · награда от 3 кредитов
T03\tУсловия задания\tкарточку задания\tПринять задание\tСоздатель|Новая библиотека§Награда и места|4 кредита · 2 из 3 мест свободно§Что нужно сделать|Сделайте три фотографии главного входа и пандуса§Критерии приёмки|Вход виден полностью, комментарий называет препятствия§Формат и место|Офлайн · Buenos Aires · Центральная библиотека§Срок и доступ|20 августа, 20:00 · уровень 1
T03A\tПодтверждение участия\tусловия принятия\tПринять слот\tОбязательство|Завершить работу до 20 августа, 20:00§Отказ|Слот освободится, причина повлияет на надёжность
T04\tТип задания\tтип нового задания\tПродолжить\tЛичное|Один исполнитель и один результат§Групповое|Несколько независимых слотов
T04A\tОснова задания\tшаблоны заданий\tВыбрать основу\tГотовый шаблон|Поля и критерии уже настроены§Без шаблона|Заполнить разрешённые поля вручную
T04B\tЧерновики заданий\tчерновики заданий\tПродолжить черновик\tПандус у библиотеки|Сохранено сегодня в 14:20§Помощь на мероприятии|Нужно обновить срок
T05\tНовое задание\tредактор задания\tПроверить задание\tТип задания|Групповое§Число исполнителей|3§Формат|Офлайн§Город|Buenos Aires§Категория|Помощь сообществу§Название|Проверить доступность пандуса§Что нужно сделать|Сделать 3 фотографии входа и описать препятствия§Критерии приёмки|На каждой фотографии полностью виден вход§Награда|4 кредита§Срок|20 августа, 20:00
T06\tПредпросмотр задания\tпредпросмотр задания\tПерейти к публикации\tЗадание|Проверить доступность пандуса§Исполнители|3 места · по 4 кредита§Проверка|Фотографии входа, описание препятствий и точный адрес§Резерв|12 кредитов после подтверждения
T07\tПубликация задания\tподтверждение публикации\tОпубликовать\tБудет опубликовано|Групповое задание на 3 исполнителей§Списание|12 кредитов будут зарезервированы§После публикации|Условия принятых слотов останутся неизменными
T08\tЗадание опубликовано\tрезультат публикации\tОткрыть задание\tРезультат|Задание появилось в каталоге§Резерв|12 кредитов · операция сохранена
M01\tМои задания\tсписок моих заданий\tОткрыть карточку\tПроверить доступность пандуса|В работе · осталось 2 часа|Черновик результата сохранён§Вычитать памятку для участников|На проверке|Отправлено сегодня в 14:20§Проверить ссылки в каталоге|Завершено|Начислено 4 кредита
M02\tВзятые мной\tпринятые задания\tОткрыть назначение\tПроверить доступность пандуса|В работе · срок сегодня§Вычитать памятку|Результат на проверке
M03\tАктивное назначение\tназначение\tПродолжить выполнение\tЗадание|Проверить доступность пандуса§Срок|20 августа, 20:00§Критерии|Три фотографии и описание препятствий
M04\tРезультат задания\tчерновик результата\tПроверить результат\tРезультат|Добавлены три фотографии и описание доступности§Сохранение|Черновик сохранён сегодня в 15:10
M04A\tВерсии результата\tверсии результата\tОткрыть версию\tВерсия 2|Текущая · сегодня в 15:10§Версия 1|Сохранена вчера в 19:40
M05\tПредпросмотр результата\tпредпросмотр результата\tПерейти к отправке\tРезультат|Три фотографии входа и описание препятствий§Проверка|Все критерии задания заполнены
M06\tОтправка результата\tподтверждение отправки\tОтправить результат\tВерсия|Будет отправлена версия 2§Последствие|После отправки начнётся срок проверки
M07\tРезультат отправлен\tотправленный результат\tК назначению\tСостояние|Версия 2 передана создателю§Срок проверки|До 23 августа, 15:10
M08\tОтказ от задания\tотказ исполнителя\tПодтвердить отказ\tПричина|Необходимо объяснить, почему работа не завершена§Последствие|Слот освободится, надёжность будет пересчитана
M09\tСозданные мной\tсозданные задания\tОткрыть задание\tПроверить доступность пандуса|Набор открыт · 1 из 3 слотов занят§Вычитать памятку|Результат ожидает проверки
M10\tЗадание и исполнители\tслоты задания\tОткрыть слот\tСвободные места|2 из 3§Мария Крылова|Результат отправлен§Резерв|12 кредитов
M11\tПроверка результата\tрезультат на проверке\tВыбрать решение\tИсполнитель|Мария Крылова§Результат|Три фотографии и описание препятствий§Срок решения|Осталось 48 часов
M12\tРешение по результату\tрешение по результату\tПроверить решение\tПолностью|Начислить 4 кредита§Частично|Начислить 2 кредита§Отклонить|Открыть окно для спора на 24 часа
M13\tРешение сохранено\tитог проверки\tК заданию\tВыплата|Исполнителю начислено 4 кредита§Запись|Решение добавлено в историю задания
M14\tСпор по результату\tформу спора\tОтправить спор\tСрок|Осталось 18 часов§Причина|Создатель не учёл приложенные фотографии
M14A\tМатериалы спора\tисторию спора\t\tКомментарий исполнителя|Сегодня · 12:04|Вход был закрыт, приложена фотография объявления§Версия результата 2|Сегодня · 12:18|Доступно сторонам спора и модератору
M15\tСтатус спора\tстатус спора\tОткрыть доступное действие\tСостояние|Материалы переданы модератору§Расчёт|Выплата и резерв временно заморожены
M16\tАпелляция\tформу апелляции\tПодать апелляцию\tСрок|Подать можно один раз в течение 7 дней§Причина|Объясните, какая часть решения требует пересмотра
M17\tЗакрытие набора\tотмену задания автором\tПодтвердить закрытие\tСвободные слоты|Средства вернутся сразу§Занятые слоты|Исполнители получат запрос на решение
M18\tЗапрос на отмену\tответ исполнителя\tСохранить ответ\tСогласиться|Задание завершится без результата§Продолжить|Работу можно закончить до текущего срока
M19\tСтатус отмены\tсостояние отмены\tК заданию\tНабор|Закрыт для новых исполнителей§Ответы|1 согласие · 1 продолжает работу
P01\tУчастники\tкаталог участников\tОткрыть карточку\tМария Крылова|Уровень 7 · Дизайн · Buenos Aires|Карма +12 · Надёжность 98%§Илья Петров|Уровень 5 · Разработка · онлайн|Карма +7 · Надёжность 94%§Анна Соколова|Уровень 4 · Тексты · Córdoba|Карма +9 · Недостаточно данных
P02\tКарточка участника\tпрофиль участника\tОценить карму\tМария Крылова|Уровень 7 · Значимый вклад§Показатели|+12 кармы · 98% надёжность · 34 задания§О себе|Помогаю с исследованиями и проверкой сценариев§Навыки|Дизайн · Исследования · Тексты§Оценка кармы|Доступна после совместного оплачиваемого задания
P03\tОценка взаимодействия\tоценку кармы\tСохранить оценку\tОценка|+1 · положительно§Комментарий|Мария помогла проверить сценарий и подробно описала результат
P04\tОценка сохранена\tрезультат оценки\tК профилю\tКарма|Новая оценка учтена в общем показателе§Повтор|Та же операция не создаст вторую оценку
P05\tЛидерборд\tлидерборд\tОткрыть карточку\t1 · Мария Крылова|260 XP§2 · Вы|180 XP|Ваше место§3 · Илья Петров|145 XP§4 · Анна Соколова|122 XP§5 · Денис Волков|118 XP
P06\tПрофиль\tсобственный профиль\tИзменить профиль\tAlex Oxytocin|Активный участник · с мая 2026§Личный прогресс|24 кредита · 180 опыта · 96% надёжность§Мои показатели|12 заданий завершено · 4 создано · 9 получателей§Карточка профиля|Карма +8 · Продукт и аналитика · Buenos Aires
P07\tРедактор профиля\tполя профиля\tСохранить профиль\tГород|Buenos Aires§О себе|Помогаю превращать идеи в ясные планы§Доступность|По вечерам
P08\tБаланс и опыт\tбаланс участника\tИстория операций\tКредиты|24 доступно§Опыт|180 · уровень 7§До следующего уровня|20 опыта
P09\tИстория операций\tоперации участника\tОткрыть операцию\tНаграда за задание|+4 кредита · сегодня§Резерв задания|-12 кредитов · вчера
P10\tОперация баланса\tоперацию баланса\tОткрыть связанное задание\tИзменение|+4 кредита§Источник|Подтверждённое выполнение§Связь|Проверить доступность пандуса
S01\tМодерация\tочередь кейсов\tОткрыть кейс\tСпор по результату задания|Обжалование · открыто|Сегодня · 12:40 · #1042§Нарушение условий публикации|Проверка · открыто|Вчера · 18:05 · #1038§Пересмотр решения создателя|Апелляция|18 августа · #1029
S02\tКейс модерации\tматериалы кейса\tПроверить решение\tЗадание|Проверить доступность пандуса§Стороны|Создатель и исполнитель§Материалы|Две версии результата и комментарий спора
S03\tРешение модератора\tпредпросмотр решения\tПодтвердить решение\tИтог|Частичная выплата§Причина|Подтверждена половина результата§Последствия|2 кредита исполнителю · 2 кредита автору
S04\tРешение применено\tитог модерации\tК очереди\tРасчёт|Выплата и возврат записаны§История|Решение доступно сторонам спора
S05\tЗаявки участников\tочередь регистраций\tОткрыть заявку\tМария Крылова|Отправлена сегодня§Илья Петров|Нужна повторная проверка
S06\tЗаявка участника\tанкету участника\tВыбрать решение\tПрофиль|Мария · Buenos Aires · исследователь§Помощь|Дизайн, интервью и тексты§Согласие|Правила приняты 18 августа
S07\tРешение по заявке\tрешение регистрации\tПодтвердить решение\tОдобрить|Открыть участнику основные разделы§Отклонить|Вернуть анкету с одним комментарием
S08\tНовая санкция\tпараметры санкции\tПроверить санкцию\tМера|Временное ограничение§Действия|Создание и принятие заданий§Срок|До 27 августа
S09\tАктивные санкции\tсписок санкций\tОткрыть санкцию\tОграничение заданий|Истекает через 5 дней§Предупреждение|Выдано 12 августа
S10\tСанкция и история\tисторию санкции\tОтозвать санкцию\tПричина|Повторная публикация приватных данных§Период|С 17 по 27 августа§История|Выдана модератором · пока активна
S11\tОплаченные выполнения\tпроверяемые выплаты\tОткрыть выполнение\tПроверка анкеты|4 кредита · выплата доступна для пересмотра§Помощь на встрече|3 кредита · подтверждено
S12\tОткрытие проверки выплаты\tновый кейс выплаты\tПодтвердить открытие\tПричина|Признаки повторного результата§Материал|Ссылка на разрешённое доказательство§Проверка|Выплата допускает обратную операцию
G01\tУправление сообществом\tразделы управления\tОткрыть раздел\tУчастники|Роли, статусы и ограничения§Каталог|Категории и шаблоны§Контроль|Аудит, конфигурация и апелляции
G02\tПриглашения\tсписок приглашений\tСоздать приглашение\tДля Марии|1 использование · до 24 августа§Для команды встречи|3 использования · активно
G03\tНовое приглашение\tпараметры приглашения\tСоздать приглашение\tПолучатель Telegram|123456789§Использований|1§Срок|24 августа, 20:00
G04\tПриглашение\tиспользование приглашения\tОтозвать приглашение\tСоздатель|Администратор сообщества§Использовано|1 из 3§Получатели|Мария Крылова
G05\tУправление участниками\tкаталог участников для администратора\tОткрыть участника\tМария Крылова|Активна · участник§Илья Петров|Пауза · модератор
G06\tУчастник в управлении\tадминистративную карточку участника\tОткрыть доступное действие\tПрофиль|Мария Крылова · активна§Роль|Участник§Ограничения|Нет активных
G07\tРоль и статус\tизменение роли или статуса\tПодтвердить изменение\tТекущее значение|Активный участник§Новое значение|Модератор§Ограничение|Администраторов меняет только главный администратор
G08\tКатегории и шаблоны\tкаталог настроек заданий\tОткрыть объект\tПомощь сообществу|Категория активна§Полевое исследование|Шаблон · версия 3
G08A\tКатегория заданий\tкатегорию заданий\tИзменить доступность\tНазвание|Помощь сообществу§Порядок|2§Создание|Участникам разрешено
G08B\tШаблон задания\tверсии шаблона\tСоздать версию\tТекущая версия|3 · активна§Результат|Текст и фотографии§Ограничение|До 3 исполнителей
G09\tНовая версия шаблона\tредактор шаблона\tПроверить версию\tНазвание|Полевое исследование§Поля задания|Адрес и описание места§Поля результата|Комментарий и фотографии
G10\tВсе задания и выполнения\tобщий журнал заданий\tОткрыть объект\tПандус у библиотеки|Участник · набор открыт§Навигация на встрече|Сообщество · выполнено
G11\tКорректировка баланса\tкорректировку учёта\tПроверить операцию\tПоказатель|Кредиты§Изменение|+2§Причина|Исправление подтверждённой ошибки расчёта
G12\tПодтверждение корректировки\tпоследствия корректировки\tПрименить корректировку\tДо операции|24 кредита§После операции|26 кредитов§Основание|Запись проверки №418
G13\tОценки кармы\tжурнал оценок кармы\tОткрыть оценку\tМария о Денисе|+1 · помощь на задании§Илья об Анне|0 · нейтральная оценка
G14\tОценка и версии\tисторию оценки кармы\tОткрыть модерацию\tТекущая версия|+1 · подтверждена§Предыдущая версия|0 · изменена автором
G14C\tМодерация версии кармы\tизменение видимости оценки\tПодтвердить действие\tВерсия|2 · оценка +1§Причина|Комментарий раскрывает приватные данные§Санкция|Автоматически не создаётся
G14A\tИстория надёжности\tизменения надёжности\tОткрыть источник\tПодтверждённое выполнение|Вес +1 · сегодня§Неявка|Вес -1 · 12 августа
G14B\tОперации участника\tжурнал баланса участника\tПроверить корректировку\tНаграда|+4 кредита · подтверждено§Возврат резерва|+8 кредитов · связан с отменой
G15\tЖурнал действий\tаудит действий\tОткрыть запись\tАдминистратор|Изменил статус участника · сегодня§Модератор|Разрешил спор · вчера
G15A\tЗапись журнала\tдетали аудита\tОткрыть разрешённый объект\tДействие|Статус изменён с паузы на активный§Причина|Запрос участника подтверждён§Неизменность|Запись доступна только для чтения
G16\tВерсии настроек\tверсии конфигурации\tЗагрузить версию\tВерсия 12|Активна · 18 августа§Версия 13|Кандидат · проверка пройдена
G16A\tВерсия настроек\tсодержимое конфигурации\tАктивировать или сравнить\tУровни|8 ступеней опыта§Лимит|3 активных назначения§Алерты|Окно 30 дней · порог 3
G17\tПроверка настроек\tзагруженную конфигурацию\tПроверить файл\tВерсия|13§Схема|Поддерживается§Целостность|Совпадает с загруженным содержимым
G18\tАктивация настроек\tподтверждение активации\tАктивировать версию\tТекущая версия|12§Новая версия|13§Причина|Обновление порога взаимодействий
G19\tЗадание от сообщества\tредактор задания сообщества\tПроверить карточку\tАвтор|Сообщество§Награда|4 кредита на слот§Исполнители|3§Проверяющий|Независимый администратор
G20\tПредпросмотр задания сообщества\tпредпросмотр задания сообщества\tОтправить на публикацию\tКарточка|Полевое исследование доступности§Проверяющий|Мария Крылова§Публикация|Требует подтверждения главного администратора
G21\tОчередь публикаций\tзапросы на публикацию\tОткрыть запрос\tИсследование доступности|Ожидает подтверждения§Помощь на встрече|Возвращено на доработку
G22\tПодтверждение публикации\tрешение о публикации\tСохранить решение\tЗадание|Исследование доступности§Автор|Сообщество§Причина решения|Условия и проверяющий подтверждены
G22A\tПроверки заданий сообщества\tочередь результатов сообщества\tОткрыть результат\tИсследование доступности|Нужен независимый проверяющий§Навигация на встрече|Результат ожидает решения
G22B\tРезультат задания сообщества\tпроверку результата сообщества\tВыбрать решение\tИсполнитель|Мария Крылова§Критерии|Три фотографии и точный адрес§Награда|4 кредита после подтверждения
G22C\tЗамена проверяющего\tнового проверяющего\tПодтвердить замену\tПричина|Текущий проверяющий стал участником задания§Новый проверяющий|Илья Петров§Срок|Новые 72 часа после назначения
G22D\tОтмена задания сообщества\tотмену назначения сообщества\tПодтвердить отмену\tПричина|Место проведения больше недоступно§Расчёт|Средства сообщества не резервировались§Обжалование|Исполнитель увидит разрешённый путь
G23\tАлерты взаимодействий\tсписок алертов\tОткрыть алерт\tМария и Илья|3 совместных задания за 30 дней§Анна и Денис|Порог ещё не достигнут
G23A\tСигналы риска\tсигналы для проверки\tОткрыть сигнал\tПовторяющиеся описания|Требует ручной проверки§Частые отмены|Не меняет доступ автоматически
G24\tАлерт взаимодействия\tпроверку взаимодействия\tСохранить итог\tПара|Мария Крылова и Илья Петров§Совместные задания|3 за 30 дней§Итог|Наблюдать, автоматических последствий нет
G25\tШтраф по алерту\tпакет штрафа\tПодтвердить штраф\tУчастники|Один из двух§Сумма|2 незарезервированных кредита§Применение|Одна атомарная операция
G26\tАдминистраторы\tсписок администраторов\tИзменить роль\tAlex Oxytocin|Главный администратор§Мария Крылова|Администратор§Самоизменение|Недоступно
G27\tАпелляции\tочередь апелляций\tОткрыть апелляцию\tСпор по пандусу|Подана сегодня§Отмена задания|Срок решения через 4 дня
G28\tРешение по апелляции\tпересмотр исхода\tПодтвердить новый итог\tПредыдущее решение|Частичная выплата§Новый итог|Полная выплата§Коррекция|Предыдущие эффекты будут обращены точно
`.trim().split("\n").reduce((result, record) => {
  const [id, titleText, subject, action, fields] = record.split("\t");
  result[id] = { title: titleText, subject, action, fields: fields.split("§") };
  return result;
}, {});

const userFields = (screen) => presentationContent[screen.id]?.fields || null;
const fieldParts = (field) => field.split("|");
const contentFor = (screen) => presentationContent[screen.id];
const actionFor = (screen) => contentFor(screen)?.action || screen.primary;

const appendPresentationAction = (node, screen) => {
  const edges = transitionsFrom(screen.id);
  const actionText = actionFor(screen);
  if ((disabledPresentationIds.has(screen.id) || connectedPresentationIds.has(screen.id)) && actionText) {
    const unavailable = element("button", actionText, "unavailable-action");
    unavailable.type = "button";
    unavailable.disabled = true;
    unavailable.dataset.primaryAction = actionText;
    node.append(unavailable);
  }
  edges.forEach((transition, index) => {
    const target = presentationScreen(transition.target);
    const primary = index === 0 && actionText && !disabledPresentationIds.has(screen.id) && !connectedPresentationIds.has(screen.id);
    const label = primary ? actionText : contentFor(target).title;
    const action = element("button", label, primary ? "primary" : "secondary");
    action.type = "button";
    if (primary) action.dataset.primaryAction = actionText;
    action.dataset.transitionId = transition.id;
    action.dataset.transitionTrigger = transition.trigger;
    action.dataset.transitionFallback = transition.fallback;
    action.addEventListener("click", () => navigatePresentationScreen(
      transition.target,
      transition.state,
      transition.historyMode,
      transition.fallback,
      history.state?.resourceId,
    ));
    node.append(action);
  });
  if (!edges.length && actionText && !disabledPresentationIds.has(screen.id) && !connectedPresentationIds.has(screen.id)) {
    const action = element("button", actionText, "primary");
    action.type = "button";
    action.dataset.primaryAction = actionText;
    action.addEventListener("click", () => renderPresentationScreen(screen.id, "content"));
    node.append(action);
  }
};

const renderListTemplate = (screen, state) => {
  const view = element("section", undefined, "semantic-shell");
  const tabs = element("div", undefined, "segmented");
  const labels = {
    M01: ["Взятые мной · 2", "Созданные · 1"],
    P01: ["Участники", "Лидерборд"],
    P05: ["Участники", "Лидерборд"],
  }[screen.id] || ["Активные", "История"];
  tabs.append(element("button", labels[0]), element("button", labels[1]));
  for (const tab of tabs.children) tab.disabled = true;
  tabs.children[screen.id === "P05" ? 1 : 0].setAttribute("aria-pressed", "true");
  view.append(tabs);
  if (screen.id === "P01") {
    const label = element("label", "Поиск участников");
    const input = element("input");
    input.placeholder = "Имя или @username · от 3 знаков";
    label.append(input);
    view.append(label);
  }
  if (state === "empty") {
    view.append(element("p", "Доступных объектов пока нет.", "status muted"));
  } else {
    const list = element("div", undefined, "list");
    for (const field of userFields(screen)) {
      const [heading, description, meta] = fieldParts(field);
      const card = element("article", undefined, "card");
      card.append(
        element("h3", heading),
        element("p", description, "muted"),
      );
      if (meta) card.append(element("p", meta, "meta"));
      list.append(card);
    }
    view.append(list);
  }
  if (screen.id === "P05") view.append(element("p", "Место считается по опыту за подтверждённые задания. Карма и баланс на место не влияют.", "status muted"));
  appendPresentationAction(view, screen);
  return view;
};

const renderDetailTemplate = (screen) => {
  const card = element("article", undefined, "card detail");
  card.append(element("h3", contentFor(screen).title));
  for (const field of userFields(screen)) {
    const [heading, value] = fieldParts(field);
    card.append(section(heading, value));
  }
  appendPresentationAction(card, screen);
  return card;
};

const renderEditorTemplate = (screen) => {
  const form = element("form", undefined, "task-form card");
  const fields = userFields(screen);
  for (const [index, field] of fields.entries()) {
    const [heading, value] = fieldParts(field);
    const label = element("label", heading);
    const control = index === fields.length - 1 ? element("textarea") : element("input");
    control.value = value;
    label.append(control);
    form.append(label);
  }
  appendPresentationAction(form, screen);
  return form;
};

const renderPreviewTemplate = (screen) => {
  const card = element("article", undefined, "card detail preview-grid");
  card.append(element("p", "Предпросмотр", "badge"), element("h3", contentFor(screen).title));
  for (const field of userFields(screen)) {
    const [heading, value] = fieldParts(field);
    card.append(section(heading, value));
  }
  appendPresentationAction(card, screen);
  return card;
};

const renderConfirmTemplate = (screen) => {
  const card = element("article", undefined, "card detail route-accent");
  card.append(
    element("p", "Подтверждение", "badge"),
    element("h3", contentFor(screen).title),
  );
  for (const field of userFields(screen)) {
    const [heading, value] = fieldParts(field);
    card.append(section(heading, value));
  }
  appendPresentationAction(card, screen);
  return card;
};

const renderOutcomeTemplate = (screen) => {
  const card = element("article", undefined, "card detail outcome-view");
  card.append(
    element("p", "Статус", "badge"),
    element("h3", contentFor(screen).title),
    element("p", fieldParts(userFields(screen)[0])[1], "muted"),
  );
  for (const field of userFields(screen).slice(1)) card.append(element("p", fieldParts(field)[1], "meta"));
  appendPresentationAction(card, screen);
  return card;
};

const renderHistoryTemplate = (screen) => {
  const view = element("section", undefined, "semantic-shell");
  view.append(element("p", "История", "badge"));
  const historyList = element("ol", undefined, "history-list");
  for (const field of userFields(screen)) {
    const [headingText, description, meta] = fieldParts(field);
    const item = element("li");
    item.append(element("strong", headingText), element("span", description, "muted"));
    if (meta) item.append(element("span", meta, "meta"));
    historyList.append(item);
  }
  view.append(historyList);
  appendPresentationAction(view, screen);
  return view;
};

const renderHubTemplate = (screen) => {
  const hub = element("section", undefined, "hub-grid");
  for (const field of userFields(screen)) {
    const [heading, value] = fieldParts(field);
    const tile = element("article", undefined, "card");
    tile.append(element("h3", heading), element("p", value, "muted"));
    hub.append(tile);
  }
  appendPresentationAction(hub, screen);
  return hub;
};

const presentationRenderers = {
  list: renderListTemplate,
  detail: renderDetailTemplate,
  editor: renderEditorTemplate,
  preview: renderPreviewTemplate,
  confirm: renderConfirmTemplate,
  outcome: renderOutcomeTemplate,
  history: renderHistoryTemplate,
  hub: renderHubTemplate,
};

function renderPresentationScreen(id, requestedState) {
  const screen = presentationScreen(id);
  const screenContent = screen && contentFor(screen);
  const state = screen ? presentationState(screen, requestedState) : "permission_closed";
  const rootNavigation = {
    T01: "catalog",
    M01: "assignments",
    P01: "participants",
    P06: "profile",
    S01: "moderation",
    G01: "management",
  }[id] || "";
  const isRoot = navigationClassFor(id) === "root";
  setNavigation(rootNavigation, !isRoot);
  back.classList.toggle("hidden", isRoot);
  title.textContent = screenContent?.title || "Экран недоступен";
  if (!screen || !screenContent) {
    const notice = element("section", undefined, "state-view");
    notice.dataset.state = "permission_closed";
    notice.append(
      element("h3", "Запрошенный раздел недоступен"),
      element("p", "Откройте один из разрешённых разделов навигации.", "status muted"),
    );
    replaceContent(notice);
    return false;
  }
  const template = presentationTemplate(id);
  const boundary = element("section", undefined, "state-view");
  boundary.dataset.screenId = id;
  boundary.dataset.template = template;
  boundary.dataset.state = state;
  boundary.dataset.primary = actionFor(screen);
  boundary.dataset.systemStates = JSON.stringify(screen.states);
  boundary.dataset.visualContract = JSON.stringify(screen.fields);
  if (state === "loading") {
    boundary.append(element("p", `Проверяем ${screenContent.subject} и актуальное состояние.`, "status muted"));
    boundary.append(element("span", undefined, "skeleton"), element("span", undefined, "skeleton"));
  } else if (state !== "content") {
    const copy = {
      empty: `Для раздела «${screenContent.title}» пока нет доступных записей.`,
      error: `Не удалось обновить ${screenContent.subject}. Повторите запрос позже.`,
      permission_closed: `Доступ к разделу «${screenContent.title}» не подтверждён.`,
      disabled_reason: `Действие «${actionFor(screen)}» пока не подключено к серверу.`,
      validation: `Проверьте поля раздела «${screenContent.title}».`,
      confirm: `Проверьте последствия действия «${actionFor(screen)}».`,
      success: `Итог для раздела «${screenContent.title}» появится после ответа сервера.`,
    }[state] || `Состояние раздела «${screenContent.title}» недоступно.`;
    const notice = element("p", copy, "status muted");
    if (state === "disabled_reason") notice.id = "connection-reason";
    boundary.append(notice);
  }
  boundary.append(presentationRenderers[template](screen, state));
  replaceContent(boundary);
  title.tabIndex = -1;
  title.focus();
}

function navigatePresentationScreen(
  id,
  requestedState = "content",
  historyMode = "push",
  fallbackId = "T01",
  resourceId = history.state?.resourceId,
) {
  const screen = presentationScreen(id);
  if (!screen) {
    const fallback = presentationScreen(fallbackId);
    if (fallback) {
      const fallbackState = "permission_closed";
      const fallbackLocation = presentationLocationFor(fallback.id, resourceId);
      if (!fallbackLocation) {
        return navigatePresentationScreen("T01", fallbackState, "replace", "T01", null);
      }
      history.replaceState({
        screen: "presentation",
        screenId: fallback.id,
        viewState: fallback.id.toLowerCase(),
        presentationState: fallbackState,
        route: productRouteFor(fallback.id),
        historyMode: "replace",
        resourceId,
      }, "", fallbackLocation);
      renderPresentationScreen(fallback.id, fallbackState);
    } else {
      history.replaceState({ screen: "catalog" }, "", presentationLocationFor("T01"));
      renderCatalog();
    }
    return false;
  }
  if (historyMode === "pop") {
    history.back();
    return true;
  }
  const method = historyMode === "push" ? "pushState" : "replaceState";
  const state = presentationState(screen, requestedState);
  const destination = presentationLocationFor(id, resourceId);
  if (!destination) return navigatePresentationScreen(fallbackId, "permission_closed", "replace", "T01", resourceId);
  history[method]({
    screen: "presentation",
    screenId: id,
    viewState: id.toLowerCase(),
    presentationState: state,
    route: productRouteFor(id),
    historyMode,
    resourceId,
  }, "", destination);
  renderPresentationScreen(id, state);
  return true;
}

const configureRoleNavigation = (profile) => {
  const roles = new Set(Array.isArray(profile.roles) ? profile.roles : [profile.role].filter(Boolean));
  const known = roles.size > 0;
  moderationNav.hidden = known && !roles.has("moderator");
  managementNav.hidden = !roles.has("administrator");
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

const createdAssignmentsButton = element("button", "Созданные мной", "back");
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
  setNavigation("catalog", false);
  title.textContent = "Каталог";
  back.classList.add("hidden");
  const boundary = element("section", undefined, "state-view");
  boundary.dataset.screenId = "T01";
  boundary.dataset.template = "list";
  boundary.dataset.state = tasks.length ? "content" : "empty";
  boundary.dataset.visualContract = JSON.stringify(presentationScreen("T01").fields);
  const create = element("button", "Создать задание", "primary");
  create.type = "button";
  create.addEventListener("click", () => openTaskCreation(true));
  if (!tasks.length) {
    boundary.append(create, element("p", "Сейчас нет доступных заданий.", "status muted"));
    replaceContent(boundary);
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
  boundary.append(create, list);
  replaceContent(boundary);
  focusTarget?.focus();
  returnFocusTaskId = null;
  restoreModerationFocus();
  restoreProfileFocus();
}

async function taskCreationCommand(body) {
  pendingTaskCreation ||= { key: newOperationKey(), body: JSON.stringify(body) };
  const response = await fetch("/api/v1/task-creation", {
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
    markTransition(publish, "PE-022", "authoritative_publish_success");
    publish.addEventListener("click", async () => {
      publish.disabled = true;
      try {
        const result = await taskCreationCommand({ action: "publish", draft_id: draft.id, expected_revision: draft.revision });
        history.replaceState({ screen: "task-creation", draftId: draft.id }, "", presentationLocationFor("T08", draft.id));
        const home = element("button", "В каталог", "primary");
        home.addEventListener("click", () => {
          history.replaceState({ screen: "catalog" }, "", presentationLocationFor("T01"));
          renderCatalog();
        });
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
  const deadlineMin = new Date(Date.now() + 60_000);
  deadlineMin.setSeconds(0, 0);
  form.deadline_at.min = new Date(deadlineMin - deadlineMin.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
  form.performer_slots.value = values.performer_slots || 1;
  form.material_text.value = values.materials?.text || "";
  form.material_url.value = values.materials?.url || "";
  const submit = element("button", "Предпросмотр", "primary");
  submit.type = "submit";
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
  updateDeadlineValidity();
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    saveStatus.classList.add("hidden");
    const value = Object.fromEntries(new FormData(form));
    const materials = Object.fromEntries([["text", value.material_text], ["url", value.material_url]].filter(([, item]) => item));
    delete value.material_text;
    delete value.material_url;
    try {
      await taskCreationCommand({ action: "save", draft_id: draft.id, expected_revision: draft.revision, form: { ...value, credit_reward_per_performer: Number(value.credit_reward_per_performer), performer_slots: Number(value.performer_slots), deadline_at: new Date(value.deadline_at).toISOString(), materials } });
      await openTaskCreation(false, false);
    } catch {
      saveStatus.textContent = "Не удалось сохранить задание. Проверьте данные и попробуйте снова.";
      saveStatus.classList.remove("hidden");
      submit.disabled = false;
    }
  });
  replaceContent(state.needs_edit ? element("p", "Предпросмотр устарел. Обновите данные.", "status") : form, form);
}

async function openTaskCreation(start, push = true) {
  if (push) {
    history.pushState(
      { screen: "task-creation", draftId: null },
      "",
      presentationLocationFor("T05"),
    );
  }
  setNavigation("", true);
  title.textContent = "Создать задание";
  back.classList.remove("hidden");
  replaceContent(element("p", "Загружаем черновик…", "status muted"));
  try {
    if (start) await taskCreationCommand({ action: "start" });
    const state = await getJson("/api/v1/task-creation");
    const draftId = state.draft?.id;
    if (draftId) {
      history.replaceState(
        { screen: "task-creation", draftId },
        "",
        presentationLocationFor("T05", draftId),
      );
    }
    renderTaskCreation(state);
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
  markTransition(save, "PE-063", "authoritative_profile_success");
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
  boundary.append(element("h3", "Лидерборд"));
  if (!items.length) {
    boundary.append(element("p", "В лидерборде пока никого нет.", "status muted"));
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

function memberListDetails(items) {
  if (!items.length) return element("p", "Участники не найдены.", "status muted");
  const list = element("ul", undefined, "list");
  for (const member of items) {
    const row = element("li");
    const button = element("button", undefined, "card");
    button.type = "button";
    button.append(element("h3", member.display_name));
    if (member.telegram_username) {
      button.append(element("p", "@" + member.telegram_username, "meta"));
    }
    button.append(
      element("p", "Уровень " + String(member.level_number), "meta"),
      element(
        "p",
        "Карма " + String(member.karma.score) + " · оценок " + String(member.karma.count),
        "meta",
      ),
    );
    button.addEventListener("click", () => showMemberProfile(member.member_id));
    row.append(button);
    list.append(row);
  }
  return list;
}

function renderParticipants(state, revision) {
  if (revision !== screenRevision) return;
  const isLeaderboard = state.view === "leaderboard";
  setNavigation(isLeaderboard ? "" : "participants", isLeaderboard);
  back.classList.toggle("hidden", !isLeaderboard);
  title.textContent = state.view === "leaderboard" ? "Лидерборд" : "Участники";
  const boundary = element("section", undefined, "state-view");
  boundary.dataset.screenId = state.view === "leaderboard" ? "P05" : "P01";
  boundary.dataset.state = state.loading ? "loading" : state.error ? "error" : "content";
  const tabs = element("div", undefined, "segmented");
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
    const search = element("form", undefined, "task-form");
    const label = element("label", "Имя или @username");
    const input = element("input");
    input.type = "search";
    input.minLength = 3;
    input.placeholder = "Минимум 3 символа";
    input.value = state.query;
    label.append(input);
    const submit = element("button", "Найти", "primary");
    submit.type = "submit";
    search.addEventListener("submit", (event) => {
      event.preventDefault();
      const query = input.value.trim();
      if (query && query.length < 3) {
        state.validation = "Введите минимум 3 символа.";
        renderParticipants(state, revision);
        return;
      }
      state.query = query;
      state.validation = "";
      void loadMembers(state, revision);
    });
    search.append(label, submit);
    boundary.append(search);
    if (state.validation) boundary.append(element("p", state.validation, "status"));
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
    boundary.append(leaderboardDetails(state.leaderboard || []));
  } else {
    boundary.append(memberListDetails(state.members || []));
  }
  replaceContent(boundary);
  if (state.focusHeading) {
    state.focusHeading = false;
    title.tabIndex = -1;
    title.focus();
  } else if (returnFocusLeaderboardTab && state.view === "members" && !state.loading) {
    returnFocusLeaderboardTab = false;
    leaderboardTab.focus();
  }
}

async function loadMembers(state, revision) {
  state.loading = true;
  state.error = false;
  renderParticipants(state, revision);
  const query = state.query ? "&query=" + encodeURIComponent(state.query) : "";
  try {
    const page = await getJson("/api/v1/members?limit=30" + query);
    if (revision !== screenRevision) return;
    state.members = page.items;
  } catch {
    if (revision !== screenRevision) return;
    state.error = true;
  }
  state.loading = false;
  renderParticipants(state, revision);
}

async function loadParticipantsLeaderboard(state, revision) {
  state.loading = true;
  state.error = false;
  renderParticipants(state, revision);
  try {
    const page = await getJson("/api/v1/leaderboard?limit=30");
    if (revision !== screenRevision) return;
    state.leaderboard = page.items;
  } catch {
    if (revision !== screenRevision) return;
    state.error = true;
  }
  state.loading = false;
  renderParticipants(state, revision);
}

function switchParticipantsView(state, revision, view) {
  state.view = view;
  state.error = false;
  state.focusHeading = view === "leaderboard";
  history.replaceState(
    { screen: "participants", view },
    "",
    presentationLocationFor(view === "leaderboard" ? "P05" : "P01"),
  );
  if (view === "leaderboard" && state.leaderboard === null) {
    void loadParticipantsLeaderboard(state, revision);
  } else if (view === "members" && state.members === null) {
    void loadMembers(state, revision);
  } else {
    renderParticipants(state, revision);
  }
}

function loadParticipants(view = "members") {
  const revision = ++screenRevision;
  const state = {
    view,
    query: "",
    validation: "",
    members: null,
    leaderboard: null,
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
  if (push) history.pushState({ screen: "member-profile", memberId }, "", presentationLocationFor("P02", memberId));
  setNavigation("", true);
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
  replaceContent(profileBoundary);
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

function loadProfile(push = true) {
  const revision = ++screenRevision;
  const state = { profile: null, profileError: false };
  state.profileRetry = element("button", "Повторить профиль", "secondary");
  state.profileRetry.type = "button";
  state.profileRetry.addEventListener("click", () => loadOwnProfile(state, revision));
  returnFocusProfile = true;
  if (push) history.replaceState({ screen: "profile" }, "", presentationLocationFor("P06"));
  setNavigation("profile", false);
  title.textContent = "Профиль";
  back.classList.add("hidden");
  renderProfile(state, revision);
  back.focus();
  void loadOwnProfile(state, revision);
}

function showTaskDetail(task, push = true) {
  screenRevision += 1;
  returnFocusTaskId = task.id;
  setNavigation("", true);
  title.textContent = "Карточка задания";
  back.classList.remove("hidden");
  if (push) history.pushState({ screen: "task", taskId: task.id }, "", presentationLocationFor("T03", task.id));
  const detail = element("article", undefined, "card detail");
  detail.append(element("h3", task.title), section("Автор", task.author_display_name));
  if (task.category_name) detail.append(section("Категория", task.category_name));
  if (task.task_kind) {
    detail.append(section("Тип", ({ solo: "Личное", group: "Групповое" })[task.task_kind]));
  }
  detail.append(
    dateSection("Срок", task.deadline_at),
    section("Награда", String(task.credit_reward_per_performer) + " кредитов"),
    section("Мест", String(task.performer_slots)),
    section("Формат", ({ online: "Онлайн", offline: "Офлайн", any: "Любой" })[task.format]),
  );
  if (task.city) detail.append(section("Город", task.city));
  detail.append(section("Описание", task.description));
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
  markTransition(accept, "PE-024", "authoritative_accept_success");
  accept.addEventListener("click", () => acceptTask(task, accept, status));
  detail.append(status, accept);
  replaceContent(detail);
  back.focus();
}

async function acceptTask(task, button, status) {
  button.disabled = true;
  status.className = "status";
  status.textContent = "Принимаем задание…";
  const operationKey = pendingAcceptKeys.get(task.id) || newOperationKey();
  pendingAcceptKeys.set(task.id, operationKey);
  try {
    const response = await fetch(
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
      : "Задание сейчас недоступно. Вернитесь в каталог и попробуйте другое.";
    if (!retryableSubmissionError(error)) pendingAcceptKeys.delete(task.id);
    button.disabled = false;
  }
}

function renderAssignments(revision = ++screenRevision) {
  if (revision !== screenRevision) return;
  setNavigation("assignments", false);
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
  if (push) history.replaceState({ screen: "assignments" }, "", presentationLocationFor("M01"));
  setNavigation("assignments", false);
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

const createdTaskStatus = (value) => ({
  published: "Опубликовано",
  closed_for_new_performers: "Набор закрыт",
  completed: "Завершено",
  cancelled: "Отменено",
}[value] || value);

async function loadCreatedReviews(push = true) {
  const revision = ++screenRevision;
  if (push) history.pushState({ screen: "created-assignments" }, "", presentationLocationFor("M09"));
  setNavigation("assignments", true);
  title.textContent = "Созданные мной";
  back.classList.remove("hidden");
  replaceContent(element("p", "Загружаем созданные задания…", "status muted"));
  try {
    const [owned, reviews] = await Promise.all([
      getJson("/api/v1/owned-tasks"),
      getJson("/api/v1/assignment-reviews"),
    ]);
    if (revision !== screenRevision) return;
    const nodes = [element("h3", "Мои опубликованные задания")];
    if (!owned.items.length) {
      nodes.push(element("p", "Созданных заданий пока нет.", "status muted"));
    } else {
      const ownedList = element("ul", undefined, "list");
      for (const task of owned.items) {
        const card = element("article", undefined, "card");
        card.append(
          element("h3", task.title),
          element("p", createdTaskStatus(task.status), "muted"),
          element(
            "p",
            "Исполнители: " + String(task.assignees.length) + "/" + String(task.performer_slots),
            "meta",
          ),
        );
        for (const assignee of task.assignees) {
          card.append(element(
            "p",
            assignee.display_name + " · " + assignmentStatus(assignee.status),
            "muted",
          ));
        }
        const item = element("li");
        item.append(card);
        ownedList.append(item);
      }
      nodes.push(ownedList);
    }
    nodes.push(element("h3", "Результаты на проверку"));
    if (!reviews.items.length) {
      nodes.push(element("p", "Результатов, ожидающих решения, пока нет.", "status muted"));
    } else {
      const reviewList = element("ul", undefined, "list");
      for (const review of reviews.items) {
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
        reviewList.append(item);
      }
      nodes.push(reviewList);
    }
    returnFocusReviewId = null;
    replaceContent(...nodes);
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
  if (push) history.pushState({ screen: "assignment-review", assignmentId }, "", presentationLocationFor("M12", assignmentId));
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
          history.replaceState(
            { screen: "created-assignments" },
            "",
            presentationLocationFor("M09"),
          );
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
    markTransition(begin, "PE-030", "open_result_versions");
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
    markTransition(confirm, "PE-034", "authoritative_submit_success");
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
  markTransition(submit, "PE-044", "open_dispute_materials");
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

function renderCancellation(assignment) {
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
    if (!normalized || !globalThis.confirm("Отказаться от задания и освободить слот?")) return;
    submit.disabled = true;
    status.className = "status";
    status.textContent = "Отказываемся от задания…";
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
      status.textContent = error instanceof TypeError
        ? "Сеть недоступна. Повторите запрос — он останется тем же."
        : "Не удалось отказаться. Проверьте состояние назначения и повторите.";
      if (!retryableSubmissionError(error)) operationKey = null;
      submit.disabled = false;
    }
  });
  form.append(heading, label, submit, status);
  return form;
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
    const response = await fetch(
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
    if (assignment.can_submit) {
      detail.append(renderSubmission(assignment, null));
    }
    if (assignment.can_cancel) {
      detail.append(renderCancellation(assignment));
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
  if (push) history.replaceState({ screen: "moderation" }, "", presentationLocationFor("S01"));
  setNavigation("moderation", false);
  title.textContent = "Очередь модерации";
  back.classList.add("hidden");
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
      presentationLocationFor("S02", caseId),
    );
  }
  setNavigation("moderation", true);
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
      markTransition(confirm, "PE-068", "authoritative_resolution_success");
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
    configureRoleNavigation(profile);
    welcome.textContent = profile.display_name
      + ", выберите понятное задание и помогите сообществу.";
    tasks = page.items;
    const initialPresentation = presentationFromLocation();
    history.replaceState({ screen: "catalog" }, "", presentationLocationFor("T01"));
    renderCatalog();
    const presentationId = initialPresentation?.screen.id;
    const resourceId = initialPresentation?.resourceId;
    if (presentationId === "P01" || presentationId === "P05") {
      loadParticipants(presentationId === "P05" ? "leaderboard" : "members");
    } else if (presentationId === "P06") {
      history.replaceState({ screen: "profile" }, "", presentationLocationFor("P06"));
      loadProfile(false);
    } else if (presentationId === "M01") {
      history.replaceState({ screen: "assignments" }, "", presentationLocationFor("M01"));
      loadAssignments(false);
    } else if (presentationId === "S01") {
      history.replaceState({ screen: "moderation" }, "", presentationLocationFor("S01"));
      loadModeration(false);
    } else if (presentationId === "T03" && resourceId) {
      const task = tasks.find((item) => item.id === resourceId);
      if (task) {
        history.replaceState({ screen: "task", taskId: task.id }, "", presentationLocationFor("T03", task.id));
        showTaskDetail(task, false);
      }
    } else if (presentationId === "P02" && resourceId) {
      history.replaceState({ screen: "member-profile", memberId: resourceId }, "", presentationLocationFor("P02", resourceId));
      showMemberProfile(resourceId, false);
    } else if (presentationId === "M03" && resourceId) {
      history.replaceState({ screen: "assignment", assignmentId: resourceId }, "", presentationLocationFor("M03", resourceId));
      showAssignmentDetail(resourceId, false);
    } else if (presentationId === "M12" && resourceId) {
      history.replaceState({ screen: "assignment-review", assignmentId: resourceId }, "", presentationLocationFor("M12", resourceId));
      showCreatedReview(resourceId, false);
    } else if (presentationId === "S02" && resourceId) {
      history.replaceState({ screen: "moderation-case", caseId: resourceId }, "", presentationLocationFor("S02", resourceId));
      showModerationCase(resourceId, false);
    }
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
  history.replaceState({ screen: "catalog" }, "", presentationLocationFor("T01"));
  renderCatalog();
});
assignmentsNav.addEventListener("click", () => loadAssignments());
profileNav.addEventListener("click", () => loadProfile());
participantsNav.addEventListener("click", () => loadParticipants());
moderationNav.addEventListener("click", () => loadModeration());
managementNav.addEventListener("click", () => {
  navigatePresentationScreen("G01", "content", "replace");
});
back.addEventListener("click", () => {
  if (history.state?.screen === "participants" && history.state.view === "leaderboard") {
    returnFocusLeaderboardTab = true;
    loadParticipants("members");
  } else if (history.state?.screen === "presentation" && history.state.screenId === "P05") {
    navigatePresentationScreen("P01", "content", "replace", "P01");
    queueMicrotask(() => content.querySelector('[data-transition-id="PE-057"]')?.focus());
  } else {
    history.back();
  }
});
globalThis.addEventListener("popstate", (event) => {
  if (event.state?.screen === "presentation") {
    renderPresentationScreen(event.state.screenId, event.state.presentationState);
  } else if (event.state?.screen === "participants") {
    loadParticipants(event.state.view || "members");
  } else if (event.state?.screen === "task") {
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
globalThis.addEventListener("hashchange", () => {
  if (!presentationFromLocation()) {
    history.replaceState({ screen: "catalog" }, "", presentationLocationFor("T01"));
    renderCatalog();
  }
});
bootstrap();
