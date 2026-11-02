// Điểm vào: điều hướng giữa các màn hình (thẻ chức năng), hộp "Gần đây", chọn kỳ báo cáo, chỉ báo hệ thống, hàng số liệu ở màn hình chào.
import { ALL, PERIODS } from "./config.js";
import { $, h, icon } from "./dom.js";
import { get } from "./api.js";
import { currentTitle, initChat, newChat } from "./chat.js";
import { vn } from "./format.js";
import { onPeriod, setPeriod } from "./state.js";
import { initLookup } from "./views/lookup.js";
import { initNotes } from "./views/notes.js";
import { getStats, showStats } from "./views/stats.js";
import { initTrends } from "./views/trends.js";

const VIEWS = ["chat", "lookup", "notes", "trends", "stats"];
const FEATURES = [                                                      // lối tắt ở màn hình chào tới các chức năng chính
  ["lookup", "book", "Tra cứu số liệu", "Một chỉ tiêu, một kỳ, kèm trang PDF"],
  ["notes", "doc", "Thuyết minh & nguồn", "Tìm đoạn thuyết minh, xem trang gốc"],
  ["trends", "zigzag", "Xu hướng & so sánh", "Biểu đồ 6 kỳ, hai kỳ, phân rã"],
  ["stats", "stats", "Thống kê", "Độ phủ dữ liệu của chatbot"],
];
const TAB_TITLES = { chat: "", lookup: "Tra cứu số liệu", notes: "Thuyết minh & nguồn", trends: "Xu hướng & so sánh", stats: "Thống kê" };
let currentView = "chat";

// ------------------------------------------------------------------ màn hình và hộp "Gần đây"
function closeHistory() { $("hist-panel").hidden = true; $("hist-btn").setAttribute("aria-expanded", "false"); }
function toggleHistory() {
  const opening = $("hist-panel").hidden;
  closeMenu();
  $("hist-panel").hidden = !opening; $("hist-btn").setAttribute("aria-expanded", String(opening));
  if (opening) ($("recent").querySelector(".conv-title") || $("hist-btn")).focus();
}

function refreshTitle() {
  const t = currentView === "chat" ? currentTitle() : TAB_TITLES[currentView];
  document.title = t && t !== "Cuộc trò chuyện mới" ? `${t} · Chatbot BCTC Vinamilk` : "Chatbot Phân Tích Tài Chính";
}
function showView(name) {
  currentView = name;
  VIEWS.forEach(v => ($("view-" + v).hidden = v !== name));
  document.querySelectorAll(".tab[data-view]").forEach(b => (b.dataset.view === name ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current")));
  refreshTitle(); closeHistory();
  if (name === "stats") showStats();
}

// ------------------------------------------------------------------ kỳ báo cáo (menu thả xuống ở thanh trên)
function closeMenu() { $("period-menu").hidden = true; $("period-btn").setAttribute("aria-expanded", "false"); }
function initPeriodMenu() {
  const menu = $("period-menu");
  [...PERIODS, ALL].forEach(p => menu.append(h("li", { role: "none" },
    h("button", { type: "button", role: "menuitemradio", "data-p": p, "aria-checked": "false", onclick: () => { setPeriod(p); closeMenu(); $("period-btn").focus(); } },
      h("span", { text: p === ALL ? "Tất cả kỳ" : p })))));
  onPeriod(p => {
    $("period-label").textContent = p === ALL ? "Tất cả kỳ" : p;
    menu.querySelectorAll("button").forEach(b => b.setAttribute("aria-checked", String(b.dataset.p === p)));
  });
  $("period-btn").onclick = () => {
    const opening = menu.hidden;
    closeHistory();
    menu.hidden = !opening; $("period-btn").setAttribute("aria-expanded", String(opening));
    if (opening) (menu.querySelector('[aria-checked="true"]') || menu.querySelector("button")).focus();
  };
  menu.onkeydown = e => {
    const items = [...menu.querySelectorAll("button")], i = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown") { e.preventDefault(); items[(i + 1) % items.length].focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); items[(i - 1 + items.length) % items.length].focus(); }
  };
  document.addEventListener("click", e => { if (!e.composedPath().some(n => n.classList && n.classList.contains("pill-wrap"))) { closeMenu(); closeHistory(); } });
}

// ------------------------------------------------------------------ chỉ báo hệ thống và hàng số liệu
function setDot(id, ok, text) { $("dot-" + id).className = "dot " + (ok ? "ok" : "bad"); $("val-" + id).textContent = text; }
async function refreshHealth() {
  try {
    const { data } = await get("/api/health");
    const dbOk = data.ok === true && data.periods > 0, aiOk = data.ok === true && data.gemini_key === true;
    setDot("db", dbOk, dbOk ? `${data.periods} kỳ` : "lỗi");
    setDot("ai", aiOk, aiOk ? "sẵn sàng" : "lỗi");
  } catch (_) { setDot("db", false, "lỗi"); setDot("ai", false, "lỗi"); }
}

async function fillWelcomeStats() {                                    // số đếm thật từ /api/stats; không lấy được thì chỉ giữ số kỳ (đếm từ danh sách kỳ)
  const parts = [[PERIODS.length, "kỳ báo cáo"]];
  const { data } = await getStats();
  if (data) parts.push([data.totals.metrics, "chỉ tiêu"], [data.totals.chunks, "đoạn thuyết minh"], [data.totals.page_images, "trang PDF dẫn chứng"]);
  $("stats").replaceChildren(...parts.map(([n, label]) => h("span", {}, h("b", { text: vn(n, 0) }), ` ${label}`)));
}

// ------------------------------------------------------------------ khởi tạo
initPeriodMenu();
initChat({ showView, closeSide: closeHistory, refreshTitle, unavailable: refreshHealth });
initLookup(); initNotes(); initTrends();
$("feats").replaceChildren(...FEATURES.map(([view, ic, name, desc]) =>
  h("button", { class: "feat", type: "button", onclick: () => showView(view) }, icon(ic), h("b", { text: name }), h("span", { text: desc }))));
document.querySelectorAll(".tab[data-view]").forEach(b => (b.onclick = () => showView(b.dataset.view)));
$("new-chat").onclick = newChat;
$("hist-btn").onclick = toggleHistory;
document.addEventListener("keydown", e => { if (e.key === "Escape") { closeMenu(); closeHistory(); } });
refreshHealth(); fillWelcomeStats();
