/** Detect stored body that is HTML (e.g. from the rich-text editor). */
export function isProbablyHtmlEmailBody(s) {
  if (s == null || !String(s).trim()) return false;
  return /<[a-z][\s\S]*>/i.test(String(s));
}

const CYRILLIC_RE = /[а-яА-ЯёЁ]/g;
const LATIN_RE = /[a-zA-Z]/g;
const HTML_TAG_RE = /<[^>]+>/g;
const HTML_ENTITY_RE = /&[#a-zA-Z0-9]+;/g;

/** Mirrors backend/app/services/outbound_email_body.py's pick_signature_language (B-546, the
 * B-238 class of bug — the two must never diverge) so the review card labels the original by the
 * language the letter is actually written in, not the language baked into the run's setup.
 * Counts Cyrillic vs. Latin letters; no letters at all → "en" (mirrors the Python fallback when
 * run_language is omitted).
 *
 * B-546: the body is sometimes HTML (B-544's "Оформление" mode saves it that way on purpose) —
 * tags and their attributes (font-family:Arial,Helvetica,sans-serif, href, class, ...) are pure
 * Latin and can outnumber Cyrillic letters in an otherwise Russian email, so markup and HTML
 * entities (&nbsp;, &amp;, &#160;, ...) are stripped to a space before counting. */
export function draftBodyLanguage(body) {
  const raw = String(body ?? "");
  const text = raw.replace(HTML_TAG_RE, " ").replace(HTML_ENTITY_RE, " ");
  const cyr = (text.match(CYRILLIC_RE) || []).length;
  const lat = (text.match(LATIN_RE) || []).length;
  return cyr > lat ? "ru" : "en";
}

const LIST_ITEM_RE = /^\s*[-–—•*]\s+/;

/** Mirrors outbound_email_body.py's _render_list_block (B-533) so the editor/preview never
 * diverges from what actually goes out (the B-238 class of bug): leading non-bullet lines → one
 * <p>, the contiguous run of bullet lines → <ul>/<li>, trailing non-bullet lines → another <p>. */
function renderListBlock(lines) {
  let i = 0;
  const intro = [];
  while (i < lines.length && !LIST_ITEM_RE.test(lines[i])) {
    intro.push(lines[i]);
    i += 1;
  }
  const items = [];
  while (i < lines.length && LIST_ITEM_RE.test(lines[i])) {
    items.push(`<li>${lines[i].replace(LIST_ITEM_RE, "")}</li>`);
    i += 1;
  }
  const tail = lines.slice(i);
  const parts = [];
  if (intro.length) parts.push(`<p>${intro.join("<br>")}</p>`);
  parts.push(`<ul>${items.join("")}</ul>`);
  if (tail.length) parts.push(`<p>${tail.join("<br>")}</p>`);
  return parts.join("");
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
  const blocks = esc.split(/\n{2,}/);
  if (blocks.length === 0) return "<p></p>";
  return blocks
    .map((block) => {
      const lines = block.split("\n");
      if (lines.some((line) => LIST_ITEM_RE.test(line))) return renderListBlock(lines);
      return `<p>${block.replace(/\n/g, "<br>")}</p>`;
    })
    .join("");
}
