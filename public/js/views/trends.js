// Màn hình Phân tích: danh sách doanh nghiệp (mặc định đủ 12) dùng chung cho hai tab.
//  - Xu hướng & so sánh (file này): chọn kiểu và chỉ tiêu, vẽ biểu đồ/bảng từ /api/chart (cùng khối dữ liệu với câu trả lời của trợ lý).
//  - Chỉ số tài chính (ratios.js): lấy danh sách doanh nghiệp và danh mục kỳ từ file này.
// Không cần khóa Gemini.
import { $, h } from "../dom.js";
import { ALL, CHART_METRICS, EXPLAIN_METRICS, PERIODS } from "../config.js";
import { attempt, post } from "../api.js";
import { chartsEl } from "../charts.js";
import { onPeriod } from "../state.js";
import { loadCompanyOptions, setOptions } from "../company-catalog.js";

const isSeries = () => $("c-mode").value === "series";
let catalog = null;
const listeners = [];                                                  // ratios.js đăng ký để biết khi doanh nghiệp được chọn thay đổi
export const onSelectionChange = fn => listeners.push(fn);
export const getCatalog = () => catalog;
export const refreshAnalysis = () => listeners.forEach(fn => fn());      // main.js gọi khi mở màn hình, để tab Chỉ số tài chính tải theo lựa chọn hiện tại
export const selectedCompanies = () => selected();

const boxes = () => [...$("c-grid").querySelectorAll("input[type=checkbox]")];
const selected = () => boxes().filter(box => box.checked).map(box => box.value);
const vnmOnly = () => { const s = selected(); return s.length === 1 && s[0] === "VNM"; };      // một mình Vinamilk: dùng danh mục chỉ tiêu đầy đủ của Vinamilk

function fillMetrics(select, list, optional) {
  const keep = select.value;
  select.replaceChildren(...(optional ? [h("option", { value: "", text: "— thêm chỉ tiêu —" })] : []), ...list.map(m => h("option", { value: m, text: m })));
  select.value = list.includes(keep) ? keep : (optional ? "" : list[0]);
}

// Các kỳ chọn được: kỳ có báo cáo của ít nhất `need` doanh nghiệp đã chọn (kiểu so sánh cùng kỳ cần từ hai doanh nghiệp).
export function periodsFor(companies, need, quarterOnly, withBase) {
  return Object.keys(catalog.periods).filter(p => (!quarterOnly || p.startsWith("Q")) && coverage(companies, p, withBase) >= need);
}
// Số doanh nghiệp có báo cáo kỳ `period` (và kỳ gốc để so sánh nếu `withBase`).
const hasPeriod = (code, p) => (catalog.available[code] || []).includes(p);
const coverage = (companies, period, withBase) => {
  const base = withBase ? baseOf(period) : null;
  return companies.filter(code => hasPeriod(code, period) && (!withBase || hasPeriod(code, base))).length;
};
function baseOf(period) {                         // kỳ gốc: cùng kỳ năm trước hoặc quý liền trước, theo ô "So với"
  const m = /^Q([1-4])\/(\d{4})$/.exec(period);
  if (!m) return null;
  const q = +m[1], y = +m[2];
  return $("c-kind").value === "qoq" ? (q === 1 ? `Q4/${y - 1}` : `Q${q - 1}/${y}`) : `Q${q}/${y - 1}`;
}

// Kỳ mặc định: kỳ có báo cáo của nhiều doanh nghiệp đã chọn nhất (bằng nhau thì lấy kỳ mới hơn), để bảng hiện được đủ doanh nghiệp.
export const bestPeriod = (companies, periods, withBase) => periods.reduce((best, p) => (best == null || coverage(companies, p, withBase) >= coverage(companies, best, withBase) ? p : best), null);

