import { attempt, get } from "./api.js";
import { h } from "./dom.js";

let request;
export function companyCatalog() {
  request ??= get("/api/consumer/catalog", { cache: "no-store" }).then(response => {
    if (!response.ok || !response.data.comparison_limit) request = null;
    return response;
  }).catch(error => {
    request = null;
    throw error;
  });
  return request;
}

export async function loadCompanyOptions(status, apply) {
  status.hidden = false;
  status.textContent = "Đang tải doanh nghiệp…";
  const response = await attempt(companyCatalog);
  if (response.error || !response.data.comparison_limit) {
    status.replaceChildren(response.error ? "Không tải được danh mục doanh nghiệp. " :
      "Máy chủ đang dùng phiên bản cũ. Cập nhật hoặc khởi động lại chatbot. ",
      h("button", { type: "button", class: "btn", text: "Thử lại", onclick: () => loadCompanyOptions(status, apply) }));
    return;
  }
  status.hidden = true;
  apply(response.data);
}

export function selectedPeers(details) {
  return [...details.querySelectorAll("input:checked:not(:disabled)")].map(input => input.value);
}

export function fillPeers(details, companies, onChange) {
  const summary = details.querySelector("summary"), options = details.querySelector(".company-options");
  const sync = () => {
    const count = selectedPeers(details).length;
    summary.textContent = count ? `So sánh với ${count} doanh nghiệp` : "Chọn thêm doanh nghiệp";
    onChange();
  };
  options.replaceChildren(...Object.entries(companies).map(([code, name]) =>
    h("label", {}, h("input", { type: "checkbox", value: code, onchange: sync }), `${name} (${code})`)));
  return code => {
    for (const input of options.querySelectorAll("input")) input.disabled = input.value === code;
    sync();
  };
}

export function commonPeriods(catalog, companies) {
  return Object.keys(catalog.periods).filter(period => companies.every(code => catalog.available[code].includes(period)));
}

export function setOptions(select, values, fallback) {
  const keep = select.value;
  select.replaceChildren(...Object.entries(values).map(([value, text]) => h("option", { value, text })));
  if (Object.hasOwn(values, keep)) select.value = keep;
  else if (Object.hasOwn(values, fallback)) select.value = fallback;
}
