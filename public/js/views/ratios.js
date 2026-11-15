// Màn hình Chỉ số tài chính: bảng chỉ số của một kỳ từ /api/ratios (không qua trợ lý, không cần khóa Gemini).
// Mỗi thẻ có giá trị, thay đổi so với kỳ so sánh, đường nhỏ qua các kỳ, và phần mở ra công thức + nguồn trang PDF.
import { $, h, icon } from "../dom.js";
import { ALL, PERIODS } from "../config.js";
import { attempt, post } from "../api.js";
import { signed, vn } from "../format.js";
import { sourceActionsEl, sourceTitle } from "../sources.js";
import { onPeriod } from "../state.js";
import { commonPeriods, fillPeers, loadCompanyOptions, selectedPeers, setOptions } from "../company-catalog.js";

const SPARK = { w: 120, h: 32, pad: 3 };
let catalog, syncPeers, loadId = 0;

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

function comparison(data) {
  const companies = data.comparison;
  const items = companies.map(c => new Map(c.groups.flatMap(g => g.items.map(i => [i.name, i]))));
  const names = [...new Set(items.flatMap(list => [...list.keys()]))]
    .filter(name => items.filter(list => list.has(name)).length >= 2);
  return h("div", { class: "tbl" }, h("table", {},
    h("caption", { text: `So sánh chỉ số · ${catalog.periods[data.period] || data.period}` }),
    h("thead", {}, h("tr", {}, h("th", { scope: "col", text: "Chỉ số" }),
      companies.map(c => h("th", { scope: "col", text: `${c.name} (${c.company})` })))),
    h("tbody", {}, names.map(name => h("tr", {}, h("th", { scope: "row", text: name }), items.map(list => {
      const item = list.get(name);
      if (item?.value == null) return h("td", { text: "Chưa có số" });
      return h("td", {}, h("strong", { text: show(item.value, item.unit) }),
        h("details", {}, h("summary", { text: "Công thức và nguồn" }),
          h("p", { text: item.formula }), item.sources.map(s => sourceActionsEl(s))));
    }))))));
}

async function load() {
  const out = $("ratios-out");
  const id = ++loadId;
  const period = $("r-period").value;
  const companies = [$("r-company").value, ...selectedPeers($("r-peers"))];
  if (!period) {
    out.replaceChildren(h("p", { class: "note", text: "Các doanh nghiệp đã chọn chưa có kỳ báo cáo chung." }));
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

export const showRatios = load;                           // main.js gọi khi mở màn hình, để luôn tính theo kỳ đang chọn

export function initRatios() {
  PERIODS.forEach(p => $("r-period").append(h("option", { value: p, text: p })));
  onPeriod(p => {
    if ($("r-company").value !== "VNM" || selectedPeers($("r-peers")).length) return;
    $("r-period").value = p === ALL ? PERIODS[0] : p;
    if (!$("view-ratios").hidden) load();
  });
  $("r-company").onchange = () => syncPeers($("r-company").value);
  $("r-period").onchange = $("r-basis").onchange = onSelectionChange;
  $("ratios-form").onsubmit = event => { event.preventDefault(); load(); };
  loadCompanyOptions($("r-company-status"), data => {
    catalog = data;
    setOptions($("r-company"), catalog.companies);
    $("r-company").disabled = false;
    $("r-peers").hidden = false;
    syncPeers = fillPeers($("r-peers"), catalog.companies, updatePeriods);
    syncPeers($("r-company").value);
  });
}

function updatePeriods() {
  const allowed = commonPeriods(catalog, [$("r-company").value, ...selectedPeers($("r-peers"))]);
  setOptions($("r-period"), Object.fromEntries(allowed.map(p => [p, catalog.periods[p]])), allowed.at(-1));
  onSelectionChange();
}

function onSelectionChange() {
  $("r-basis").disabled = $("r-period").value.startsWith("FY");
  $("ratios-form").querySelector("button").disabled = !$("r-period").value;
  if ($("view-ratios").hidden) return;
  if (selectedPeers($("r-peers")).length && $("r-period").value) {
    loadId++;
    $("ratios-out").replaceChildren(h("p", { class: "note", text: "Bấm Xem chỉ số để so sánh các doanh nghiệp đã chọn." }));
  } else {
    load();
  }
}
