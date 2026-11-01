// Định dạng số và nhãn theo kiểu Việt Nam (dấu chấm nghìn, dấu phẩy thập phân), khớp với phía máy chủ.
import { ALL } from "./config.js";

export function vn(x, nd = 1) {
  const a = Math.abs(x).toFixed(nd), [i, f] = a.split(".");
  return (x < 0 && Number(a) !== 0 ? "-" : "") + i.replace(/\B(?=(\d{3})+(?!\d))/g, ".") + (f ? "," + f : "");
}
export const signed = (x, nd = 1) => (x >= 0 ? "+" : "") + vn(x, nd);
export const docName = d => String(d || "").replace(/^q(\d)-(\d{4})$/i, "Q$1/$2");       // "q2-2026" -> "Q2/2026"
export const periodLabel = p => (p === ALL ? "tất cả kỳ" : p);
