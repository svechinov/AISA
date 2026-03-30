export const THEME_STORAGE_KEY = "ai-biz-os-theme";

/** @returns {"light" | "dark"} */
export function readStoredTheme() {
  try {
    const v = localStorage.getItem(THEME_STORAGE_KEY);
    if (v === "dark" || v === "light") return v;
  } catch {
    /* ignore */
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** Apply theme to <html> and persist explicit user choice. */
export function setTheme(mode) {
  const root = document.documentElement;
  const dark = mode === "dark";
  root.classList.toggle("dark", dark);
  try {
    localStorage.setItem(THEME_STORAGE_KEY, dark ? "dark" : "light");
  } catch {
    /* ignore */
  }
}
