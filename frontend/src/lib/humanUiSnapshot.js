/**
 * Client-side snapshots (localStorage) for Human UI: projects, runs, run cards, last context.
 * Schema bumps invalidate keys via new PREFIX version.
 */

const SCHEMA = 1;
const PREFIX = "ai_biz_os.human_ui";

function storageKey(suffix) {
  return `${PREFIX}.v${SCHEMA}.${suffix}`;
}

function safeParse(raw, fallback) {
  try {
    if (raw == null || raw === "") return fallback;
    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}

function storageGet(itemKey) {
  if (typeof localStorage === "undefined") return null;
  return localStorage.getItem(itemKey);
}

function storageSet(itemKey, value) {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(itemKey, value);
  } catch {
    /* quota / private mode */
  }
}

export function snapshotReadLastContext() {
  const v = safeParse(storageGet(storageKey("lastContext")), null);
  if (!v || v.schema !== SCHEMA) return null;
  return {
    projectId: v.projectId != null ? Number(v.projectId) : null,
    runId: v.runId != null ? Number(v.runId) : null,
    mainNav: typeof v.mainNav === "string" ? v.mainNav : "runs",
    projectView: v.projectView === "archived" ? "archived" : "active",
  };
}

/** @param {{ projectId?: number | null, runId?: number | null, mainNav?: string, projectView?: string }} ctx */
export function snapshotWriteLastContext(ctx) {
  const payload = {
    schema: SCHEMA,
    projectId: ctx.projectId ?? null,
    runId: ctx.runId ?? null,
    mainNav: ctx.mainNav ?? "runs",
    projectView: ctx.projectView === "archived" ? "archived" : "active",
  };
  storageSet(storageKey("lastContext"), JSON.stringify(payload));
}

export function snapshotInitialProjectView() {
  const lc = snapshotReadLastContext();
  return lc?.projectView === "archived" ? "archived" : "active";
}

/** @param {"active" | "archived"} view */
export function snapshotReadProjects(view) {
  const part = view === "archived" ? "projects_archived" : "projects_active";
  const v = safeParse(storageGet(storageKey(part)), null);
  if (!Array.isArray(v)) return null;
  return v;
}

/** @param {"active" | "archived"} view */
export function snapshotWriteProjects(view, projects) {
  const part = view === "archived" ? "projects_archived" : "projects_active";
  storageSet(storageKey(part), JSON.stringify(projects));
}

/**
 * @template T
 * @param {T[]} data
 * @param {T | null} prev
 * @param {"active" | "archived"} listView
 */
export function snapshotPickSelectedProject(data, prev, listView) {
  if (!data?.length) return null;
  const last = snapshotReadLastContext();
  if (
    last &&
    last.projectView === listView &&
    last.projectId != null &&
    data.some((p) => p.id === last.projectId)
  ) {
    return data.find((p) => p.id === last.projectId) ?? null;
  }
  if (prev && data.some((p) => p.id === prev.id)) return prev;
  return data[0] ?? null;
}

/** @param {number} projectId */
export function snapshotReadRuns(projectId) {
  if (projectId == null || Number.isNaN(Number(projectId))) return null;
  const v = safeParse(storageGet(storageKey(`runs.${projectId}`)), null);
  if (!v) return null;
  if (Array.isArray(v)) return v;
  if (v.schema === SCHEMA && Array.isArray(v.runs)) return v.runs;
  return null;
}

/** @param {number} projectId */
export function snapshotWriteRuns(projectId, runs) {
  if (projectId == null || Number.isNaN(Number(projectId))) return;
  const payload = { schema: SCHEMA, runs, savedAt: Date.now() };
  storageSet(storageKey(`runs.${projectId}`), JSON.stringify(payload));
}

/** @param {number} runId */
export function snapshotReadRunCards(runId) {
  if (runId == null || Number.isNaN(Number(runId))) return null;
  const v = safeParse(storageGet(storageKey(`run_cards.${runId}`)), null);
  if (!v || v.schema !== SCHEMA) return null;
  return {
    display_phase: v.display_phase,
    setup_steps: v.setup_steps,
    setup_summary: v.setup_summary,
    setup_state_message: v.setup_state_message,
    performance: v.performance,
    conversations: v.conversations,
    hourly_sends_24h: v.hourly_sends_24h,
    savedAt: v.savedAt,
  };
}

