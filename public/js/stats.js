// Số đếm độ phủ dữ liệu (kỳ, chỉ tiêu, đoạn thuyết minh, trang PDF) từ /api/stats, dùng cho hàng số liệu ở màn hình chào.
import { attempt, get } from "./api.js";

let cached = null;
// Trả {data} hoặc {error}; chỉ lưu đệm khi thành công để lần sau còn thử lại được.
export async function getStats() {
  if (cached) return { data: cached };
  const r = await attempt(() => get("/api/stats"));
  if (r.data) cached = r.data;
  return r;
}