function syncControls() {
  const mode = $("c-mode"), chosen = selected(), button = $("chart-form").querySelector("button[type=submit]"), status = $("c-compare-status");
  const compare = mode.value === "companies", single = vnmOnly();
  $("c-count").textContent = catalog ? `· đã chọn ${chosen.length}/${boxes().length}` : "";
  mode.querySelector('[value="explain"]').disabled = !single;
  if (mode.value === "explain" && !single) mode.value = "series";
  if (single && !compare) {
    fillMetrics($("c-m1"), mode.value === "explain" ? EXPLAIN_METRICS : CHART_METRICS, false);
    fillMetrics($("c-m2"), CHART_METRICS, true);
    fillMetrics($("c-m3"), CHART_METRICS, true);
  } else if (catalog) {
    setOptions($("c-m1"), catalog.metrics, "doanh_thu_thuan");
    for (const id of ["c-m2", "c-m3"]) setOptions($(id), { "": "— thêm chỉ tiêu —", ...catalog.metrics });
  }
  $("c-m2").closest("label").hidden = $("c-m3").closest("label").hidden = !isSeries();
  $("c-period-wrap").hidden = isSeries();
  $("c-kind-wrap").hidden = isSeries() || compare;
  let problem = "";
  if (!chosen.length) problem = "Chọn ít nhất một doanh nghiệp.";
  else if (compare && chosen.length < 2) problem = "So sánh cùng kỳ cần chọn từ hai doanh nghiệp.";
  if (catalog) {
    const growth = mode.value === "growth", allowed = isSeries() ? [] : periodsFor(chosen, compare ? 2 : 1, !compare, growth);
    setOptions($("c-period"), Object.fromEntries(allowed.map(p => [p, catalog.periods[p]])), bestPeriod(chosen, allowed, growth));
    $("c-basis").disabled = compare && $("c-period").value.startsWith("FY");
    if (!problem && !isSeries() && !allowed.length) problem = "Các doanh nghiệp đã chọn chưa có kỳ báo cáo phù hợp.";
  }
  status.textContent = problem;
  button.disabled = !!problem;
  listeners.forEach(fn => fn());
}

// Hai tab dùng chung danh sách doanh nghiệp: đổi tab không mất lựa chọn.
function showTab(name) {
  for (const tab of document.querySelectorAll(".tab[data-tab]")) {
    const on = tab.dataset.tab === name;
    tab.setAttribute("aria-selected", String(on)); tab.tabIndex = on ? 0 : -1;
    $("panel-" + tab.dataset.tab).hidden = !on;
  }
  listeners.forEach(fn => fn());
}

async function draw(e) {
  e.preventDefault();
  const out = $("chart-out"), mode = $("c-mode").value, companies = selected();
  if ((mode === "explain" || mode === "growth" && !vnmOnly()) && $("c-kind").value === "qoq" && $("c-basis").value === "luy_ke") {
    out.replaceChildren(h("div", { class: "errbox", role: "alert", text: "So với quý liền trước chỉ áp dụng cho số liệu riêng quý. Hãy chọn \"Riêng quý\" hoặc \"So với cùng kỳ năm trước\"." }));
    return;
  }
  const metrics = [...new Set(["c-m1", "c-m2", "c-m3"].map(id => $(id).value).filter((v, i) => v && (isSeries() || i === 0)))];
  out.replaceChildren(h("p", { class: "note", text: "Đang dựng biểu đồ…" }));
  const r = await attempt(() => post("/api/chart", { mode, metrics, companies, period: mode === "series" ? null : $("c-period").value, kind: $("c-kind").value, basis: $("c-basis").value }));
  out.replaceChildren(r.error ? h("div", { class: "errbox", role: "alert", text: r.error }) : chartsEl(r.data.charts) || h("p", { class: "note", text: "Không có số liệu cho lựa chọn này." }));
}

export function initTrends() {
  PERIODS.forEach(p => $("c-period").append(h("option", { value: p, text: p })));
  onPeriod(p => { if (p !== ALL && [...$("c-period").options].some(o => o.value === p)) $("c-period").value = p; });
  fillMetrics($("c-m2"), CHART_METRICS, true);
  fillMetrics($("c-m3"), CHART_METRICS, true);
  syncControls();
  $("c-mode").onchange = $("c-period").onchange = $("c-kind").onchange = syncControls;
  $("c-grid").onchange = syncControls;
  document.querySelectorAll(".tab[data-tab]").forEach(tab => {
    tab.onclick = () => showTab(tab.dataset.tab);
    tab.onkeydown = e => {                                              // mũi tên trái/phải chuyển tab (mẫu WAI-ARIA)
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      const tabs = [...document.querySelectorAll(".tab[data-tab]")], next = tabs[(tabs.indexOf(tab) + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length];
      showTab(next.dataset.tab); next.focus();
    };
  });
  $("c-all").onclick = () => { boxes().forEach(box => (box.checked = true)); syncControls(); };
  $("c-none").onclick = () => { boxes().forEach(box => (box.checked = false)); syncControls(); };
  $("chart-form").onsubmit = draw;
  loadCompanyOptions($("c-company-status"), data => {
    catalog = data;
    $("c-grid").replaceChildren(...Object.entries(catalog.companies).map(([code, name]) =>
      h("label", {}, h("input", { type: "checkbox", value: code, checked: true }), `${name} (${code})`)));
    $("c-companies").disabled = false;
    syncControls();
  });
}