/** @param {number} runId @param {object} ws — workspace API object */
export function snapshotWriteRunCards(runId, ws) {
  if (runId == null || !ws || typeof ws !== "object") return;
  const payload = {
    schema: SCHEMA,
    savedAt: Date.now(),
    display_phase: ws.display_phase,
    setup_steps: ws.setup_steps,
    setup_summary: ws.setup_summary,
    setup_state_message: ws.setup_state_message,
    performance: ws.performance,
    conversations: ws.conversations,
    hourly_sends_24h: ws.hourly_sends_24h,
  };
  storageSet(storageKey(`run_cards.${runId}`), JSON.stringify(payload));
}

/** Merge cached Run setup / performance fields onto a run row (Run card shape). */
export function snapshotMergeWorkspaceFromRunCards(snap, runRow) {
  if (!runRow) return null;
  const base = { ...runRow };
  if (!snap) return base;
  return {
    ...base,
    display_phase: snap.display_phase ?? base.display_phase,
    setup_steps: snap.setup_steps,
    setup_summary: snap.setup_summary,
    setup_state_message: snap.setup_state_message,
    performance: snap.performance,
    conversations: snap.conversations,
    hourly_sends_24h: snap.hourly_sends_24h,
  };
}

function normalizeAbdCounts(raw) {
  if (!raw || typeof raw !== "object") return null;
  return {
    active: Number(raw.active) || 0,
    bounced: Number(raw.bounced) || 0,
    dead_mailbox: Number(raw.dead_mailbox) || 0,
  };
}

/**
 * Inner tab strip counts (Review contacts, Drafts, Tracking Events/Threads).
 * Key: `inner_tabs.{runId}` — merge-written so TrackingView and Human UI can update their slices independently.
 */
export function snapshotReadInnerTabCounts(runId) {
  if (runId == null || Number.isNaN(Number(runId))) return null;
  const v = safeParse(storageGet(storageKey(`inner_tabs.${runId}`)), null);
  if (!v || v.schema !== SCHEMA) return null;
  return {
    threads: normalizeAbdCounts(v.threads),
    events: normalizeAbdCounts(v.events),
    contacts:
      v.contacts && typeof v.contacts === "object" && !Array.isArray(v.contacts) ? v.contacts : null,
    drafts:
      v.drafts && typeof v.drafts === "object" && !Array.isArray(v.drafts) ? v.drafts : null,
    savedAt: v.savedAt,
  };
}

/**
 * @param {number} runId
 * @param {{ threads?: object, events?: object, contacts?: object, drafts?: object }} partial
 */
export function snapshotMergeWriteInnerTabs(runId, partial) {
  if (runId == null || Number.isNaN(Number(runId)) || !partial || typeof partial !== "object") return;
  const prev = snapshotReadInnerTabCounts(runId);
  const next = {
    schema: SCHEMA,
    savedAt: Date.now(),
    threads:
      partial.threads != null ? normalizeAbdCounts(partial.threads) : prev?.threads ?? null,
    events: partial.events != null ? normalizeAbdCounts(partial.events) : prev?.events ?? null,
    contacts: partial.contacts != null ? partial.contacts : prev?.contacts ?? null,
    drafts: partial.drafts != null ? partial.drafts : prev?.drafts ?? null,
  };
  storageSet(storageKey(`inner_tabs.${runId}`), JSON.stringify(next));
}

/**
 * Instant paint for Threads / Events / Contacts / Drafts: small denormalized lists per run (localStorage).
 * Updated after a successful full load; read while the next load is in flight.
 */
export function snapshotReadRunPanelLite(runId) {
  if (runId == null || Number.isNaN(Number(runId))) return null;
  const v = safeParse(storageGet(storageKey(`panel_lite.${runId}`)), null);
  if (!v || v.schema !== SCHEMA) return null;
  return {
    threads: Array.isArray(v.threads) ? v.threads : null,
    eventsGroups: Array.isArray(v.eventsGroups) ? v.eventsGroups : null,
    contactsPreview: Array.isArray(v.contactsPreview) ? v.contactsPreview : null,
    draftsPreview: Array.isArray(v.draftsPreview) ? v.draftsPreview : null,
    savedAt: v.savedAt,
  };
}

/**
 * @param {number} runId
 * @param {{
 *   threads?: object[] | null,
 *   eventsGroups?: object[] | null,
 *   contactsPreview?: object[] | null,
 *   draftsPreview?: object[] | null,
 * }} partial
 */
