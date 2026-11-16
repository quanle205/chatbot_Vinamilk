// Tab Chỉ số tài chính (trong màn hình Phân tích): chỉ số của một kỳ từ /api/ratios (không qua trợ lý, không cần khóa Gemini).
// Một doanh nghiệp: thẻ giá trị, thay đổi so với kỳ so sánh, đường nhỏ qua các kỳ, công thức + nguồn trang PDF.
// Nhiều doanh nghiệp: bảng chỉ số × doanh nghiệp, ghi rõ phạm vi số (riêng/hợp nhất) và doanh nghiệp chưa có báo cáo kỳ đó.
import { $, h, icon } from "../dom.js";
import { attempt, post } from "../api.js";
import { signed, vn } from "../format.js";
import { sourceActionsEl, sourceTitle } from "../sources.js";
import { onPeriod } from "../state.js";
import { setOptions } from "../company-catalog.js";
import { bestPeriod, getCatalog, onSelectionChange, periodsFor, selectedCompanies } from "./trends.js?v=analysis";

const SPARK = { w: 120, h: 32, pad: 3 };
let loadId = 0, lastKey = "";

const show = (v, unit) => (unit === "%" ? `${vn(v * 100, 1)}%` : unit === "ngày" ? `${vn(v, 1)} ngày` : `${vn(v, 2)} ${unit}`);
const change = (d, unit) => (unit === "%" ? `${signed(d * 100, 1)} điểm %` : unit === "ngày" ? `${signed(d, 1)} ngày` : `${signed(d, 2)} ${unit}`);

