/** Detect stored body that is HTML (e.g. from the rich-text editor). */
export function isProbablyHtmlEmailBody(s) {
  if (s == null || !String(s).trim()) return false;
  return /<[a-z][\s\S]*>/i.test(String(s));
}

/** Plain text and legacy drafts → HTML TipTap can load. */
export function normalizeDraftBodyForEditor(body) {
  const s = body ?? "";
  if (!s.trim()) return "<p></p>";
  if (isProbablyHtmlEmailBody(s)) return s;
  const esc = s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  const parts = esc.split(/\n{2,}/);
  if (parts.length === 0) return "<p></p>";
  return parts.map((block) => `<p>${block.replace(/\n/g, "<br>")}</p>`).join("");
}
