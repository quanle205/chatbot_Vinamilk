// Biểu đồ đường (Chart.js nạp trễ, ghim phiên bản + SRI) và bảng số liệu từ khối `charts` của API. Dùng ở Hỏi đáp và Xu hướng & so sánh.
import { h } from "./dom.js";
import { docName, signed, vn } from "./format.js";

const CHART_JS = { src: "https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js", integrity: "sha384-vsrfeLOOY6KuIYKDlmVH5UiBmgIdB1oEf7p01YgWHuqmOHfZr374+odEv96n9tNC" };
let loading = null;

function loadChartJs() {
  if (window.Chart) return Promise.resolve(window.Chart);
  loading = loading || new Promise((resolve, reject) => {
    const el = h("script", { src: CHART_JS.src, integrity: CHART_JS.integrity, crossorigin: "anonymous", referrerpolicy: "no-referrer" });
    el.onload = () => (window.Chart ? resolve(window.Chart) : reject(new Error("no Chart")));
    el.onerror = () => { loading = null; reject(new Error("load")); };
    document.head.appendChild(el);
  });
  return loading;
}
const cssVar = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function tableEl(b) {
  const kind = b.kind, unit = b.unit;
  const head = kind === "series" ? ["Kỳ", `Giá trị (${unit})`, "Nguồn"] : kind === "breakdown" ? ["Khoản mục", `Đóng góp (${unit})`] : ["Kỳ", `Giá trị (${unit})`];
  const foot = [];
  if (kind === "comparison" && b.change != null) foot.push(["Thay đổi", signed(b.change / b.scale) + (b.growth != null ? ` (${signed(b.growth * 100)}%)` : "")]);
  if (kind === "breakdown" && b.change != null) foot.push(["Tổng chênh lệch", signed(b.change / b.scale)]);
  return h("div", { class: "tbl" }, h("table", {},
    h("thead", {}, h("tr", {}, head.map((t, i) => h("th", { class: i === 1 ? "n" : null, scope: "col", text: t })))),
    h("tbody", {}, b.rows.map(r => h("tr", {},
      h("td", { text: r.label }),
      h("td", { class: "n", text: kind === "breakdown" ? signed(r.value / b.scale) : vn(r.value / b.scale) }),
      kind === "series" ? h("td", { text: r.source ? `${docName(r.source.doc)} · trang PDF ${r.source.page}` : "" }) : null))),
    foot.length ? h("tfoot", {}, foot.map(f => h("tr", {}, h("td", { text: f[0] }), h("td", { class: "n", text: f[1] })))) : null));
}

function summaryEl(b) {                           // một dòng nhận xét do máy chủ tính (cao nhất, thấp nhất, thay đổi đầu-cuối)
  const m = b.summary;
  if (!m) return null;
  const describe = x => `${x.label} (${vn(x.value / b.scale)} ${b.unit})`, bare = x => x.label.replace(/^tại /, "");
  return h("p", { class: "note", text: `Cao nhất: ${describe(m.max)}; thấp nhất: ${describe(m.min)}; từ ${bare(m.first)} đến ${bare(m.last)}: ${signed(m.change / b.scale)} ${b.unit}`
    + (m.growth != null ? ` (${signed(m.growth * 100)}%)` : "") + "." });
}

function drawLine(box, b, before) {
  const holder = h("div", { class: "cv" });
  const canvas = h("canvas", { role: "img", "aria-label": `Biểu đồ đường ${b.title}: ` + b.rows.map(r => `${r.label} ${vn(r.value / b.scale)} ${b.unit}`).join("; ") });
  holder.append(canvas); box.insertBefore(holder, before);
  loadChartJs().then(Chart => {
    const ink = cssVar("--ink"), mute = cssVar("--mute"), line = cssVar("--line");
    new Chart(canvas, { type: "line",
      data: { labels: b.rows.map(r => r.period || r.label), datasets: [{ label: b.unit, data: b.rows.map(r => +(r.value / b.scale).toFixed(1)),
        borderColor: ink, backgroundColor: ink, pointRadius: 4, pointHoverRadius: 6, borderWidth: 2, tension: 0 }] },      // tension 0: đường thẳng, không vẽ đoạn cong sai lệch số liệu
      options: { responsive: true, maintainAspectRatio: false, animation: false,
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => `${vn(c.parsed.y)} ${b.unit}` } } },
        scales: { x: { ticks: { color: mute }, grid: { display: false } },
                  y: { ticks: { color: mute, callback: v => vn(v, 0) }, grid: { color: line }, title: { display: true, text: b.unit, color: mute } } } } });
  }).catch(() => holder.replaceWith(h("p", { class: "note", text: "Không tải được thư viện vẽ biểu đồ; số liệu xem ở bảng bên dưới." })));
}

export function chartsEl(blocks) {
  if (!blocks || !blocks.length) return null;
  return h("div", { class: "charts" }, blocks.map(b => {
    const table = tableEl(b), box = h("div", { class: "chartbox" }, h("h3", { text: b.title }), summaryEl(b), table);
    if (b.chart && b.rows.length >= 2) drawLine(box, b, table);          // một kỳ thì không vẽ
    return box;
  }));
}
