/** Chunk size for GET list endpoints that support ?limit=&offset= (contacts, email-drafts, email-threads). */
export const LIST_FETCH_PAGE_SIZE = 500;

/**
 * Repeatedly requests paginated `{ items, total, limit, offset }` until all rows are loaded.
 * If the server returns a legacy JSON array (no `limit` query), `getJson` receives that array once and it is returned as-is.
 *
 * @param {(pathWithQuery: string) => Promise<unknown>} getJson — e.g. `path => api(path, opts)`
 * @param {string} basePath — path without query, e.g. `/contacts/run/12`
 */
export async function fetchAllPagedItems(getJson, basePath) {
  const items = [];
  let offset = 0;
  let total = Infinity;
  while (offset < total) {
    const qs = new URLSearchParams({
      limit: String(LIST_FETCH_PAGE_SIZE),
      offset: String(offset),
    });
    const sep = basePath.includes("?") ? "&" : "?";
    const data = await getJson(`${basePath}${sep}${qs}`);
    if (Array.isArray(data)) {
      return data;
    }
    const chunk = data && typeof data === "object" && Array.isArray(data.items) ? data.items : [];
    total = Number(data?.total);
    if (!Number.isFinite(total)) {
      total = chunk.length;
    }
    items.push(...chunk);
    offset += chunk.length;
    if (chunk.length === 0) {
      break;
    }
  }
  return items;
}
