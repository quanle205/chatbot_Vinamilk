// Markdown an toàn cho câu trả lời: đoạn, tiêu đề, danh sách, in đậm, nghiêng, mã, bảng. Dựng bằng DOM nên thẻ HTML trong văn bản chỉ hiện như chữ.
import { h } from "./dom.js";

const BULLET = /^\s*([-*•])\s+(.*)$/, NUMBERED = /^\s*\d+[.)]\s+(.*)$/, HEADING = /^\s{0,3}#{1,6}\s+(.*)$/;

function inline(text) {
  const frag = document.createDocumentFragment(), re = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) frag.append(text.slice(last, m.index));
    const t = m[0];
    frag.append(t.startsWith("**") ? h("strong", { text: t.slice(2, -2) }) : t[0] === "`" ? h("code", { text: t.slice(1, -1) }) : h("em", { text: t.slice(1, -1) }));
    last = m.index + t.length;
  }
  if (last < text.length) frag.append(text.slice(last));
  return frag;
}

const isSeparator = s => s.includes("|") && s.includes("-") && /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(s);
function cells(line) {
  let t = line.trim();
  if (t.startsWith("|")) t = t.slice(1);
  if (t.endsWith("|")) t = t.slice(0, -1);
  return t.split("|").map(c => c.trim());
}

export function markdown(src) {
  const root = h("div", { class: "md" }), lines = String(src).replace(/\r\n?/g, "\n").split("\n");
  const startsTable = i => lines[i].includes("|") && i + 1 < lines.length && isSeparator(lines[i + 1]);
  let i = 0, m;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    if ((m = line.match(HEADING))) { root.append(h("h4", {}, inline(m[1].replace(/#+\s*$/, "")))); i++; continue; }
    if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) { root.append(h("hr")); i++; continue; }
    if (startsTable(i)) {
      const head = cells(line), rows = []; i += 2;
      while (i < lines.length && lines[i].trim() && lines[i].includes("|")) rows.push(cells(lines[i++]));
      root.append(h("div", { class: "md-tbl" }, h("table", {},
        h("thead", {}, h("tr", {}, head.map(c => h("th", { scope: "col" }, inline(c))))),
        h("tbody", {}, rows.map(r => h("tr", {}, r.map(c => h("td", {}, inline(c)))))))));
      continue;
    }
    if (BULLET.test(line)) { const ul = h("ul"); while (i < lines.length && (m = lines[i].match(BULLET))) { ul.append(h("li", {}, inline(m[2]))); i++; } root.append(ul); continue; }
    if (NUMBERED.test(line)) { const ol = h("ol"); while (i < lines.length && (m = lines[i].match(NUMBERED))) { ol.append(h("li", {}, inline(m[1]))); i++; } root.append(ol); continue; }
    const p = h("p"), start = i;
    while (i < lines.length && lines[i].trim() && !HEADING.test(lines[i]) && !BULLET.test(lines[i]) && !NUMBERED.test(lines[i]) && !startsTable(i)) {
      if (i > start) p.append(h("br"));
      p.append(inline(lines[i].trim())); i++;
    }
    if (i === start) { p.append(lines[i]); i++; }               // bảo đảm luôn tiến lên, không lặp vô hạn
    root.append(p);
  }
  return root;
}
