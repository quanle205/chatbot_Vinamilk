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

// Ô chọn doanh nghiệp: mỗi doanh nghiệp một nút bấm (tên + mã); dòng tóm tắt ghi rõ TÊN các doanh nghiệp đã chọn.
export function companyPill(code, name, attrs = {}) {
  return h("label", { class: "pill" }, h("input", { type: "checkbox", value: code, ...attrs }), h("span", { class: "pn", text: name }), h("small", { text: code }));
}

export function fillPeers(details, companies, onChange) {
  const summary = details.querySelector("summary"), options = details.querySelector(".company-options");
  const inputs = () => [...options.querySelectorAll("input")];
  const sync = () => {
    const names = selectedPeers(details).map(code => companies[code]);
    summary.textContent = !names.length ? "Chọn thêm doanh nghiệp để so sánh"
      : `So sánh với: ${names.length <= 3 ? names.join(", ") : `${names.slice(0, 3).join(", ")} và ${names.length - 3} doanh nghiệp khác`}`;
    summary.title = names.join(", ");
    details.classList.toggle("has-value", names.length > 0);
    onChange();
  };
  const setAll = on => { inputs().forEach(input => { if (!input.disabled) input.checked = on; }); sync(); };
  options.replaceChildren(
    h("div", { class: "company-actions" },
      h("button", { type: "button", class: "btn", text: "Chọn tất cả", onclick: () => setAll(true) }),
      h("button", { type: "button", class: "btn", text: "Bỏ chọn", onclick: () => setAll(false) })),
    h("div", { class: "pill-grid" }, Object.entries(companies).map(([code, name]) => companyPill(code, name, { onchange: sync }))));
  return code => {
    for (const input of inputs()) {
      input.disabled = input.value === code;
      if (input.disabled) input.checked = false;
      input.closest("label").classList.toggle("is-base", input.disabled);
    }
    sync();
  };
}

// Kỳ báo cáo của nhóm doanh nghiệp: kỳ mà ÍT NHẤT MỘT doanh nghiệp có báo cáo (doanh nghiệp thiếu kỳ đó hiện "Chưa có số"), không loại kỳ chỉ vì một doanh nghiệp chưa có.
export function anyPeriods(catalog, companies) {
  return Object.keys(catalog.periods).filter(period => companies.some(code => catalog.available[code].includes(period)));
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

// Như setOptions nhưng mỗi mục là {value, text, disabled}: kỳ chưa chọn được vẫn hiện (làm mờ, nêu lý do) thay vì biến mất.
export function setChoices(select, items, fallback) {
  const keep = select.value;
  select.replaceChildren(...items.map(i => h("option", { value: i.value, text: i.text, disabled: i.disabled })));
  const ok = v => items.some(i => i.value === v && !i.disabled);
  select.value = ok(keep) ? keep : ok(fallback) ? fallback : (items.find(i => !i.disabled)?.value ?? "");
}
