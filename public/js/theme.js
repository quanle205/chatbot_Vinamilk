// Apply the saved theme before CSS loads to prevent a light flash.
(() => {
  const key = "vinamilk-theme", system = window.matchMedia("(prefers-color-scheme: dark)");
  let saved;
  try { saved = localStorage.getItem(key); } catch (_) {}
  let explicit = saved === "light" || saved === "dark";
  function apply(theme) {
    document.documentElement.dataset.theme = theme;
    const dark = theme === "dark", button = document.getElementById("theme-toggle");
    document.querySelector('meta[name="theme-color"]').content = dark ? "#101827" : "#4338ca";
    if (button) {
      button.setAttribute("aria-pressed", String(dark));
      button.setAttribute("aria-label", dark ? "Chuyển sang giao diện sáng" : "Chuyển sang giao diện tối");
      button.title = button.getAttribute("aria-label");
      button.querySelector(".theme-icon").textContent = dark ? "☀" : "☾";
      button.querySelector(".theme-state").textContent = dark ? "Tối" : "Sáng";
    }
    window.dispatchEvent(new Event("themechange"));
  }
  apply(explicit ? saved : system.matches ? "dark" : "light");
  system.addEventListener("change", () => { if (!explicit) apply(system.matches ? "dark" : "light"); });
  document.addEventListener("DOMContentLoaded", () => {
    apply(document.documentElement.dataset.theme);
    document.getElementById("theme-toggle").addEventListener("click", () => {
      const theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      explicit = true;
      try { localStorage.setItem(key, theme); } catch (_) {}
      apply(theme);
    });
  });
})();
