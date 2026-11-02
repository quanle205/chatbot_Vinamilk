// Màn hình Trò chuyện: hội thoại lưu trong localStorage, gửi câu hỏi tới /api/ask, hiển thị câu trả lời kèm nguồn, biểu đồ, phản hồi.
import { ALL, KEY, SUGGESTIONS } from "./config.js";
import { $, h, icon } from "./dom.js";
import { NETWORK_ERROR, errorText, post } from "./api.js";
import { chartsEl } from "./charts.js";
import { markdown } from "./markdown.js";
import { sourcesEl } from "./sources.js";
import { getPeriod, onPeriod } from "./state.js";
import { store } from "./storage.js";
import { periodLabel } from "./format.js";

const MAX_CONVERSATIONS = 40;
const MAX_HISTORY_MESSAGES = 12;          // 6 lượt hỏi-đáp gửi kèm mỗi câu hỏi (máy chủ cũng giới hạn)
const NEW_TITLE = "Cuộc trò chuyện mới";

let ui;                                   // {showView, closeSide, refreshTitle, unavailable}: do main.js truyền vào để không phụ thuộc vòng
let convs = [], cur = null, busy = false, ctrl = null;
const input = () => $("q");

const uid = () => (crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2));
export const currentTitle = () => (cur ? cur.title : NEW_TITLE);

function persist() {
  convs.sort((a, b) => b.updated - a.updated);
  convs = convs.slice(0, MAX_CONVERSATIONS);
  while (!store.set(KEY.convs, convs) && convs.length > 1) convs.pop();         // đầy bộ nhớ trình duyệt: bỏ cuộc cũ nhất
  store.set(KEY.active, cur ? cur.id : null);
}

// ------------------------------------------------------------------ hiển thị tin nhắn
function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
  return new Promise((resolve, reject) => {
    const box = h("textarea", { class: "sr", "aria-hidden": "true" }); box.value = text; document.body.append(box); box.select();
    try { document.execCommand("copy") ? resolve() : reject(); } catch (e) { reject(e); } finally { box.remove(); }
  });
}

async function sendFeedback(bar, msg, label) {
  const buttons = bar.querySelectorAll(".fb"), note = bar.querySelector(".thanks");
  buttons.forEach(b => (b.disabled = true));
  try {
    const r = await post("/api/feedback", { question: msg.question.slice(0, 500), answer: msg.text.slice(0, 8000), label, timestamp: new Date().toISOString() });
    if (!r.ok) throw new Error("feedback");
    note.textContent = "Cảm ơn bạn đã phản hồi.";
  } catch (_) {
    buttons.forEach(b => (b.disabled = false));
    note.textContent = "Chưa gửi được phản hồi, bạn bấm lại nhé.";
  }
}

function actionBar(msg, isLast) {
  const copy = h("button", { class: "act", type: "button", title: "Sao chép câu trả lời" }, icon("copy"), "Sao chép");
  copy.onclick = () => copyText(msg.text).then(() => {
    copy.replaceChildren(icon("check"), "Đã sao chép");
    setTimeout(() => copy.replaceChildren(icon("copy"), "Sao chép"), 1500);
  }).catch(() => {});
  const bar = h("div", { class: "actions" }, copy,
    isLast ? h("button", { class: "act", type: "button", title: "Tạo lại câu trả lời", onclick: () => retry(msg) }, icon("redo"), "Tạo lại") : null,
    h("button", { class: "act icon-only fb", type: "button", "aria-label": "Câu trả lời hữu ích", title: "Hữu ích", onclick: () => sendFeedback(bar, msg, "up") }, icon("thumb-up")),
    h("button", { class: "act icon-only fb", type: "button", "aria-label": "Câu trả lời chưa hữu ích", title: "Chưa hữu ích", onclick: () => sendFeedback(bar, msg, "down") }, icon("thumb-down")),
    h("span", { class: "thanks", "aria-live": "polite" }));
  return bar;
}

