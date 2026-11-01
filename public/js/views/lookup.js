// Màn hình Tra cứu số liệu: một chỉ tiêu, một kỳ, đọc thẳng từ /api/lookup (không qua trợ lý, không cần khóa Gemini).
import { $, h } from "../dom.js";
import { ALL, PERIODS } from "../config.js";
import { attempt, post } from "../api.js";
import { onPeriod } from "../state.js";

export function initLookup() {
  PERIODS.forEach(p => $("lk-period").append(h("option", { value: p, text: p })));
  onPeriod(p => { if (p !== ALL) $("lk-period").value = p; });            // theo kỳ đang chọn ở thanh trên

  $("lookup-form").onsubmit = async e => {
    e.preventDefault();
    const out = $("lk-out");
    out.textContent = "Đang tra…";
    const r = await attempt(() => post("/api/lookup", { metric: $("lk-metric").value, period: $("lk-period").value, basis: $("lk-basis").value }));
    out.textContent = r.error || r.data.text || "Không có số liệu.";
  };
}