// Đường nhỏ qua các kỳ: kỳ đang xem có chấm đậm; kỳ thiếu số thì ngắt đoạn.
function sparkline(history, current) {
  const NS = "http://www.w3.org/2000/svg", pts = history.filter(x => x.value != null);
  if (pts.length < 2) return null;
  const vals = pts.map(x => x.value), lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
  const x = i => SPARK.pad + (i * (SPARK.w - 2 * SPARK.pad)) / (history.length - 1);
  const y = v => SPARK.h - SPARK.pad - ((v - lo) / span) * (SPARK.h - 2 * SPARK.pad);
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${SPARK.w} ${SPARK.h}`); svg.setAttribute("class", "spark");
  svg.setAttribute("role", "img"); svg.setAttribute("aria-label", `Đường ${history.length} kỳ, từ ${history[0].period} đến ${history[history.length - 1].period}`);
  const line = document.createElementNS(NS, "polyline");
  line.setAttribute("points", history.map((p, i) => (p.value == null ? null : `${x(i).toFixed(1)},${y(p.value).toFixed(1)}`)).filter(Boolean).join(" "));
  svg.append(line);
  const i = history.findIndex(p => p.period === current);
  if (i >= 0 && history[i].value != null) {
    const dot = document.createElementNS(NS, "circle");
    dot.setAttribute("cx", x(i).toFixed(1)); dot.setAttribute("cy", y(history[i].value).toFixed(1)); dot.setAttribute("r", "3");
    svg.append(dot);
  }
  return svg;
}

function card(item, data) {
  if (item.value == null) return h("div", { class: "ratio-card off" }, h("div", { class: "r-name", text: item.name }), h("div", { class: "note", text: item.error }));
  const head = h("div", { class: "r-top" },
    h("div", {}, h("div", { class: "r-name", text: item.name }), h("div", { class: "r-val", text: show(item.value, item.unit) })),
    sparkline(item.history, data.period));
  const delta = item.delta == null
    ? h("div", { class: "r-delta none", text: `Chưa có số ${data.compare_label} để so sánh` })
    : h("div", { class: "r-delta" }, icon(item.delta > 0 ? "up" : item.delta < 0 ? "arrow-down" : "minus"),
        h("span", { text: `${change(item.delta, item.unit)} so với ${data.compare_label} (${data.compare_period})` }));
  const annual = item.annualized != null ? h("div", { class: "note", text: `Quy năm: ${show(item.annualized, item.unit)}` }) : null;
  const more = h("details", { class: "r-more" }, h("summary", { text: "Công thức và nguồn" }),
    h("p", { class: "note", text: item.formula }),
    item.notes.length ? h("ul", { class: "note" }, item.notes.map(n => h("li", { text: n }))) : null,
    h("ul", { class: "r-src" }, item.sources.map(s => h("li", {}, h("div", { class: "src-h", text: sourceTitle(s) }), sourceActionsEl(s)))));
  return h("div", { class: "ratio-card" }, head, delta, annual, more);
}

const COMPARE_NOTE = "Số liệu từ báo cáo đã đối chiếu. Vinamilk có 14 chỉ số; các doanh nghiệp khác chỉ tính được 4 chỉ số có đủ số liệu đầu vào cùng phạm vi (ROE, ROA, vòng quay tồn kho... cần số dư đầu kỳ hoặc giá vốn nên không tính để tránh so sánh sai). "
  + "Dấu – nghĩa là chỉ số không tính được cho doanh nghiệp đó.";

function comparison(data) {
  const catalog = getCatalog();
  const columns = data.comparison;
  const items = columns.map(c => new Map(c.groups.flatMap(g => g.items.map(i => [i.name, i]))));
  const names = [...new Set(items.flatMap(list => [...list.keys()]))];                  // đủ mọi chỉ số, thứ tự của doanh nghiệp có nhiều chỉ số nhất
  const lead = items.reduce((a, b) => (b.size > a.size ? b : a), items[0]);
  names.sort((a, b) => (lead.has(a) ? [...lead.keys()].indexOf(a) : 99) - (lead.has(b) ? [...lead.keys()].indexOf(b) : 99));
  const scopes = new Set(items.flatMap(list => [...list.values()].map(i => i.scope).filter(Boolean)));
  const missing = columns.filter(c => c.error).map(c => c.company);
  const cell = (c, list, name) => {
    if (c.error) return h("td", { class: "off", text: "Chưa có báo cáo kỳ này" });
    const item = list.get(name);
    if (!item) return h("td", { text: "–" });
    if (item.value == null) return h("td", { title: item.error || "", text: "Chưa có số đối chiếu" });
    return h("td", { class: "n" }, h("strong", { text: show(item.value, item.unit) }), item.scope ? h("span", { class: "rt-scope", text: item.scope }) : null,
      h("details", { class: "pgd" }, h("summary", { text: "Nguồn" }), h("p", { class: "note", text: item.formula }), item.sources.map(src => sourceActionsEl(src))));
  };
  return h("div", {}, h("h3", { class: "sec-title rt-cap", text: `So sánh chỉ số · ${catalog.periods[data.period] || data.period} · ${columns.length - missing.length}/${columns.length} doanh nghiệp có báo cáo` }),
    h("div", { class: "tbl rt-tbl" }, h("table", {},
    h("thead", {}, h("tr", {}, h("th", { scope: "col", text: "Chỉ số" }), columns.map(c => h("th", { class: "n", scope: "col", text: `${c.name} (${c.company})` })))),
    h("tbody", {}, names.map(name => h("tr", {}, h("th", { scope: "row", text: name }), columns.map((c, i) => cell(c, items[i], name))))))),
    h("p", { class: "note rt-note", text: COMPARE_NOTE }),
    scopes.size > 1 ? h("p", { class: "note rt-note", text: "Lưu ý: bảng trộn số hợp nhất và số riêng công ty; tỷ số vẫn đúng với phạm vi ghi dưới mỗi số nhưng không hoàn toàn cùng cơ sở." }) : null);
}

async function load() {
  const out = $("ratios-out");
  const id = ++loadId;
  const period = $("r-period").value, companies = selectedCompanies();
  if (!companies.length || !period) {
    out.replaceChildren(h("p", { class: "note", text: companies.length ? "Các doanh nghiệp đã chọn chưa có kỳ báo cáo." : "Chọn ít nhất một doanh nghiệp." }));
    return;
  }
  out.replaceChildren(h("div", { class: "ratio-grid", "aria-busy": "true" }, Array.from({ length: 6 }, () => h("div", { class: "ratio-card skel-card" }, h("div", { class: "skel" }, h("i"), h("i"))))));
  const r = await attempt(() => post("/api/ratios", { companies, period, basis: $("r-basis").value }));
  if (id !== loadId) return;
  if (r.error) { out.replaceChildren(h("div", { class: "errbox", role: "alert", text: r.error })); return; }
  if (r.data.comparison) { out.replaceChildren(comparison(r.data)); return; }
  out.replaceChildren(...r.data.groups.map(g => h("section", { class: "r-group" },
    h("h3", { class: "sec-title", text: g.name }), h("div", { class: "ratio-grid" }, g.items.map(i => card(i, r.data))))));
}

const active = () => !$("view-trends").hidden && !$("panel-ratios").hidden;

// Đồng bộ kỳ và cách tính theo doanh nghiệp đã chọn; chỉ tải lại khi lựa chọn đổi thật sự (hoặc khi mở tab).
function sync() {
  const catalog = getCatalog();
  if (!catalog) return;
  const companies = selectedCompanies(), allowed = periodsFor(companies, 1, false, false);
  setOptions($("r-period"), Object.fromEntries(allowed.map(p => [p, catalog.periods[p]])), bestPeriod(companies, allowed, false));
  $("r-basis").disabled = $("r-period").value.startsWith("FY");
  $("ratios-form").querySelector("button[type=submit]").disabled = !companies.length || !$("r-period").value;
  $("r-status").textContent = !companies.length ? "Chọn ít nhất một doanh nghiệp." : companies.length > 1 ? "Nhiều doanh nghiệp: hiện bảng so sánh. Chọn riêng một doanh nghiệp để xem đủ thẻ chỉ số, công thức và đường xu hướng." : "";
  const key = [companies.join(","), $("r-period").value, $("r-basis").value].join("|");
  if (active() && key !== lastKey) { lastKey = key; load(); }
}

export function initRatios() {
  onSelectionChange(sync);                                // doanh nghiệp đổi hoặc mở tab: đồng bộ rồi tải
  onPeriod(p => { if (active() && [...$("r-period").options].some(o => o.value === p)) { $("r-period").value = p; sync(); } });
  $("r-period").onchange = $("r-basis").onchange = sync;
  $("ratios-form").onsubmit = event => { event.preventDefault(); lastKey = ""; sync(); };
}
