// Màn hình Tra cứu số liệu: một chỉ tiêu, một kỳ cho một hoặc nhiều doanh nghiệp (Vinamilk và 11 công ty hàng tiêu dùng).
// Đọc thẳng /api/consumer/lookup (không qua trợ lý, không cần khóa Gemini); kết quả kèm nguồn trang PDF.
import { $ } from "../dom.js";
import { ALL } from "../config.js";
import { attempt, post } from "../api.js";
import { anyPeriods, commonPeriods, fillPeers, loadCompanyOptions, selectedPeers, setOptions } from "../company-catalog.js";
import { markdown } from "../markdown.js";
import { sourcesEl } from "../sources.js";
import { onPeriod } from "../state.js";

let catalog = null, syncPeers = () => {}, pending = false;
const companies = () => [$("lk-company").value, ...selectedPeers($("lk-peers"))];

function syncControls() {
  const button = $("lookup-form").querySelector("button[type=submit]"), note = $("lk-note");
  if (!catalog) { button.disabled = true; return; }
  const chosen = companies(), periods = anyPeriods(catalog, chosen);
  setOptions($("lk-period"), Object.fromEntries(periods.map(p => [p, catalog.periods[p]])), commonPeriods(catalog, chosen).at(-1) ?? periods.at(-1));
  const period = $("lk-period").value, lacking = chosen.filter(code => !catalog.available[code].includes(period)).map(code => catalog.companies[code]);
  $("lk-basis").disabled = period.startsWith("FY");
  note.hidden = !lacking.length;
  note.textContent = lacking.length ? `Chưa có báo cáo ${catalog.periods[period]} của ${lacking.join(", ")}; các doanh nghiệp này sẽ hiện "Chưa có số". Đổi kỳ để so sánh đủ.` : "";
  button.disabled = pending || !periods.length;
}

async function submit(event) {
  event.preventDefault();
  if (pending || !catalog) return;
  pending = true; syncControls();
  const out = $("lk-out");
  out.textContent = "Đang tra…";
  try {
    const r = await attempt(() => post("/api/consumer/lookup", {
      companies: companies(), period: $("lk-period").value, metric: $("lk-metric").value, basis: $("lk-basis").value }));
    if (r.error) { out.textContent = r.error; return; }
    out.replaceChildren(markdown(r.data.answer || "Không có số liệu."));
    const evidence = sourcesEl(r.data.sources, r.data.notes);
    if (evidence) out.append(evidence);
  } finally {
    pending = false; syncControls();
  }
}

export function initLookup() {
  onPeriod(p => { if (p !== ALL && [...$("lk-period").options].some(o => o.value === p)) $("lk-period").value = p; });   // theo kỳ đang chọn ở thanh trên
  $("lk-company").onchange = () => { syncPeers($("lk-company").value); syncControls(); };
  $("lk-period").onchange = syncControls;
  $("lookup-form").onsubmit = submit;
  syncControls();
  loadCompanyOptions($("lk-company-status"), data => {
    catalog = data;
    setOptions($("lk-company"), catalog.companies, "VNM");
    setOptions($("lk-metric"), catalog.metrics, "doanh_thu_thuan");
    $("lk-company").disabled = false;
    syncPeers = fillPeers($("lk-peers"), catalog.companies, syncControls);
    syncPeers($("lk-company").value);
    syncControls();
  });
}
