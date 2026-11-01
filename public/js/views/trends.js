// Màn hình Xu hướng & so sánh: chọn chỉ tiêu và kiểu so sánh, vẽ biểu đồ/bảng từ /api/chart (cùng khối dữ liệu với câu trả lời của trợ lý, không cần khóa Gemini).
import { $, h } from "../dom.js";
import { ALL, CHART_METRICS, EXPLAIN_METRICS, PERIODS } from "../config.js";
import { attempt, post } from "../api.js";
import { chartsEl } from "../charts.js";
import { onPeriod } from "../state.js";

const isSeries = () => $("c-mode").value === "series";

function fillMetrics(select, list, optional) {
  const keep = select.value;
  select.replaceChildren(...(optional ? [h("option", { value: "", text: "— thêm chỉ tiêu —" })] : []), ...list.map(m => h("option", { value: m, text: m })));
  select.value = list.includes(keep) ? keep : (optional ? "" : list[0]);
}

function syncControls() {
  const series = isSeries();
  fillMetrics($("c-m1"), $("c-mode").value === "explain" ? EXPLAIN_METRICS : CHART_METRICS, false);   // phân rã chỉ hỗ trợ hai chỉ tiêu
  $("c-m2").hidden = $("c-m3").hidden = !series;
  $("c-period-wrap").hidden = $("c-kind-wrap").hidden = series;
}

async function draw(e) {
  e.preventDefault();
  const out = $("chart-out"), mode = $("c-mode").value;
  if (mode === "explain" && $("c-kind").value === "qoq" && $("c-basis").value === "luy_ke") {
    out.replaceChildren(h("div", { class: "errbox", role: "alert", text: "So với quý liền trước chỉ áp dụng cho số liệu riêng quý. Hãy chọn \"Riêng quý\" hoặc \"So với cùng kỳ năm trước\"." }));
    return;
  }
  const metrics = [...new Set(["c-m1", "c-m2", "c-m3"].map(id => $(id).value).filter((v, i) => v && (isSeries() || i === 0)))];
  out.replaceChildren(h("p", { class: "note", text: "Đang dựng biểu đồ…" }));
  const r = await attempt(() => post("/api/chart", { mode, metrics, period: isSeries() ? null : $("c-period").value, kind: $("c-kind").value, basis: $("c-basis").value }));
  out.replaceChildren(r.error ? h("div", { class: "errbox", role: "alert", text: r.error }) : chartsEl(r.data.charts) || h("p", { class: "note", text: "Không có số liệu cho lựa chọn này." }));
}

export function initTrends() {
  PERIODS.forEach(p => $("c-period").append(h("option", { value: p, text: p })));
  onPeriod(p => { if (p !== ALL) $("c-period").value = p; });
  fillMetrics($("c-m2"), CHART_METRICS, true);
  fillMetrics($("c-m3"), CHART_METRICS, true);
  syncControls();
  $("c-mode").onchange = syncControls;
  $("chart-form").onsubmit = draw;
}
