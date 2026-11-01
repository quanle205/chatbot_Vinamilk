// Điểm vào: điều hướng giữa các màn hình, thanh bên (ngăn kéo trên điện thoại), chọn kỳ báo cáo, chỉ báo hệ thống, hàng số liệu ở màn hình chào.
import { ALL, PERIODS } from "./config.js";
import { $, h } from "./dom.js";
import { get } from "./api.js";
import { currentTitle, initChat, newChat } from "./chat.js";
import { vn } from "./format.js";
import { onPeriod, setPeriod } from "./state.js";
import { initLookup } from "./views/lookup.js";
import { initNotes } from "./views/notes.js";
import { getStats, showStats } from "./views/stats.js";
import { initTrends } from "./views/trends.js";

const VIEW_TITLES = { lookup: "Tra cứu số liệu", notes: "Thuyết minh & nguồn", trends: "Xu hướng & so sánh", stats: "Thống kê" };
const views = ["chat", ...Object.keys(VIEW_TITLES)];
let currentView = "chat";

// ------------------------------------------------------------------ màn hình và thanh bên
const narrow = window.matchMedia("(max-width:900px)");
function syncSide() {
  const open = $("side").classList.contains("open");
  $("side").inert = narrow.matches && !open;                          // ngăn kéo đóng thì không focus được vào bên trong
  $("open-side").setAttribute("aria-expanded", String(open));
}
function openSide() { $("side").classList.add("open"); $("scrim").classList.add("show"); syncSide(); $("new-chat").focus(); }
function closeSide() { $("side").classList.remove("open"); $("scrim").classList.remove("show"); syncSide(); }

function refreshTitle() { $("top-title").textContent = currentView === "chat" ? currentTitle() : VIEW_TITLES[currentView]; }
function showView(name) {
  currentView = name;
  views.forEach(v => ($("view-" + v).hidden = v !== name));
  document.querySelectorAll(".nav-item[data-view]").forEach(b => (b.dataset.view === name ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current")));
  refreshTitle(); closeSide();
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
    menu.hidden = !opening; $("period-btn").setAttribute("aria-expanded", String(opening));
    if (opening) (menu.querySelector('[aria-checked="true"]') || menu.querySelector("button")).focus();
  };
  menu.onkeydown = e => {
    const items = [...menu.querySelectorAll("button")], i = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown") { e.preventDefault(); items[(i + 1) % items.length].focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); items[(i - 1 + items.length) % items.length].focus(); }
  };
  document.addEventListener("click", e => { if (!e.target.closest(".pill-wrap")) closeMenu(); });
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
initChat({ showView, closeSide, refreshTitle, unavailable: refreshHealth });
initLookup(); initNotes(); initTrends();
document.querySelectorAll(".nav-item[data-view]").forEach(b => (b.onclick = () => showView(b.dataset.view)));
$("new-chat").onclick = newChat;
$("open-side").onclick = openSide;
$("scrim").onclick = closeSide;
narrow.addEventListener("change", syncSide);
document.addEventListener("keydown", e => { if (e.key === "Escape") { closeMenu(); closeSide(); } });
syncSide(); refreshHealth(); fillWelcomeStats();