export function snapshotMergeWriteRunPanelLite(runId, partial) {
  if (runId == null || Number.isNaN(Number(runId)) || !partial || typeof partial !== "object") return;
  const prev = snapshotReadRunPanelLite(runId) || {};
  const next = {
    schema: SCHEMA,
    savedAt: Date.now(),
    threads: partial.threads !== undefined ? partial.threads : prev.threads ?? null,
    eventsGroups: partial.eventsGroups !== undefined ? partial.eventsGroups : prev.eventsGroups ?? null,
    contactsPreview:
      partial.contactsPreview !== undefined ? partial.contactsPreview : prev.contactsPreview ?? null,
    draftsPreview: partial.draftsPreview !== undefined ? partial.draftsPreview : prev.draftsPreview ?? null,
  };
  storageSet(storageKey(`panel_lite.${runId}`), JSON.stringify(next));
}

/** @public matches backend `context_json` key for Prompt setup. */
export const SNAP_PROMPT_SETUP_TEXT_KEY = "prompt_setup_text";

function runSignatureHtmlMeaningful(html) {
  const raw = String(html ?? "").trim();
  if (!raw) return false;
  const text = raw
    .replace(/<style[\s\S]*?<\/style>/gi, "")
    .replace(/<script[\s\S]*?<\/script>/gi, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;|&#160;/gi, " ")
    .replace(/\u00a0/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return text.length > 0;
}

function deriveSetupPrefsFromRunRow(runRow) {
  if (!runRow || typeof runRow !== "object") {
    return { prompt_setup_saved: false, sender_signature_configured: false };
  }
  const prompt =
    typeof runRow.prompt_setup_saved === "boolean"
      ? runRow.prompt_setup_saved
      : (() => {
          const cj = runRow.context_json;
          const raw = cj && typeof cj === "object" ? cj[SNAP_PROMPT_SETUP_TEXT_KEY] : null;
          return typeof raw === "string" && raw.trim().length > 0;
        })();
  const sig =
    typeof runRow.sender_signature_configured === "boolean"
      ? runRow.sender_signature_configured
      : runSignatureHtmlMeaningful(runRow.sender_signature_html);
  return { prompt_setup_saved: prompt, sender_signature_configured: sig };
}

/**
 * Human UI: Prompt / Signature filled state per run (instant icons). Updated only from seeds (once) or PATCH saves.
 */
export function snapshotReadRunSetupPrefs(runId) {
  if (runId == null || Number.isNaN(Number(runId))) return null;
  const v = safeParse(storageGet(storageKey(`setup_prefs.${runId}`)), null);
  if (!v || v.schema !== SCHEMA) return null;
  return {
    prompt_setup_saved: Boolean(v.prompt_setup_saved),
    sender_signature_configured: Boolean(v.sender_signature_configured),
    savedAt: v.savedAt,
  };
}

/**
 * @param {number} runId
 * @param {{ prompt_setup_saved?: boolean, sender_signature_configured?: boolean }} partial
 */
export function snapshotWriteRunSetupPrefs(runId, partial) {
  if (runId == null || Number.isNaN(Number(runId)) || !partial || typeof partial !== "object") return;
  const prev = snapshotReadRunSetupPrefs(runId);
  const next = {
    schema: SCHEMA,
    savedAt: Date.now(),
    prompt_setup_saved:
      partial.prompt_setup_saved !== undefined
        ? Boolean(partial.prompt_setup_saved)
        : prev != null
          ? Boolean(prev.prompt_setup_saved)
          : false,
    sender_signature_configured:
      partial.sender_signature_configured !== undefined
        ? Boolean(partial.sender_signature_configured)
        : prev != null
          ? Boolean(prev.sender_signature_configured)
          : false,
  };
  storageSet(storageKey(`setup_prefs.${runId}`), JSON.stringify(next));
}

/** One-time: if no prefs stored for this run, fill from API run row (list or full GET). Never overwrites existing. */
export function snapshotEnsureRunSetupPrefsSeedFromRun(runId, runRow) {
  if (runId == null || Number.isNaN(Number(runId)) || !runRow) return;
  if (storageGet(storageKey(`setup_prefs.${runId}`))) return;
  const d = deriveSetupPrefsFromRunRow(runRow);
  snapshotWriteRunSetupPrefs(runId, {
    prompt_setup_saved: d.prompt_setup_saved,
    sender_signature_configured: d.sender_signature_configured,
  });
}
