// Nguồn dẫn chứng: tên báo cáo, trang PDF, liên kết PDF chính thức và ảnh trang có khung đỏ quanh dòng được trích. Dùng ở Hỏi đáp và Thuyết minh & nguồn.
import { STATEMENTS } from "./config.js";
import { h, icon } from "./dom.js";
import { docName } from "./format.js";

const safeImage = src => (typeof src === "string" && /^\/pages\/[\w-]+\/\d+\.webp$/.test(src) ? src : null);
const safeUrl = url => (typeof url === "string" && /^https:\/\//.test(url) ? url : null);

export function sourceTitle(s) {
  return `${docName(s.doc)} · ${STATEMENTS[s.statement] || s.statement || "Thuyết minh"} · trang PDF ${s.page != null ? s.page : "không rõ"}`;
}

// Tiêu đề nguồn; "trang PDF N" là liên kết tới bằng chứng (PDF chính thức tại đúng trang, nếu không có thì ảnh trang).
function titleEl(s) {
  const link = safeUrl(s.is_pdf ? s.url : null) || safeImage(s.image);
  if (!link) return h("div", { class: "src-h", text: sourceTitle(s) });
  const base = `${docName(s.doc)} · ${STATEMENTS[s.statement] || s.statement || "Thuyết minh"} · `;
  return h("div", { class: "src-h" }, base, h("a", { href: link, target: "_blank", rel: "noopener noreferrer", title: "Mở bằng chứng" }, `trang PDF ${s.page != null ? s.page : "không rõ"}`));
}

// Liên kết mở PDF và ảnh trang dẫn chứng của một nguồn (không gồm tiêu đề).
export function sourceActionsEl(s) {
  const page = s.page != null ? s.page : "không rõ", img = safeImage(s.image), url = safeUrl(s.url);
  const boxes = (s.boxes || []).filter(b => Array.isArray(b) && b.length === 4 && b.every(Number.isFinite));
  return h("div", { class: "src-actions" },
    url ? h("div", { class: "src-links" }, h("a", { href: url, target: "_blank", rel: "noopener noreferrer" }, s.is_pdf ? `Mở PDF chính thức tại trang ${page}` : "Mở trang báo cáo Vinamilk", " ", icon("ext"))) : null,
    img ? h("details", { class: "pgd" }, h("summary", { text: "Xem trang PDF dẫn chứng" }),
      h("a", { class: "pg", href: img, target: "_blank", rel: "noopener noreferrer", "aria-label": `Mở ảnh trang ${page} của ${docName(s.doc)} trong tab mới` },
        h("img", { src: img, loading: "lazy", alt: `Trang ${page} của báo cáo ${docName(s.doc)}${boxes.length ? ", dòng được trích dẫn có khung đỏ" : ""}` }),
        boxes.map(b => h("span", { class: "hl", style: `left:${b[0] * 100}%;top:${b[1] * 100}%;width:${b[2] * 100}%;height:${b[3] * 100}%` })))) : null,
    !img && s.excerpt ? h("details", { class: "pgd" }, h("summary", { text: `Xem trích đoạn trang ${page} (văn bản OCR)` }),
      h("pre", { class: "excerpt", text: s.excerpt }),
      h("div", { class: "src-rows", text: "Trang này chưa có ảnh; đây là văn bản OCR của đúng trang được dẫn, cần đối chiếu PDF." })) : null);
}

// Thẻ "Nguồn" thu gọn dưới câu trả lời, kèm các lưu ý của công cụ (số suy ra, số đã phân loại lại, số đã sửa OCR).
export function sourcesEl(list, notes) {
  list = list || []; notes = notes || [];
  if (!list.length && !notes.length) return null;
  const items = list.map(s => h("li", {}, titleEl(s),
    s.rows && s.rows.length ? h("div", { class: "src-rows", text: s.rows.join("; ") }) : null, sourceActionsEl(s)));
  return h("details", { class: "srcs" },
    h("summary", {}, icon("file"), `Nguồn · ${list.length}` + (notes.length ? ` · ${notes.length} ghi chú` : "")),
    notes.length ? h("div", { class: "src-notes" }, h("strong", { text: "Ghi chú" }), h("ul", {}, notes.map(n => h("li", { text: n })))) : null,
    h("ul", {}, items));
}
