import { attempt, post } from "../api.js";
import { companyCatalog } from "../company-catalog.js";
import { $, h } from "../dom.js";
import { markdown } from "../markdown.js";
import { sourcesEl } from "../sources.js";

export async function initConsumer() {
  const form = $("consumer-form"), button = form.querySelector("button"), out = $("consumer-out");
  if (form.dataset.ready) return;
  form.dataset.ready = "loading";
  const response = await attempt(companyCatalog);
  if (response.error) {
    delete form.dataset.ready;
    out.textContent = response.error;
    return;
  }
  const { companies, periods, metrics, available } = response.data;
  const options = values => Object.entries(values).map(([value, text]) => h("option", { value, text }));
  $("consumer-primary").replaceChildren(...options(companies));
  $("consumer-secondary").replaceChildren(...options({ "": "Không so sánh", ...companies }));
  $("consumer-period").replaceChildren(...options(periods));
  $("consumer-metric").replaceChildren(...options(metrics));
  let pending = false;
  const syncControls = () => {
    const selected = $("consumer-primary").value, secondary = $("consumer-secondary");
    if (secondary.value === selected) secondary.value = "";
    for (const option of secondary.options) option.disabled = option.value === selected;
    const period = $("consumer-period");
    const supported = (available[selected] || []).filter(p => !secondary.value || available[secondary.value]?.includes(p));
    for (const option of period.options) option.disabled = !supported.includes(option.value);
    if (!supported.includes(period.value)) {
      period.value = [...period.options].reverse().find(option => !option.disabled)?.value || "";
    }
    $("consumer-basis").disabled = period.value.startsWith("FY");
    button.disabled = pending || !period.value;
  };
  $("consumer-primary").onchange = $("consumer-secondary").onchange = $("consumer-period").onchange = syncControls;
  $("consumer-period").value = "";
  form.dataset.ready = "yes";
  syncControls();
  form.onsubmit = async event => {
    event.preventDefault();
    if (pending) return;
    pending = true;
    button.disabled = true;
    out.textContent = "Đang tra cứu…";
    try {
      const response = await attempt(() => post("/api/consumer/lookup", {
        companies: [$("consumer-primary").value, $("consumer-secondary").value].filter(Boolean),
        period: $("consumer-period").value,
        metric: $("consumer-metric").value,
        basis: $("consumer-basis").value,
      }));
      if (response.error) { out.textContent = response.error; return; }
      const { answer, sources, notes } = response.data;
      out.replaceChildren(markdown(answer));
      const evidence = sourcesEl(sources, notes);
      if (evidence) out.append(evidence);
    } finally {
      pending = false;
      syncControls();
    }
  };
}
