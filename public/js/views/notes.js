// Màn hình Thuyết minh & nguồn: tìm đoạn thuyết minh theo nội dung (cùng bộ truy xuất với trợ lý, không cần khóa Gemini) và xem đúng trang PDF dẫn chứng.
import { $, h } from "../dom.js";
import { ALL, NOTE_EXAMPLES } from "../config.js";
import { attempt, post } from "../api.js";
import { sourceActionsEl } from "../sources.js";
import { getPeriod, onPeriod } from "../state.js";

const KIND_LABEL = { van_ban: "Văn bản OCR, cần đối chiếu PDF", bang_so_lieu: "Bảng số liệu đã đối chiếu" };

function resultEl(x) {
  return h("article", { class: "note-card" },
    h("div", { class: "nc-h" }, h("strong", { text: `${x.period} · trang PDF ${x.page}` }), h("span", { class: "badge", text: KIND_LABEL[x.kind] || x.kind })),
    x.heading && x.heading !== "TM" ? h("div", { class: "nc-sec", text: x.heading }) : null,
    h("div", { class: "nc-text", text: x.text }),
    x.truncated ? h("p", { class: "note", text: "Đoạn dài đã được rút gọn; xem đầy đủ ở trang PDF." }) : null,
    sourceActionsEl(x.source),
    x.source.image ? null : h("p", { class: "note", text: `Chưa có ảnh trang ${x.page} trong dữ liệu; mở báo cáo gốc và xem trang PDF ${x.page}.` }));
}

async function search(query) {
  const out = $("notes-out");
  query = query.trim();
  if (query.length < 2) { out.replaceChildren(h("p", { class: "note", text: "Nhập ít nhất 2 ký tự để tìm." })); return; }
  out.replaceChildren(h("p", { class: "note", text: "Đang tìm… (lần đầu có thể mất vài giây)" }));
  const period = getPeriod();
  const r = await attempt(() => post("/api/notes", { query, period: period === ALL ? null : period, include_tables: $("notes-tables").checked, k: 8 }));
  if (r.error) { out.replaceChildren(h("div", { class: "errbox", role: "alert", text: r.error })); return; }
  const found = r.data.results;
  out.replaceChildren(...(found.length ? [h("p", { class: "note", text: `${found.length} đoạn phù hợp nhất, xếp theo độ liên quan.` }), ...found.map(resultEl)]
    : [h("p", { class: "note", text: "Không tìm thấy đoạn phù hợp. Bạn thử từ khóa khác, đổi kỳ ở thanh trên hoặc chọn \"Gồm cả bảng số liệu\"." })]));
}

export function initNotes() {
  NOTE_EXAMPLES.forEach(text => $("notes-chips").append(h("button", { class: "chip", type: "button", text, onclick: () => { $("notes-q").value = text; search(text); } })));
  onPeriod(p => { $("notes-scope").textContent = p === ALL ? "Đang tìm trong tất cả kỳ." : `Đang tìm trong kỳ ${p} (đổi ở góc phải thanh trên).`; });
  $("notes-form").onsubmit = e => { e.preventDefault(); search($("notes-q").value); };
}
