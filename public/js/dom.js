// Dựng DOM an toàn: văn bản luôn đi qua textContent/createTextNode, không dùng innerHTML với nội dung từ máy chủ hay mô hình.
export const $ = id => document.getElementById(id);

export function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat()) if (c != null && c !== false) e.append(c.nodeType ? c : document.createTextNode(String(c)));
  return e;
}

const SVG = "http://www.w3.org/2000/svg";
export function icon(name) {                       // biểu tượng lấy từ sprite <symbol id="i-..."> trong index.html
  const s = document.createElementNS(SVG, "svg"), u = document.createElementNS(SVG, "use");
  s.setAttribute("class", "ic"); s.setAttribute("aria-hidden", "true"); u.setAttribute("href", "#i-" + name); s.append(u);
  return s;
}
