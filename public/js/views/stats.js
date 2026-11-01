// Màn hình Thống kê: độ phủ dữ liệu của chatbot (kỳ, chỉ tiêu, đoạn thuyết minh, trang PDF dẫn chứng) từ /api/stats. Số đếm lấy từ dữ liệu thật, không nhập tay.
import { $, h } from "../dom.js";
import { STATEMENTS } from "../config.js";
import { attempt, get } from "../api.js";
import { vn } from "../format.js";

let cached = null;
// Trả {data} hoặc {error}; chỉ lưu đệm khi thành công để lần sau còn thử lại được. Dùng chung với hàng số liệu ở màn hình chào.
export async function getStats() {
  if (cached) return { data: cached };
  const r = await attempt(() => get("/api/stats"));
  if (r.data) cached = r.data;
  return r;
}

const card = (value, label) => h("div", { class: "stat-card" }, h("div", { class: "stat-v", text: vn(value, 0) }), h("div", { class: "stat-l", text: label }));

function periodsTable(d) {
  const head = ["Kỳ", "Chuẩn mực kế toán", "Chỉ tiêu có số liệu", "Đoạn thuyết minh", "Trang PDF dẫn chứng", "Báo cáo gốc"];
  return h("div", { class: "tbl" }, h("table", {},
    h("caption", { class: "sr", text: "Độ phủ dữ liệu theo kỳ báo cáo" }),
    h("thead", {}, h("tr", {}, head.map((t, i) => h("th", { scope: "col", class: i >= 2 && i <= 4 ? "n" : null, text: t })))),
    h("tbody", {}, d.periods.map(p => h("tr", {},
      h("td", { text: p.period }), h("td", { text: p.standard }),
      h("td", { class: "n", text: `${p.metrics}/${d.totals.metrics_defined}` }), h("td", { class: "n", text: vn(p.chunks, 0) }), h("td", { class: "n", text: vn(p.page_images, 0) }),
      h("td", {}, h("a", { href: p.pdf_url || d.official_url, target: "_blank", rel: "noopener noreferrer", text: p.pdf_url ? "Mở PDF" : "Trang báo cáo Vinamilk" })))))));
}

function matrix(d) {
  const groups = Object.keys(STATEMENTS).map(st => [st, d.metrics.filter(m => m.statement === st)]).filter(([, rows]) => rows.length);
  return h("div", { class: "tbl matrix" }, h("table", {},
    h("caption", { class: "sr", text: "Chỉ tiêu có số liệu theo kỳ" }),
    h("thead", {}, h("tr", {}, h("th", { scope: "col", text: "Chỉ tiêu" }), d.periods.map(p => h("th", { scope: "col", class: "n", text: p.period })))),
    groups.map(([st, rows]) => h("tbody", {},
      h("tr", { class: "grp" }, h("th", { colspan: String(d.periods.length + 1), scope: "colgroup", text: STATEMENTS[st] })),
      rows.map(m => h("tr", {}, h("th", { scope: "row", text: m.name }),
        m.have.map(ok => h("td", { class: "n " + (ok ? "yes" : "no"), "aria-label": ok ? "Có số liệu" : "Không có số liệu", text: ok ? "●" : "–" }))))))));
}

export async function showStats() {
  const out = $("stats-out");
  if (!cached) out.replaceChildren(h("p", { class: "note", text: "Đang tải thống kê…" }));
  const r = await getStats();
  if (r.error) { out.replaceChildren(h("div", { class: "errbox", role: "alert", text: r.error })); return; }
  const d = r.data, t = d.totals;
  out.replaceChildren(
    h("div", { class: "stat-cards" }, card(t.periods, "kỳ báo cáo"), card(t.metrics, "chỉ tiêu có số liệu"), card(t.chunks, "đoạn văn bản và bảng đã lập chỉ mục"), card(t.page_images, "trang PDF có ảnh dẫn chứng")),
    h("h3", { class: "sec-title", text: "Theo kỳ báo cáo" }), periodsTable(d),
    h("h3", { class: "sec-title", text: "Chỉ tiêu có số liệu theo kỳ" }),
    h("p", { class: "note", text: `● có số liệu trong báo cáo của kỳ đó; – không có. Tổng ${vn(t.cells, 0)} ô số liệu đã đối chiếu với PDF.` }), matrix(d));
}
