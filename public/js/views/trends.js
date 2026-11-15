// Màn hình Xu hướng & so sánh: chọn chỉ tiêu và kiểu so sánh, vẽ biểu đồ/bảng từ /api/chart (cùng khối dữ liệu với câu trả lời của trợ lý, không cần khóa Gemini).
import { $, h } from "../dom.js";
import { ALL, CHART_METRICS, EXPLAIN_METRICS, PERIODS } from "../config.js";
import { attempt, post } from "../api.js";
import { chartsEl } from "../charts.js";
import { onPeriod } from "../state.js";
import { commonPeriods, fillPeers, loadCompanyOptions, selectedPeers, setOptions } from "../company-catalog.js";

const isSeries = () => $("c-mode").value === "series";
let catalog, syncPeers;

function fillMetrics(select, list, optional) {
  const keep = select.value;
  select.replaceChildren(...(optional ? [h("option", { value: "", text: "— thêm chỉ tiêu —" })] : []), ...list.map(m => h("option", { value: m, text: m })));
  select.value = list.includes(keep) ? keep : (optional ? "" : list[0]);
}

function syncControls() {
  const company = $("c-company").value, mode = $("c-mode");
  mode.querySelector('[value="explain"]').disabled = company !== "VNM";
  if (mode.value === "explain" && company !== "VNM") mode.value = "series";
  const compare = mode.value === "companies";
  if (!compare && company === "VNM") {
    fillMetrics($("c-m1"), mode.value === "explain" ? EXPLAIN_METRICS : CHART_METRICS, false);
    fillMetrics($("c-m2"), CHART_METRICS, true);
    fillMetrics($("c-m3"), CHART_METRICS, true);
  } else if (catalog) {
    setOptions($("c-m1"), catalog.metrics);
    for (const id of ["c-m2", "c-m3"]) setOptions($(id), {"": "— thêm chỉ tiêu —", ...catalog.metrics});
  }
  $("c-m2").closest("label").hidden = $("c-m3").closest("label").hidden = !isSeries();
  $("c-period-wrap").hidden = isSeries();
  $("c-kind-wrap").hidden = isSeries() || compare;
  $("c-peers").hidden = !compare || !catalog;
  if (catalog) {
    const peers = selectedPeers($("c-peers"));
    const allowed = compare ? commonPeriods(catalog, [company, ...peers]) :
      catalog.available[company].filter(p => p.startsWith("Q"));
    setOptions($("c-period"), Object.fromEntries(allowed.map(p => [p, catalog.periods[p]])), allowed.at(-1));
    $("c-basis").disabled = compare && $("c-period").value.startsWith("FY");
    $("chart-form").querySelector("button").disabled = (!isSeries() && !allowed.length) || (compare && !peers.length);
    $("c-compare-status").textContent = compare && !allowed.length ? "Các doanh nghiệp đã chọn chưa có kỳ báo cáo chung." : "";
  } else {
    $("chart-form").querySelector("button").disabled = compare;
  }
}

async function draw(e) {
  e.preventDefault();
  const out = $("chart-out"), mode = $("c-mode").value;
  if ((mode === "explain" || mode === "growth" && $("c-company").value !== "VNM") && $("c-kind").value === "qoq" && $("c-basis").value === "luy_ke") {
    out.replaceChildren(h("div", { class: "errbox", role: "alert", text: "So với quý liền trước chỉ áp dụng cho số liệu riêng quý. Hãy chọn \"Riêng quý\" hoặc \"So với cùng kỳ năm trước\"." }));
    return;
  }
  const metrics = [...new Set(["c-m1", "c-m2", "c-m3"].map(id => $(id).value).filter((v, i) => v && (isSeries() || i === 0)))];
  out.replaceChildren(h("p", { class: "note", text: "Đang dựng biểu đồ…" }));
  const companies = [$("c-company").value];
  if (mode === "companies") companies.push(...selectedPeers($("c-peers")));
  const r = await attempt(() => post("/api/chart", { mode, metrics, companies, period: mode === "series" ? null : $("c-period").value, kind: $("c-kind").value, basis: $("c-basis").value }));
  out.replaceChildren(r.error ? h("div", { class: "errbox", role: "alert", text: r.error }) : chartsEl(r.data.charts) || h("p", { class: "note", text: "Không có số liệu cho lựa chọn này." }));
}

export function initTrends() {
  PERIODS.forEach(p => $("c-period").append(h("option", { value: p, text: p })));
  onPeriod(p => { if ($("c-company").value === "VNM" && p !== ALL && [...$("c-period").options].some(o => o.value === p)) $("c-period").value = p; });
  fillMetrics($("c-m2"), CHART_METRICS, true);
  fillMetrics($("c-m3"), CHART_METRICS, true);
  syncControls();
  $("c-mode").onchange = $("c-period").onchange = syncControls;
  $("c-company").onchange = () => syncPeers($("c-company").value);
  $("chart-form").onsubmit = draw;
  loadCompanyOptions($("c-company-status"), data => {
    catalog = data;
    setOptions($("c-company"), catalog.companies);
    $("c-company").disabled = false;
    syncPeers = fillPeers($("c-peers"), catalog.companies, syncControls);
    syncPeers($("c-company").value);
  });
}