function botEl(msg, isLast) {
  const wrap = h("div", { class: "msg bot" });
  if (msg.pending) {
    wrap.append(h("div", { class: "typing", role: "status" }, "Đang tra cứu", h("i"), h("i"), h("i")));
    return wrap;
  }
  if (msg.error) {
    wrap.append(h("div", { class: "errbox", role: "alert" }, h("div", { text: msg.error }),
      h("button", { class: "btn", type: "button", onclick: () => retry(msg) }, icon("redo"), "Thử lại")));
    return wrap;
  }
  const unsupported = msg.unsupported || [];
  return h("div", { class: "msg bot" }, markdown(msg.text),
    unsupported.length ? h("div", { class: "warn", role: "note" }, "Các số sau trong câu trả lời ", h("strong", { text: "không khớp" }), ` kết quả tra cứu, hãy kiểm tra lại: ${unsupported.join(", ")}`) : null,
    (msg.warnings || []).map(w => h("div", { class: "warn", role: "note", text: w })),
    chartsEl(msg.charts), sourcesEl(msg.sources, msg.notes), actionBar(msg, isLast));
}

function msgEl(msg, i) {
  return msg.role === "user" ? h("div", { class: "msg user" }, h("div", { class: "bubble", text: msg.text })) : botEl(msg, i === cur.msgs.length - 1);
}

function renderConv() {
  const log = $("log"); log.replaceChildren();
  $("welcome").hidden = !!(cur && cur.msgs.length);
  if (cur) cur.msgs.forEach((m, i) => log.append(msgEl(m, i)));
  ui.refreshTitle();
  const scroller = $("scroll"); scroller.scrollTop = scroller.scrollHeight;
}

// ------------------------------------------------------------------ gửi câu hỏi
// /api/ask chưa nhận tham số kỳ nên kỳ đang chọn được thêm vào câu hỏi như gợi ý ngữ cảnh; lịch sử và hiển thị vẫn dùng câu hỏi gốc.
const withPeriod = q => (getPeriod() === ALL ? q : `${q}\n(Nếu không nêu kỳ, hiểu là kỳ ${getPeriod()}.)`);

function historyBefore(index) {                         // các cặp hỏi-đáp văn bản đã hoàn tất, đứng trước câu hỏi đang gửi
  const out = [];
  for (let i = 0; i < index - 1; i++) {
    const q = cur.msgs[i], a = cur.msgs[i + 1];
    if (q.role === "user" && a && a.role === "bot" && a.text && !a.error) out.push({ role: "user", text: q.text.slice(0, 4000) }, { role: "model", text: a.text.slice(0, 4000) });
  }
  return out.slice(-MAX_HISTORY_MESSAGES);
}

function chatError(status, data) {
  if (status === 422) return "Câu hỏi chưa hợp lệ (tối đa 500 ký tự). Bạn rút gọn rồi thử lại nhé.";
  if (status === 503) return "Trợ lý chưa sẵn sàng (có thể thiếu khóa Gemini). Bạn vẫn có thể dùng thẻ Tra cứu hoặc Thuyết minh.";
  return errorText(status, data);
}

function setBusy(on) {
  busy = on;
  const send = $("send");
  send.replaceChildren(icon(on ? "stop" : "up"));
  send.setAttribute("aria-label", on ? "Dừng trả lời" : "Gửi câu hỏi");
  send.disabled = on ? false : !input().value.trim();
}

async function ask(question, regenerate = false) {
  question = question.trim();
  if (busy || !question) return;
  if (!cur) {
    cur = { id: uid(), title: question.length > 40 ? question.slice(0, 40).trim() + "…" : question, updated: Date.now(), msgs: [] };
    convs.unshift(cur);
  }
  if (!regenerate) cur.msgs.push({ role: "user", text: question });
  const bot = { role: "bot", pending: true, question };
  cur.msgs.push(bot);
  cur.updated = Date.now();
  renderConv(); renderRecent(); setBusy(true);
  ctrl = new AbortController();
  try {
    const r = await post("/api/ask", { question: withPeriod(question), history: historyBefore(cur.msgs.length - 1) }, ctrl.signal);
    if (!r.ok) throw Object.assign(new Error(chatError(r.status, r.data)), { http: r.status });
    delete bot.pending;
    Object.assign(bot, { text: r.data.answer, sources: r.data.sources || [], notes: r.data.notes || [], charts: r.data.charts || [],
      warnings: r.data.warnings || [], unsupported: r.data.unsupported_numbers || [] });
  } catch (e) {
    delete bot.pending;
    bot.error = e.name === "AbortError" ? "Đã dừng trả lời." : e.http ? e.message : NETWORK_ERROR;
    if (e.http === 503) ui.unavailable();
  } finally {
    ctrl = null; cur.updated = Date.now(); persist(); setBusy(false); renderConv(); renderRecent();
  }
}

