// localStorage có bẫy lỗi (chế độ riêng tư, hết dung lượng): thất bại thì trả giá trị mặc định / false, không làm hỏng giao diện.
export const store = {
  get(key, fallback) { try { const v = localStorage.getItem(key); return v == null ? fallback : JSON.parse(v); } catch (_) { return fallback; } },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch (_) { return false; } },
};
