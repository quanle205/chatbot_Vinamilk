// Gọi API và đổi lỗi thành thông báo tiếng Việt. Mọi màn hình dùng chung để xử lý lỗi giống nhau.
export const NETWORK_ERROR = "Không kết nối được tới máy chủ. Bạn kiểm tra mạng rồi thử lại nhé.";

async function request(url, { method = "GET", body, signal } = {}) {
  const r = await fetch(url, { method, signal, headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  return { ok: r.ok, status: r.status, data: await r.json().catch(() => ({})) };
}
export const get = url => request(url);
export const post = (url, body, signal) => request(url, { method: "POST", body, signal });

// Thông báo cho người dùng từ mã lỗi; máy chủ đã trả `detail` tiếng Việt cho 400/422/429/5xx thì dùng lại.
export function errorText(status, data) {
  const detail = typeof data.detail === "string" ? data.detail : "";
  if (status === 429) return detail || "Bạn thao tác hơi nhanh, vui lòng thử lại sau ít phút.";
  if (status === 400 || status === 422) return detail || "Lựa chọn chưa hợp lệ, bạn kiểm tra lại nhé.";
  return detail || "Đã có sự cố khi xử lý yêu cầu. Bạn thử lại sau ít phút nhé.";
}

// Thực hiện một lời gọi và trả {data} hoặc {error}: gói cả lỗi mạng, để mỗi màn hình chỉ cần hiển thị.
export async function attempt(call) {
  try {
    const r = await call();
    return r.ok ? { data: r.data } : { error: errorText(r.status, r.data), status: r.status };
  } catch (_) { return { error: NETWORK_ERROR }; }
}