function retry(msg) {                                   // bỏ câu trả lời cũ rồi hỏi lại đúng câu hỏi đó
  const i = cur ? cur.msgs.indexOf(msg) : -1;
  if (busy || i < 0) return;
  cur.msgs.splice(i, 1);
  ask(msg.question, true);
}

// ------------------------------------------------------------------ hộp "Gần đây": các cuộc trò chuyện đã lưu
function renderRecent() {
  const list = $("recent"); list.replaceChildren();
  if (!convs.length) { list.append(h("li", { class: "recent-empty", text: "Chưa có cuộc trò chuyện nào" })); return; }
  [...convs].sort((a, b) => b.updated - a.updated).forEach(c => {
    const active = cur && cur.id === c.id;
    const li = h("li", { class: "conv" + (active ? " active" : "") });
    const del = h("button", { class: "conv-act", type: "button", "aria-label": `Xóa cuộc trò chuyện ${c.title}`, title: "Xóa" }, icon("trash"));
    let timer = null;
    del.onclick = () => {                               // hai bước, không dùng confirm() của trình duyệt
      if (!del.classList.contains("confirm")) {
        del.classList.add("confirm"); del.textContent = "Xóa?"; del.setAttribute("aria-label", "Bấm lần nữa để xóa");
        timer = setTimeout(renderRecent, 3000); return;
      }
      clearTimeout(timer); removeConv(c);
    };
    li.append(h("button", { class: "conv-title", type: "button", text: c.title, title: c.title, onclick: () => openConv(c), "aria-current": active ? "true" : null }),
      h("button", { class: "conv-act", type: "button", "aria-label": `Đổi tên cuộc trò chuyện ${c.title}`, title: "Đổi tên", onclick: () => startRename(li, c) }, icon("edit")), del);
    list.append(li);
  });
}

function startRename(li, c) {
  const box = h("input", { type: "text", value: c.title, maxlength: "80", "aria-label": "Tên cuộc trò chuyện" });
  let done = false;
  const finish = save => {
    if (done) return; done = true;
    const title = box.value.trim();
    if (save && title) { c.title = title; persist(); ui.refreshTitle(); }
    renderRecent();
  };
  box.onkeydown = e => { if (e.key === "Enter") finish(true); else if (e.key === "Escape") finish(false); };
  box.onblur = () => finish(true);
  li.replaceChildren(box); box.focus(); box.select();
}

function removeConv(c) {
  convs = convs.filter(x => x !== c);
  if (cur === c) { cur = null; renderConv(); }
  persist(); renderRecent();
}

export function openConv(c) { if (busy) return; cur = c; persist(); ui.showView("chat"); renderConv(); renderRecent(); ui.closeSide(); }
export function newChat() { if (busy) return; cur = null; persist(); ui.showView("chat"); renderConv(); renderRecent(); ui.closeSide(); input().focus(); }

// ------------------------------------------------------------------ khởi tạo
function autosize() {
  const box = input();
  box.style.height = "auto"; box.style.height = Math.min(box.scrollHeight, 160) + "px";
  if (!busy) $("send").disabled = !box.value.trim();
}

export function initChat(hooks) {
  ui = hooks;
  convs = store.get(KEY.convs, []).filter(c => c && Array.isArray(c.msgs));
  cur = convs.find(c => c.id === store.get(KEY.active, null)) || null;
  convs.forEach(c => c.msgs.forEach(m => { if (m.pending) { delete m.pending; m.error = "Phiên trước bị ngắt giữa chừng."; } }));

  SUGGESTIONS.forEach(([tag, text]) => $("cards").append(
    h("button", { class: "card-btn", type: "button", onclick: () => ask(text) }, h("span", { class: "tag", text: tag }), h("span", { text }))));
  onPeriod(p => {
    $("desc-period").textContent = periodLabel(p);
    $("ctx").textContent = (p === ALL ? "Tất cả kỳ" : `Kỳ ${p}`) + " · Báo cáo hợp nhất · Tool + RAG";
  });

  input().addEventListener("input", autosize);
  input().addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229) { e.preventDefault(); $("composer").requestSubmit(); }   // không gửi khi đang gõ dấu tiếng Việt
  });
  $("composer").onsubmit = e => {
    e.preventDefault();
    if (busy) { if (ctrl) ctrl.abort(); return; }
    const text = input().value; input().value = ""; autosize(); ask(text);
  };
  renderConv(); renderRecent();
}
