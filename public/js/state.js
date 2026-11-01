// Kỳ báo cáo đang chọn ở thanh trên: một nguồn duy nhất, các màn hình đăng ký để cập nhật khi đổi.
import { ALL, KEY, PERIODS } from "./config.js";
import { store } from "./storage.js";

let period = store.get(KEY.period, PERIODS[0]);
if (period !== ALL && !PERIODS.includes(period)) period = PERIODS[0];
const listeners = [];

export const getPeriod = () => period;
export function setPeriod(p) { period = p; store.set(KEY.period, p); listeners.forEach(fn => fn(p)); }
export function onPeriod(fn) { listeners.push(fn); fn(period); }          // gọi ngay một lần với kỳ hiện tại
