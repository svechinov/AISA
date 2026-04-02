import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  useDialog,
} from "@/components/ui/dialog";
import { NativeFilterSelect } from "@/components/ui/select";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import appPkg from "../../package.json";
import TrackingView from "@/components/TrackingView";
import { EmailDraftRichTextEditor } from "@/components/EmailDraftRichTextEditor";
import { EmailDraftBodyPreview } from "@/components/EmailDraftBodyPreview";
import {
  DraftAssetAttachmentsField,
  normalizeAttachedAssetIds,
} from "@/components/DraftAssetAttachmentsField";
import { ThemeToggle } from "@/components/ThemeToggle";
import { cn } from "@/lib/utils";
import {
  snapshotEnsureRunSetupPrefsSeedFromRun,
  snapshotInitialProjectView,
  snapshotMergeWorkspaceFromRunCards,
  snapshotMergeWriteInnerTabs,
  snapshotMergeWriteRunPanelLite,
  snapshotPickSelectedProject,
  snapshotReadInnerTabCounts,
  snapshotReadLastContext,
  snapshotReadProjects,
  snapshotReadRunCards,
  snapshotReadRunPanelLite,
  snapshotReadRunSetupPrefs,
  snapshotReadRuns,
  snapshotWriteLastContext,
  snapshotWriteProjects,
  snapshotWriteRunCards,
  snapshotWriteRunSetupPrefs,
  snapshotWriteRuns,
} from "@/lib/humanUiSnapshot";
import {
  MAX_CONTACTS_PANEL_LITE,
  stripContactForPanelLite,
  stripDraftForPanelLite,
} from "@/lib/runPanelLite";
import {
  Archive,
  ArchiveRestore,
  ArrowDownWideNarrow,
  ArrowUpNarrowWide,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  CircleX,
  Clock,
  FileText,
  Loader2,
  Mail,
  Pencil,
  RefreshCw,
  Search,
  Settings,
  Users,
  X,
} from "lucide-react";

/**
 * In dev without VITE_API_BASE: requests go to the same host as the UI (`/api/...`), and Vite proxies to :8000.
 * The browser then avoids hitting port 8000 directly (common firewall / IPv6 / file-policy issues).
 * In a production build without env, the default is a direct URL (with nginx, configure your own proxy).
 */
const ENV_API = import.meta.env.VITE_API_BASE?.trim();
const DEV_PROXY_TARGET =
  import.meta.env.VITE_API_PROXY_TARGET?.trim() || "http://127.0.0.1:8000";
const API_BASE =
  ENV_API && ENV_API.length > 0
    ? ENV_API.replace(/\/$/, "")
    : import.meta.env.DEV
      ? "/api"
      : "http://127.0.0.1:8000";

/** Labels for GET /setup/status summary (dashboard informer). */
const SETUP_LLM_LABELS = {
  claude: "Claude",
  openai: "OpenAI",
  perplexity: "Perplexity",
  grok: "Grok",
};

const SETUP_CDN_LABELS = {
  cloudflare: "Cloudflare",
  akamai: "Akamai",
  cloudfront: "Amazon CloudFront",
  gcp_cdn: "Google Cloud CDN",
};

const DEFAULT_OUTREACH_BRIEF =
  "Offer:\nTarget:\nRoles:\nGoal:\nTone: Professional\nNotes:\n";

/** Stored in `email_drafts.review_notes` when reviewer uses the clock (defer send). */
const OUTBOUND_REVIEW_SEND_LATER = "send_later";

/** Company-level green “Pending”: draft sent and still waiting or in active reply — not bounce/dead only. */
const COMPANY_OUTREACH_PENDING_TRACKING = new Set(["sent", "replied"]);

function _normCompanyToken(s) {
  return String(s ?? "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ");
}

function _stripWebsiteKey(url) {
  let u = _normCompanyToken(url);
  u = u.replace(/^https?:\/\//, "").replace(/^www\./, "");
  return u.replace(/\/+$/, "");
}

/** Intersecting keys for Companies row ↔ run contact (same idea as backend run_companies_status_service). */
function entityKeysForCompanyRowOrContact(obj) {
  const keys = new Set();
  const name = _normCompanyToken("name" in obj ? obj.name : obj.company);
  if (name) keys.add(name);
  const web = String(obj.website || "").trim();
  if (web) {
    const stripped = _stripWebsiteKey(web);
    if (stripped) keys.add(stripped);
    keys.add(_normCompanyToken(web));
  }
  return [...keys].filter(Boolean);
}

function contactMatchesCompaniesTableRow(contact, row) {
  const a = new Set(entityKeysForCompanyRowOrContact({ name: row.name, website: row.website }));
  const b = new Set(entityKeysForCompanyRowOrContact({ company: contact.company, website: contact.website }));
  if (!a.size || !b.size) return false;
  for (const k of a) {
    if (b.has(k)) return true;
  }
  return false;
}

/** Companies “Contacts found” → show Not available when every matched contact is bounced or dead mailbox. */
function companyHasOnlyBouncedOrDeadContacts(contacts, row) {
  const matched = (contacts || []).filter((c) => contactMatchesCompaniesTableRow(c, row));
  if (!matched.length) return false;
  return matched.every((c) => c.email_health === "bounced" || c.email_health === "dead_mailbox");
}

/** After send, outbound leaves Review → Drafts (track in Events / Threads). */
function isOutboundDraftClosedForReview(d) {
  return Boolean(d && String(d.status) === "sent");
}

function mergeContactReviewSnap(snap, live) {
  return {
    pending: snap?.pending ?? live.pending,
    approved: snap?.approved ?? live.approved,
    rejected: snap?.rejected ?? live.rejected,
    bounced: snap?.bounced ?? live.bounced,
    dead_mailbox: snap?.dead_mailbox ?? live.dead_mailbox,
    no_email: snap?.no_email ?? live.no_email,
  };
}

function mergeDraftReviewSnap(snap, live) {
  return {
    pendingReview: snap?.pendingReview ?? live.pendingReview,
    approved: snap?.approved ?? live.approved,
  };
}

/** Snapshot-only: «все нули» → сразу empty; нет снапшота или есть >0 → ждём загрузку. */
function reviewContactsSnapMode(contactsSnap) {
  if (!contactsSnap || typeof contactsSnap !== "object") return "loading";
  const keys = ["pending", "approved", "rejected", "bounced", "dead_mailbox", "no_email"];
  let sum = 0;
  for (const k of keys) sum += Number(contactsSnap[k]) || 0;
  return sum === 0 ? "empty" : "loading";
}

function reviewDraftsSnapMode(draftsSnap) {
  if (!draftsSnap || typeof draftsSnap !== "object") return "loading";
  const sum = (Number(draftsSnap.pendingReview) || 0) + (Number(draftsSnap.approved) || 0);
  return sum === 0 ? "empty" : "loading";
}

function SnapshotCardsPlaceholder({ mode, kind }) {
  if (mode === "empty") {
    return (
      <div className="rounded-2xl border-2 border-dashed border-muted-foreground/25 py-14 text-center text-sm text-muted-foreground">
        No {kind} data for this run.
      </div>
    );
  }
  return (
    <div
      className="flex flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed border-muted-foreground/25 py-14 text-center text-sm text-muted-foreground"
      role="status"
      aria-live="polite"
    >
      <Clock className="h-8 w-8 shrink-0 animate-spin text-primary" aria-hidden />
      <p>
        {kind} data is loading…
      </p>
    </div>
  );
}

/**
 * API returns runs newest-first (id desc). Surface non-closed runs first for default
 * selection and lists so a closed wave is not shown ahead of an active one.
 */
function orderRunsOpenFirst(runs) {
  if (!Array.isArray(runs) || runs.length === 0) return [];
  const open = runs.filter((r) => !r.closed_at);
  const closed = runs.filter((r) => r.closed_at);
  return [...open, ...closed];
}

/** Longest first so e.g. "professional notes:" wins over embedded "notes:". */
const BRIEF_LABEL_PREFIXES = [
  ["target entities:", "target_entities"],
  ["professional notes:", "notes"],
  ["target roles:", "target_roles"],
  ["offer:", "offer"],
  ["target:", "target_entities"],
  ["roles:", "target_roles"],
  ["role:", "target_roles"],
  ["goal:", "goal"],
  ["tone:", "tone"],
  ["notes:", "notes"],
];

function briefLineLabelAndRest(line) {
  let s = line.trim();
  if (!s) return [null, ""];
  /** Markdown-wrapped labels (**Offer:**) break prefix match; strip * for detection only. */
  s = s.replace(/\*/g, "").trim();
  if (!s) return [null, ""];
  const lower = s.toLowerCase();
  for (const [prefix, key] of BRIEF_LABEL_PREFIXES) {
    if (lower.startsWith(prefix)) {
      return [key, s.slice(prefix.length).trim()];
    }
  }
  return [null, s];
}

/** Mirrors backend brief parser: at least Offer or Goal must have text. */
function outreachBriefHasOfferOrGoal(raw) {
  const text = (raw || "").trim();
  if (!text) return false;
  const acc = {
    offer: "",
    target_entities: "",
    target_roles: "",
    goal: "",
    tone: "",
    notes: "",
  };
  let currentKey = null;
  const chunks = [];
  const flush = () => {
    if (currentKey !== null) {
      acc[currentKey] = chunks.join("\n").trim();
    }
    chunks.length = 0;
  };
  for (const line of text.split("\n")) {
    const [lk, rest] = briefLineLabelAndRest(line);
    if (lk !== null) {
      flush();
      currentKey = lk;
      if (rest) chunks.push(rest);
    } else if (currentKey !== null) {
      chunks.push(line);
    } else if (line.trim()) {
      acc.notes = acc.notes ? `${acc.notes}\n${line.trim()}` : line.trim();
    }
  }
  flush();
  return Boolean((acc.offer && acc.offer.length > 0) || (acc.goal && acc.goal.length > 0));
}

/** Inner outreach fields from API run.context_json (nested `context` or legacy flat). */
function contextFromRun(run) {
  if (!run?.context_json || typeof run.context_json !== "object") return null;
  const cj = run.context_json;
  const inner = cj.context && typeof cj.context === "object" ? cj.context : cj;
  const goal =
    String(inner.goal ?? inner.outreach_goal ?? "").trim() ||
    (run.input_json && typeof run.input_json === "object"
      ? String(run.input_json.goal ?? "").trim()
      : "");
  return {
    offer: String(inner.offer ?? inner.product ?? "").trim(),
    target_entities: String(inner.target_entities ?? "").trim(),
    target_roles: String(inner.target_roles ?? "").trim(),
    goal,
    tone: String(inner.tone ?? "Professional").trim() || "Professional",
    notes: String(inner.notes ?? inner.extra_context ?? "").trim(),
  };
}

function contextToOutreachBriefText(ctx) {
  if (!ctx) return DEFAULT_OUTREACH_BRIEF;
  return [
    `Offer: ${ctx.offer}`,
    `Target: ${ctx.target_entities}`,
    `Roles: ${ctx.target_roles}`,
    `Goal: ${ctx.goal}`,
    `Tone: ${ctx.tone}`,
    `Notes: ${ctx.notes}`,
    "",
  ].join("\n");
}

/** Mirrors backend run.context_json key for saved Prompt setup textarea. */
const PROMPT_SETUP_STORAGE_KEY = "prompt_setup_text";

/** True when saved HTML has visible text (empty rich-text often stores tags only). */
function runSignatureHasMeaningfulContent(html) {
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

function getPromptSetupEditorInitialText(run) {
  if (!run) return DEFAULT_OUTREACH_BRIEF;
  const cj = run.context_json;
  if (cj && typeof cj === "object") {
    const raw = cj[PROMPT_SETUP_STORAGE_KEY];
    if (typeof raw === "string" && raw.length > 0) {
      return raw;
    }
  }
  const ctx = contextFromRun(run);
  return contextToOutreachBriefText(ctx);
}

/** Prefill dialog from a run (GET /runs/:id or selected run). */
function seedNewRunFormFromRun(run) {
  if (!run) {
    return {
      name: "",
      notes: "",
      segment: "",
      outreach_brief: DEFAULT_OUTREACH_BRIEF,
    };
  }
  const ctx = contextFromRun(run);
  const brief = ctx ? contextToOutreachBriefText(ctx) : DEFAULT_OUTREACH_BRIEF;
  const baseName = String(run.name ?? "").trim();
  const seg = String(run.segment ?? "").trim();
  const dateStr = new Date().toLocaleDateString();
  const name = baseName
    ? baseName
    : seg
      ? seg
      : `Outreach wave · ${dateStr}`;
  return {
    name,
    notes: String(run.notes ?? "").trim(),
    segment: seg,
    outreach_brief: brief,
  };
}

/** Default timeout so the UI never sits on “Loading…” forever if the proxy/API hangs. */
const API_TIMEOUT_MS = 25000;
/** POST /runs/:id/restart runs the full LLM setup loop synchronously. */
const RESTART_RUN_TIMEOUT_MS = 600000;
/** POST /runs/start runs `run_workflow` synchronously on the server (same class of long work as restart). */
const START_RUN_TIMEOUT_MS = 600000;
/** Single-company find retry calls the LLM again; allow longer than default API timeout. */
const COMPANY_RETRY_FIND_TIMEOUT_MS = 120000;
/** PATCH prompt/signature is fast on the server, but slow proxies or queued workers can exceed the default. */
const RUN_SETUP_PATCH_TIMEOUT_MS = 120000;
/** Run-details bundle is many parallel GETs; allow the same headroom when refreshing after setup saves. */
const LOAD_RUN_DETAILS_BUNDLE_TIMEOUT_MS = 120000;
/** Contact analyzer: many Gmail searches in one request — allow long run (default 25s would abort mid-flight). */
const CONTACT_ANALYZER_VERIFY_ALL_TIMEOUT_MS = 600000;
/** Single-address Gmail search can be slow. */
const CONTACT_ANALYZER_VERIFY_ONE_TIMEOUT_MS = 120000;
/** Import inbox+sent (6 months) may fetch many messages; allow long run. */
const CONTACT_ANALYZER_IMPORT_INBOX_TIMEOUT_MS = 600000;
/** Rows per page in Contact analyzer table. */
const CONTACT_ANALYZER_PAGE_SIZE = 50;
/** Same page size for Companies table and Contacts group lists. */
const WORKSPACE_TABLE_PAGE_SIZE = CONTACT_ANALYZER_PAGE_SIZE;

function combineAbortSignals(a, b) {
  if (typeof AbortSignal !== "undefined" && typeof AbortSignal.any === "function") {
    return AbortSignal.any([a, b]);
  }
  const combined = new AbortController();
  const abort = () => combined.abort();
  if (a.aborted || b.aborted) {
    abort();
    return combined.signal;
  }
  a.addEventListener("abort", abort, { once: true });
  b.addEventListener("abort", abort, { once: true });
  return combined.signal;
}

const statusTone = {
  pending: "secondary",
  running: "default",
  completed: "default",
  failed: "destructive",
  needs_review: "secondary",
  drafts_ready: "secondary",
  approved: "default",
  rejected: "destructive",
  edited: "secondary",
  valid: "default",
  invalid: "destructive",
  draft: "secondary",
  sending: "default",
  sent: "default",
};

const sendLifecycleBadgeClass = {
  draft: "border-amber-500/40 bg-amber-500/10 text-amber-950 dark:text-amber-100",
  sending: "border-blue-500/40 bg-blue-500/10 text-blue-950 dark:text-blue-100",
  sent: "border-green-600/40 bg-green-600/10 text-green-900 dark:text-green-100",
  failed: "border-destructive/50 bg-destructive/10 text-destructive",
  replied: "border-emerald-600/40 bg-emerald-500/10 text-emerald-950 dark:text-emerald-100",
  bounced: "border-orange-500/40 bg-orange-500/10 text-orange-950 dark:text-orange-100",
  dead_mailbox: "border-red-700/40 bg-red-600/10 text-red-950 dark:text-red-100",
};

const pretty = (v) => {
  if (!v) return "—";
  return String(v)
    .replaceAll("_", " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
};

function formatSetupIntegrationInformer(si) {
  const ids = si?.llm_providers_ready;
  const llmPart =
    Array.isArray(ids) && ids.length > 0
      ? ids.map((id) => SETUP_LLM_LABELS[id] || pretty(id)).join(", ")
      : "—";
  const cdnId = String(si?.cdn_provider ?? "").trim().toLowerCase();
  const cdnPart = cdnId ? SETUP_CDN_LABELS[cdnId] || pretty(cdnId) : "—";
  return { llmPart, cdnPart };
}

/** Merge GET /runs/:id/workspace-lite into existing full workspace (poll path). */
function mergeWorkspaceLiteInto(prevWorkspace, lite) {
  if (!lite || typeof lite !== "object") return prevWorkspace;
  if (!prevWorkspace || typeof prevWorkspace !== "object") return prevWorkspace;
  return {
    ...prevWorkspace,
    display_phase: lite.display_phase ?? prevWorkspace.display_phase,
    setup_state_message: lite.setup_state_message ?? prevWorkspace.setup_state_message,
    performance: {
      ...(prevWorkspace.performance && typeof prevWorkspace.performance === "object"
        ? prevWorkspace.performance
        : {}),
      ...(lite.performance && typeof lite.performance === "object" ? lite.performance : {}),
    },
    conversations: {
      ...(prevWorkspace.conversations && typeof prevWorkspace.conversations === "object"
        ? prevWorkspace.conversations
        : {}),
      ...(lite.conversations && typeof lite.conversations === "object" ? lite.conversations : {}),
    },
  };
}

/** Job title for header + edit form: column `role`, else common keys in source_json (LLM / legacy). */
function contactRoleFromPayload(contact) {
  if (!contact) return "";
  const col = String(contact.role ?? "").trim();
  if (col) return col;
  const sj = contact.source_json && typeof contact.source_json === "object" ? contact.source_json : {};
  return String(sj.role ?? sj.title ?? sj.job_title ?? sj.position ?? "").trim();
}

function StatusBadge({ value }) {
  return <Badge variant={statusTone[value] || "secondary"}>{pretty(value)}</Badge>;
}

function SendLifecycleBadge({ status }) {
  const st = status || "draft";
  if (st === "dead_mailbox") {
    return (
      <Badge variant="destructive" className="font-normal text-xs">
        Dead mailbox
      </Badge>
    );
  }
  const cls = sendLifecycleBadgeClass[st];
  const label =
    st === "bounced"
      ? "Bounced"
      : pretty(st);
  return (
    <Badge className={cls} variant="secondary">
      {label}
    </Badge>
  );
}

/** FastAPI often returns `{ "detail": "..." | [...] }` in the response body; `api()` puts raw body in Error.message. */
function detailFromApiErrorMessage(msg) {
  const m = String(msg || "").trim();
  if (!m) return "Request failed";
  try {
    const j = JSON.parse(m);
    const d = j.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      return d
        .map((x) => (typeof x === "object" && x != null && x.msg != null ? String(x.msg) : JSON.stringify(x)))
        .join("; ");
    }
  } catch {
    /* plain text */
  }
  return m;
}

function formatApiError(e) {
  if (e?.name === "AbortError") {
    const curlHint =
      API_BASE === "/api"
        ? `Timed out or cancelled — check ${DEV_PROXY_TARGET}/health (Vite proxies /api to VITE_API_PROXY_TARGET; default http://127.0.0.1:8000).`
        : `Timed out or cancelled — check ${API_BASE}/health.`;
    return `${curlHint}`;
  }
  const msg = e?.message || String(e);
  if (msg === "Failed to fetch" || msg.includes("NetworkError") || msg.includes("Load failed")) {
    const curlHint =
      API_BASE === "/api"
        ? `curl ${DEV_PROXY_TARGET}/health — the Vite proxy uses VITE_API_PROXY_TARGET (${DEV_PROXY_TARGET}); if not OK, start the backend (e.g. docker compose up -d in infra/ for :8000).`
        : `curl ${API_BASE}/health and docker compose up -d in infra/.`;
    return `${msg} — ${curlHint}`;
  }
  return msg;
}

/** Transient / bursty request failures — log only; no full-page error informer. */
function isConsoleOnlyApiFailure(message) {
  const m = String(message || "");
  return (
    m.includes("Failed to fetch") ||
    m.includes("NetworkError") ||
    m.includes("Load failed") ||
    m.includes("Timed out or cancelled") ||
    (m.includes("Abort") && (m.includes("aborted") || m.includes("cancel")))
  );
}

function setUiError(setError, err) {
  const raw = String(err?.message ?? err ?? "");
  if (!raw) return;
  const msg = detailFromApiErrorMessage(raw);
  if (!msg) return;
  if (isConsoleOnlyApiFailure(msg)) {
    console.warn("[AiBizOsHumanUI]", msg, err);
    return;
  }
  setError(msg);
}

async function api(path, { method = "GET", body, headers: hdr = {}, signal, timeoutMs = API_TIMEOUT_MS } = {}) {
  const headers = { ...hdr };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const timeoutCtl = new AbortController();
  const tid = setTimeout(() => timeoutCtl.abort(), timeoutMs);
  const combined = signal ? combineAbortSignals(signal, timeoutCtl.signal) : timeoutCtl.signal;
  let res;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: combined,
      cache: "no-store",
    });
  } catch (e) {
    throw new Error(formatApiError(e));
  } finally {
    clearTimeout(tid);
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Request failed: ${res.status}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

function projectPk(p) {
  return p?.project_id ?? p?.id;
}

/** Align with backend `app.utils.contact_identity` (name + company + website only). */
function contactIdentityKeyFromContactRow(c) {
  if (!c || typeof c !== "object") return null;
  const normWs = (s) => String(s || "").trim().replace(/\s+/g, " ").toLowerCase();
  const stripSite = (url) => {
    let u = normWs(url);
    u = u.replace(/^https?:\/\//, "").replace(/^www\./, "");
    return u.replace(/\/+$/, "");
  };
  const name = normWs(c.name);
  const company = normWs(c.company);
  const site = stripSite(c.website);
  if (!name && !company && !site) return null;
  return `${name}\x1f${company}\x1f${site}`;
}

/** Hide redundant Invalid/No-email rows when the same person already has a row with an email. */
function filterShadowNoEmailContacts(contactsList) {
  if (!Array.isArray(contactsList) || contactsList.length === 0) return contactsList;
  const identitiesWithEmail = new Set();
  for (const c of contactsList) {
    const em = String(c.email || "").trim().toLowerCase();
    if (em && em.includes("@")) {
      const ik = contactIdentityKeyFromContactRow(c);
      if (ik) identitiesWithEmail.add(ik);
    }
  }
  return contactsList.filter((c) => {
    const em = String(c.email || "").trim().toLowerCase();
    if (em && em.includes("@")) return true;
    const ik = contactIdentityKeyFromContactRow(c);
    if (ik && identitiesWithEmail.has(ik)) return false;
    return true;
  });
}

/** Review contacts tab bucket. Order: delivery health → usable email → review_status. */
function contactReviewTabBucket(c) {
  const em = String(c?.email ?? "").trim().toLowerCase();
  const hasUsableEmail = em.includes("@");
  if (c.email_health === "dead_mailbox") return "dead_mailbox";
  if (c.email_health === "bounced") return "bounced";
  if (!hasUsableEmail) return "no_email";
  const rs = c.review_status;
  if (rs === "pending") return "pending";
  if (rs === "rejected") return "rejected";
  if (rs === "approved" || rs === "edited") return "approved";
  return "no_email";
}

/** Total performance card: Gmail daily send-tier hint from 24h volume (all runs). */
function totalPerformance24hBand(emailsSent24h) {
  const n = Number(emailsSent24h);
  const safe = Number.isFinite(n) ? Math.max(0, Math.floor(n)) : 0;
  if (safe >= 200) {
    return {
      label: "danger of blocking",
      cardClass: "border-red-500/55 bg-red-500/15",
      captionClass: "text-red-700 dark:text-red-400",
    };
  }
  if (safe >= 180) {
    return {
      label: "blocking capability",
      cardClass: "border-orange-500/55 bg-orange-500/15",
      captionClass: "text-orange-800 dark:text-orange-400",
    };
  }
  if (safe > 160) {
    return {
      label: "above normal",
      cardClass: "border-amber-400/55 bg-amber-500/15",
      captionClass: "text-amber-900 dark:text-amber-300",
    };
  }
  return {
    label: "normal",
    cardClass: "border-border bg-card",
    captionClass: "text-muted-foreground",
  };
}

function NewProjectFooter({ projectName, onCreated }) {
  const { setOpen } = useDialog();
  return (
    <DialogFooter>
      <Button
        onClick={async () => {
          await onCreated();
          setOpen(false);
        }}
      >
        Create
      </Button>
    </DialogFooter>
  );
}

const PROJECT_VIEW_OPTS = [
  { value: "active", label: "Active projects" },
  { value: "archived", label: "Archived projects" },
];

const MAIN_NAV = [
  { value: "runs", label: "Runs" },
  { value: "companies", label: "Companies" },
  { value: "contacts", label: "Contacts" },
  { value: "drafts", label: "Drafts" },
  { value: "events", label: "Events" },
  { value: "threads", label: "Threads" },
  { value: "reply-drafts", label: "Reply drafts" },
  { value: "reminders", label: "Reminders" },
  { value: "assets", label: "Assets" },
  { value: "packets", label: "Packets" },
  { value: "dead", label: "Dead mailboxes" },
  { value: "queue", label: "Re-search queue" },
  { value: "contact-analyzer", label: "Contact analyzer" },
];

function mainNavToTrackingTab(nav) {
  const map = {
    events: "events",
    threads: "threads",
    "reply-drafts": "replies",
    reminders: "reminders",
    assets: "assets-library",
    packets: "asset-packets",
    dead: "dead",
    queue: "queue",
  };
  return map[nav] || "events";
}

/** Inverse map — TrackingView tab value → Human UI main nav (single global «place»). */
function trackingTabToMainNav(tab) {
  const t = String(tab || "");
  const map = {
    events: "events",
    threads: "threads",
    replies: "reply-drafts",
    reminders: "reminders",
    "assets-library": "assets",
    "asset-packets": "packets",
    dead: "dead",
    queue: "queue",
  };
  return map[t] || "events";
}

export default function AiBizOsHumanUI() {
  const [projects, setProjects] = useState([]);
  const [selectedProject, setSelectedProject] = useState(null);
  const [selectedRun, setSelectedRun] = useState(null);
  const [steps, setSteps] = useState([]);
  const [contacts, setContacts] = useState([]);
  const [drafts, setDrafts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  /** Hide draft error banner after dismiss; key = `${id}:${error_message}` so a new error shows again. */
  const [dismissedOutboundDraftErrorKeys, setDismissedOutboundDraftErrorKeys] = useState(
    () => new Set(),
  );
  const [projectName, setProjectName] = useState("New campaign");
  const [search, setSearch] = useState("");
  /** Review email drafts: same idea as contact review tabs — only two buckets. */
  const [draftReviewTab, setDraftReviewTab] = useState("pending");
  const [projectView, setProjectView] = useState(() => snapshotInitialProjectView());
  const [mainNav, setMainNav] = useState(() => {
    const lc = snapshotReadLastContext();
    return typeof lc?.mainNav === "string" ? lc.mainNav : "runs";
  });
  const [runsList, setRunsList] = useState([]);
  const [workspace, setWorkspace] = useState(null);
  /** When === selectedRun.id, Review contacts / Drafts sub-tab counts use live data; else localStorage snapshot. */
  const [runDetailsHydratedId, setRunDetailsHydratedId] = useState(null);
  /** Bumps when Prompt/Signature setup localStorage prefs change so icons re-read snapshots without waiting on run object. */
  const [runSetupPrefsRev, setRunSetupPrefsRev] = useState(0);
  /** All runs / all projects — from GET /sending/global-performance. */
  const [totalPerformance, setTotalPerformance] = useState(null);
  const [newRunOpen, setNewRunOpen] = useState(false);
  /** Snapshot when the dialog opened from an existing run: trimmed fields + optional runId for Update vs Create. */
  const [newRunBaseline, setNewRunBaseline] = useState(null);
  const [newRunCreateInFlight, setNewRunCreateInFlight] = useState(false);
  const [newRunUpdateInFlight, setNewRunUpdateInFlight] = useState(false);
  const newRunDialogBusy = newRunCreateInFlight || newRunUpdateInFlight;
  const [switchRunOpen, setSwitchRunOpen] = useState(false);
  const [closeRunOpen, setCloseRunOpen] = useState(false);
  const [renameProjectOpen, setRenameProjectOpen] = useState(false);
  const [renameProjectId, setRenameProjectId] = useState(null);
  const [renameProjectNameField, setRenameProjectNameField] = useState("");
  const [renameProjectSaving, setRenameProjectSaving] = useState(false);
  const [newRunForm, setNewRunForm] = useState({
    name: "",
    notes: "",
    segment: "",
    outreach_brief: DEFAULT_OUTREACH_BRIEF,
  });
  const [openRunEditLoading, setOpenRunEditLoading] = useState(false);

  /** Inline edit: { id, email } */
  const [editingContact, setEditingContact] = useState(null);
  const [createDraftContactId, setCreateDraftContactId] = useState(null);
  /** Keys: draft id string — outbound draft body regeneration in progress. */
  const [regeneratingOutboundDraftIds, setRegeneratingOutboundDraftIds] = useState(() => ({}));
  /** Outbound draft id → review PATCH in flight (Approve / Send later / Reject). */
  const [outboundDraftReviewBusy, setOutboundDraftReviewBusy] = useState(() => ({}));
  /** Keys: draft id string — POST /sending/drafts/:id/send in flight (Review → Drafts). */
  const [sendingOutboundDraftIds, setSendingOutboundDraftIds] = useState(() => ({}));
  /** POST /sending/runs/:id/send in flight (Send all approved). */
  const [sendAllApprovedBusy, setSendAllApprovedBusy] = useState(false);
  const [editDraft, setEditDraft] = useState(null);
  const [editDraftSaving, setEditDraftSaving] = useState(false);
  const [applyAssetsToAllPendingDrafts, setApplyAssetsToAllPendingDrafts] = useState(false);
  const [assetsLibrary, setAssetsLibrary] = useState([]);
  const [runAssetPackets, setRunAssetPackets] = useState([]);
  const [draftForm, setDraftForm] = useState({
    subject: "",
    body: "",
    attached_asset_ids: [],
  });
  const [signatureSetupOpen, setSignatureSetupOpen] = useState(false);
  const [signatureFormHtml, setSignatureFormHtml] = useState("");
  const [signatureEditorKey, setSignatureEditorKey] = useState(0);
  /** Defer TipTap mount so the modal shell paints before heavy editor init. */
  const [signatureEditorMount, setSignatureEditorMount] = useState(false);
  const [signatureSetupSaving, setSignatureSetupSaving] = useState(false);
  const [promptSetupOpen, setPromptSetupOpen] = useState(false);
  const [promptSetupText, setPromptSetupText] = useState("");
  const [promptSetupSaving, setPromptSetupSaving] = useState(false);
  const [restartDialogOpen, setRestartDialogOpen] = useState(false);
  const [restartDialogRun, setRestartDialogRun] = useState(null);
  /** Non-blocking: restart runs in background after confirm (no full-screen lock). */
  const [pendingRestart, setPendingRestart] = useState(null);
  const [companiesPanel, setCompaniesPanel] = useState(null);
  const [companiesLoading, setCompaniesLoading] = useState(false);
  /** Per-row: POST /companies/retry-find in flight (several retries can run in parallel). */
  const [companyRetryLoading, setCompanyRetryLoading] = useState(() => ({}));
  const [companyRetryAllLoading, setCompanyRetryAllLoading] = useState(false);
  const [companiesPage, setCompaniesPage] = useState(1);
  const [contactReviewTab, setContactReviewTab] = useState("pending");
  const [contactsReviewPage, setContactsReviewPage] = useState(1);
  const [continueCompanyFindLoading, setContinueCompanyFindLoading] = useState(false);
  /**
   * After retry: still no matching contact and LLM added no new rows → red "Not available", no Retry.
   * Keyed by collect_index; reset when switching runs.
   */
  const [companyFindUnavailable, setCompanyFindUnavailable] = useState(() => ({}));
  const [setupIntegration, setSetupIntegration] = useState(null);
  const [gmailSetupOpen, setGmailSetupOpen] = useState(false);
  const [gmailForm, setGmailForm] = useState({
    clientId: "",
    clientSecret: "",
    redirectUri: "",
  });
  const [gmailSetupBusy, setGmailSetupBusy] = useState(false);
  const [gmailSetupErr, setGmailSetupErr] = useState("");
  const [testSendBusy, setTestSendBusy] = useState(false);
  const [analyzerRows, setAnalyzerRows] = useState([]);
  const [analyzerLoading, setAnalyzerLoading] = useState(false);
  const [analyzerRowBusy, setAnalyzerRowBusy] = useState(() => ({}));
  const [analyzerBulkBusy, setAnalyzerBulkBusy] = useState(false);
  const [analyzerBulkNote, setAnalyzerBulkNote] = useState("");
  const [analyzerPage, setAnalyzerPage] = useState(1);
  /** false = Not verified → No history → History detected (matches API); true = reversed */
  const [analyzerGmailHistorySortDesc, setAnalyzerGmailHistorySortDesc] = useState(false);

  const gmailSendReady = setupIntegration?.gmail_send_ready === true;

  const contactsVisible = useMemo(() => filterShadowNoEmailContacts(contacts), [contacts]);

  useEffect(() => {
    if (!selectedRun) setRunDetailsHydratedId(null);
  }, [selectedRun]);

  const contactAnalyzerNavVisible = Boolean(
    gmailSendReady && selectedRun && Array.isArray(contactsVisible) && contactsVisible.length > 0,
  );

  const visibleMainNavItems = useMemo(
    () =>
      MAIN_NAV.filter(
        (item) => item.value !== "contact-analyzer" || contactAnalyzerNavVisible,
      ),
    [contactAnalyzerNavVisible],
  );

  const analyzerRowsSorted = useMemo(() => {
    const rows = analyzerRows.slice();
    const badgeRank = (st) => {
      if (st == null) return 0;
      if (st === "no_history") return 1;
      if (st === "history_detected") return 2;
      return 3;
    };
    rows.sort((a, b) => {
      const ra = badgeRank(a.gmail_history_status);
      const rb = badgeRank(b.gmail_history_status);
      const primary = analyzerGmailHistorySortDesc ? rb - ra : ra - rb;
      if (primary !== 0) return primary;
      return String(a.email_normalized).localeCompare(String(b.email_normalized));
    });
    return rows;
  }, [analyzerRows, analyzerGmailHistorySortDesc]);

  const analyzerPageCount = Math.max(1, Math.ceil(analyzerRowsSorted.length / CONTACT_ANALYZER_PAGE_SIZE));

  const analyzerRowsPage = useMemo(() => {
    const start = (analyzerPage - 1) * CONTACT_ANALYZER_PAGE_SIZE;
    return analyzerRowsSorted.slice(start, start + CONTACT_ANALYZER_PAGE_SIZE);
  }, [analyzerRowsSorted, analyzerPage]);

  useEffect(() => {
    setAnalyzerPage((p) => Math.min(Math.max(1, p), analyzerPageCount));
  }, [analyzerPageCount, analyzerRowsSorted.length]);

  const gmailSetupHintsFromApi = useMemo(() => {
    const raw = setupIntegration?.hints;
    if (!Array.isArray(raw)) return [];
    return raw.filter((h) => String(h).startsWith("Gmail setup:"));
  }, [setupIntegration?.hints]);

  const openGmailSetup = useCallback(() => {
    setGmailSetupErr("");
    setGmailSetupOpen(true);
  }, []);

  const loadSetupIntegration = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/setup/status`, {
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      if (!res.ok) {
        setSetupIntegration(null);
        return;
      }
      setSetupIntegration(await res.json());
    } catch {
      setSetupIntegration(null);
    }
  }, []);

  const loadProjects = useCallback(async (listView, options = {}) => {
    const { signal } = options;
    const v = listView === undefined ? projectView : listView;
    const cached = snapshotReadProjects(v);
    if (cached?.length && !signal?.aborted) {
      setProjects(cached);
      setSelectedProject((prev) => snapshotPickSelectedProject(cached, prev, v));
    }
    setLoading(true);
    setError("");
    try {
      const qs = v === "archived" ? "?archived=true" : "?archived=false";
      const data = await api(`/projects${qs}`, { signal });
      if (signal?.aborted) return;
      snapshotWriteProjects(v, data);
      setProjects(data);
      setSelectedProject((prev) => {
        if (!data.length) return null;
        return snapshotPickSelectedProject(data, prev, v);
      });
    } catch (e) {
      if (signal?.aborted) return;
      setUiError(setError, e);
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [projectView]);

  const continueCompanyFindAllPending = async (runId) => {
    if (!runId) return;
    setError("");
    setContinueCompanyFindLoading(true);
    try {
      await api(`/runs/${runId}/companies/continue-find`, {
        method: "POST",
        timeoutMs: COMPANY_RETRY_FIND_TIMEOUT_MS,
      });
      const data = await api(`/runs/${runId}/companies`);
      setCompaniesPanel(data);
      setCompanyFindUnavailable({});
      refreshRunDetailsInBackground(runId);
    } catch (e) {
      setUiError(setError, e);
    } finally {
      setContinueCompanyFindLoading(false);
    }
  };

  const retryCompanyFind = async (runId, collectIndex) => {
    if (!runId || collectIndex == null) return;
    setError("");
    setCompanyRetryLoading((prev) => ({ ...prev, [collectIndex]: true }));
    try {
      const result = await api(`/runs/${runId}/companies/retry-find`, {
        method: "POST",
        body: { collect_index: collectIndex },
        timeoutMs: COMPANY_RETRY_FIND_TIMEOUT_MS,
      });
      const merged =
        typeof result?.new_contacts_merged === "number"
          ? result.new_contacts_merged
          : typeof result?.newContactsMerged === "number"
            ? result.newContactsMerged
            : 0;
      const data = await api(`/runs/${runId}/companies`);
      setCompaniesPanel(data);
      const rowAfter = data.companies?.find((c) => c.collect_index === collectIndex);
      if (
        (rowAfter?.contact_status === "none" || rowAfter?.contact_status === "no_email") &&
        merged === 0
      ) {
        setCompanyFindUnavailable((prev) => ({ ...prev, [collectIndex]: true }));
      }
      if (rowAfter?.contact_status === "found") {
        setCompanyFindUnavailable((prev) => {
          if (!prev[collectIndex]) return prev;
          const next = { ...prev };
          delete next[collectIndex];
          return next;
        });
      }
      refreshRunDetailsInBackground(runId);
    } catch (e) {
      setUiError(setError, e);
    } finally {
      setCompanyRetryLoading((prev) => {
        const next = { ...prev };
        delete next[collectIndex];
        return next;
      });
    }
  };

  /** Sequential POST /companies/retry-find for «Not found» or «no email» rows (excludes Not available). */
  const retryAllCompanyFindNotFound = async (runId) => {
    if (!runId) return;
    setError("");
    setCompanyRetryAllLoading(true);
    let unavailableAcc = { ...companyFindUnavailable };
    try {
      for (let safety = 0; safety < 500; safety++) {
        const data = await api(`/runs/${runId}/companies`);
        setCompaniesPanel(data);
        const row = data.companies?.find(
          (c) =>
            (c.contact_status === "none" || c.contact_status === "no_email") &&
            !unavailableAcc[c.collect_index],
        );
        if (!row) break;

        const collectIndex = row.collect_index;
        setCompanyRetryLoading((prev) => ({ ...prev, [collectIndex]: true }));
        try {
          const result = await api(`/runs/${runId}/companies/retry-find`, {
            method: "POST",
            body: { collect_index: collectIndex },
            timeoutMs: COMPANY_RETRY_FIND_TIMEOUT_MS,
          });
          const merged =
            typeof result?.new_contacts_merged === "number"
              ? result.new_contacts_merged
              : typeof result?.newContactsMerged === "number"
                ? result.newContactsMerged
                : 0;
          const dataAfter = await api(`/runs/${runId}/companies`);
          setCompaniesPanel(dataAfter);
          const rowAfter = dataAfter.companies?.find((c) => c.collect_index === collectIndex);
          if (
            (rowAfter?.contact_status === "none" || rowAfter?.contact_status === "no_email") &&
            merged === 0
          ) {
            unavailableAcc = { ...unavailableAcc, [collectIndex]: true };
            setCompanyFindUnavailable(unavailableAcc);
          }
          if (rowAfter?.contact_status === "found") {
            setCompanyFindUnavailable((prev) => {
              if (!prev[collectIndex]) return prev;
              const next = { ...prev };
              delete next[collectIndex];
              unavailableAcc = next;
              return next;
            });
          }
        } catch (e) {
          setUiError(setError, e);
          break;
        } finally {
          setCompanyRetryLoading((prev) => {
            const next = { ...prev };
            delete next[collectIndex];
            return next;
          });
        }
      }
      refreshRunDetailsInBackground(runId);
    } finally {
      setCompanyRetryAllLoading(false);
    }
  };

  const loadRunDetails = async (runId, runRowHint, options = {}) => {
    if (!runId) return null;
    const requestTimeoutMs = options?.requestTimeoutMs ?? API_TIMEOUT_MS;
    const workspaceLite = options?.workspace === "lite";
    // Background polls call this with the same run — do not clear hydration or Contacts/Drafts
    // flash back to snapshot placeholders until the request finishes.
    setRunDetailsHydratedId((prev) => (prev === runId ? prev : null));
    // Instant paint: pick run row from list + local run_cards snapshot so UI does not show the previous run
    // for the whole API round-trip (server restart / slow proxy). Caller may pass runRowHint when state
    // has not flushed yet (e.g. right after setRunsList in an async effect).
    const rowGuess = runRowHint ?? runsList.find((r) => r.id === runId);
    if (rowGuess) {
      setSelectedRun(rowGuess);
      setWorkspace(snapshotMergeWorkspaceFromRunCards(snapshotReadRunCards(runId), rowGuess));
    }
    try {
      const wsPath = workspaceLite ? `/runs/${runId}/workspace-lite` : `/runs/${runId}/workspace`;
      const [run, stepsData, contactsData, draftsData, ws, packetsData] = await Promise.all([
        api(`/runs/${runId}`, { timeoutMs: requestTimeoutMs }),
        api(`/steps/run/${runId}`, { timeoutMs: requestTimeoutMs }),
        api(`/contacts/run/${runId}`, { timeoutMs: requestTimeoutMs }),
        api(`/email-drafts/run/${runId}`, { timeoutMs: requestTimeoutMs }),
        api(wsPath, { timeoutMs: requestTimeoutMs }),
        api(`/asset-packets/run/${runId}`, { timeoutMs: requestTimeoutMs }),
      ]);
      setSelectedRun(run);
      snapshotEnsureRunSetupPrefsSeedFromRun(runId, run);
      setSteps(stepsData);
      setContacts(contactsData);
      setDrafts(draftsData);
      if (workspaceLite) {
        setWorkspace((prev) => {
          const merged = mergeWorkspaceLiteInto(prev, ws);
          if (merged) snapshotWriteRunCards(runId, merged);
          return merged;
        });
      } else {
        setWorkspace(ws);
        if (ws) snapshotWriteRunCards(runId, ws);
      }
      try {
        const cp = (Array.isArray(contactsData) ? contactsData : [])
          .slice(0, MAX_CONTACTS_PANEL_LITE)
          .map(stripContactForPanelLite)
          .filter(Boolean);
        const dp = (Array.isArray(draftsData) ? draftsData : [])
          .map(stripDraftForPanelLite)
          .filter(Boolean);
        snapshotMergeWriteRunPanelLite(runId, { contactsPreview: cp, draftsPreview: dp });
      } catch {
        /* panel lite is best-effort */
      }
      setRunDetailsHydratedId(runId);
      setRunAssetPackets(Array.isArray(packetsData) ? packetsData : []);
      if (!workspaceLite) {
        try {
          const tp = await api("/sending/global-performance", { timeoutMs: requestTimeoutMs });
          setTotalPerformance({
            emails_sent: Number(tp?.emails_sent) || 0,
            emails_sent_24h: Number(tp?.emails_sent_24h) || 0,
          });
        } catch (e) {
          const msg = detailFromApiErrorMessage(e?.message || e);
          console.warn("[Total performance] GET /sending/global-performance failed:", msg);
        }
      }
      return ws;
    } catch (e) {
      setRunDetailsHydratedId(null);
      setUiError(setError, e);
      return null;
    }
  };

  /** Full run bundle without blocking the UI (used after small PATCHes; same long timeouts as setup saves). */
  const refreshRunDetailsInBackground = (runId) => {
    if (!runId) return;
    void loadRunDetails(runId, undefined, {
      requestTimeoutMs: LOAD_RUN_DETAILS_BUNDLE_TIMEOUT_MS,
    }).catch((e) => setUiError(setError, e));
  };

  /** Global asset library: not part of loadRunDetails — fetch when opening draft editor (and similar). */
  const loadAssetsLibrary = useCallback(async () => {
    try {
      const assetsData = await api(`/assets`);
      setAssetsLibrary(Array.isArray(assetsData) ? assetsData : []);
    } catch {
      /* keep previous list if request fails */
    }
  }, []);

  const loadContactAnalyzer = useCallback(async () => {
    const rid = selectedRun?.id;
    if (!rid) {
      setAnalyzerRows([]);
      return;
    }
    setAnalyzerBulkNote("");
    setAnalyzerLoading(true);
    try {
      const data = await api(`/runs/${rid}/contact-analyzer`);
      setAnalyzerRows(Array.isArray(data?.rows) ? data.rows : []);
    } catch (e) {
      setUiError(setError, e);
      setAnalyzerRows([]);
    } finally {
      setAnalyzerLoading(false);
    }
  }, [selectedRun?.id]);

  useEffect(() => {
    if (!editingContact?.id) return;
    const c = contacts.find((x) => x.id === editingContact.id);
    if (c?.email_health === "dead_mailbox") setEditingContact(null);
  }, [contacts, editingContact?.id]);

  useEffect(() => {
    if (!signatureSetupOpen) setSignatureEditorMount(false);
  }, [signatureSetupOpen]);

  useEffect(() => {
    const ac = new AbortController();
    void loadProjects(undefined, { signal: ac.signal });
    return () => ac.abort();
  }, [projectView, loadProjects]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const tp = await api("/sending/global-performance");
        if (!cancelled) {
          setTotalPerformance({
            emails_sent: Number(tp?.emails_sent) || 0,
            emails_sent_24h: Number(tp?.emails_sent_24h) || 0,
          });
        }
      } catch (e) {
        if (!cancelled) {
          const msg = detailFromApiErrorMessage(e?.message || e);
          console.warn("[Total performance] initial fetch failed:", msg);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    void loadSetupIntegration();
  }, [loadSetupIntegration]);

  useEffect(() => {
    if (mainNav === "drafts") void loadSetupIntegration();
  }, [mainNav, loadSetupIntegration]);

  /** One-shot when entering Drafts (not on loadRunDetails poll) so preview labels resolve asset names. */
  useEffect(() => {
    if (mainNav !== "drafts" || !selectedRun?.id) return;
    void loadAssetsLibrary();
  }, [mainNav, selectedRun?.id, loadAssetsLibrary]);

  useEffect(() => {
    if (mainNav === "assets") void loadSetupIntegration();
  }, [mainNav, loadSetupIntegration]);

  useEffect(() => {
    if (mainNav === "contact-analyzer" && selectedRun?.id) void loadContactAnalyzer();
  }, [mainNav, selectedRun?.id, loadContactAnalyzer]);

  useEffect(() => {
    if (mainNav !== "contact-analyzer") return;
    if (!gmailSendReady || contactsVisible.length === 0 || !selectedRun) {
      setMainNav("runs");
    }
  }, [mainNav, gmailSendReady, contactsVisible.length, selectedRun]);

  useEffect(() => {
    try {
      const sp = new URLSearchParams(window.location.search);
      const ok = sp.get("gmail_connected");
      const gerr = sp.get("gmail_error");
      if (!ok && !gerr) return;
      const url = new URL(window.location.href);
      url.searchParams.delete("gmail_connected");
      url.searchParams.delete("gmail_error");
      window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
      void loadSetupIntegration();
      if (gerr) setError(decodeURIComponent(gerr));
      if (ok) setError("");
    } catch {
      /* ignore malformed query */
    }
  }, [loadSetupIntegration]);

  useEffect(() => {
    if (!selectedRun?.id || mainNav !== "companies") {
      setCompaniesPanel(null);
      return;
    }
    const ac = new AbortController();
    setCompaniesLoading(true);
    (async () => {
      try {
        const data = await api(`/runs/${selectedRun.id}/companies`, { signal: ac.signal });
        if (!ac.signal.aborted) setCompaniesPanel(data);
      } catch (e) {
        const msg = String(e?.message || e);
        if (isConsoleOnlyApiFailure(msg)) {
          console.warn("[AiBizOsHumanUI] companies load", msg, e);
        } else {
          setCompaniesPanel(null);
          setError(msg);
        }
      } finally {
        if (!ac.signal.aborted) setCompaniesLoading(false);
      }
    })();
    return () => ac.abort();
  }, [selectedRun?.id, mainNav, steps]);

  useEffect(() => {
    setCompanyFindUnavailable({});
    setCompanyRetryLoading({});
  }, [selectedRun?.id]);

  useEffect(() => {
    if (!selectedProject) return;
    const pid = projectPk(selectedProject);
    const cachedRuns = snapshotReadRuns(pid);
    const orderedCache = Array.isArray(cachedRuns) && cachedRuns.length ? orderRunsOpenFirst(cachedRuns) : [];
    setRunsList(orderedCache);

    const last = snapshotReadLastContext();
    if (orderedCache.length > 0) {
      const targetIdEarly =
        last &&
        last.projectId === pid &&
        last.runId != null &&
        orderedCache.some((r) => r.id === last.runId)
          ? last.runId
          : orderedCache[0].id;
      const runRowEarly = orderedCache.find((r) => r.id === targetIdEarly) ?? orderedCache[0];
      const cardSnapEarly = snapshotReadRunCards(targetIdEarly);
      setSelectedRun(runRowEarly);
      setWorkspace(snapshotMergeWorkspaceFromRunCards(cardSnapEarly, runRowEarly));
    } else {
      setSelectedRun(null);
      setWorkspace(null);
    }

    const ac = new AbortController();
    (async () => {
      try {
        const runs = await api(`/runs/project/${pid}`, { signal: ac.signal });
        const ordered = orderRunsOpenFirst(runs);
        setRunsList(ordered);
        if (ordered.length > 0) {
          const targetId =
            last &&
            last.projectId === pid &&
            last.runId != null &&
            ordered.some((r) => r.id === last.runId)
              ? last.runId
              : ordered[0].id;
          const runRow = ordered.find((r) => r.id === targetId) ?? ordered[0];
          const cardSnap = snapshotReadRunCards(targetId);
          setSelectedRun(runRow);
          setWorkspace(snapshotMergeWorkspaceFromRunCards(cardSnap, runRow));
          await loadRunDetails(targetId, runRow);
        } else {
          setSelectedRun(null);
          setSteps([]);
          setContacts([]);
          setDrafts([]);
          setWorkspace(null);
        }
      } catch (e) {
        if (ac.signal.aborted) return;
        const msg = String(e?.message || e);
        if (isConsoleOnlyApiFailure(msg)) {
          console.warn("[AiBizOsHumanUI] runs list", msg, e);
        } else {
          setRunsList([]);
          setError(msg);
        }
      }
    })();
    return () => ac.abort();
  }, [selectedProject]);

  useEffect(() => {
    const pid = selectedProject ? projectPk(selectedProject) : null;
    const rid =
      selectedProject && selectedRun && selectedRun.project_id === pid ? selectedRun.id : null;
    snapshotWriteLastContext({
      projectId: pid,
      runId: rid,
      mainNav,
      projectView,
    });
  }, [selectedProject, selectedRun?.id, selectedRun?.project_id, mainNav, projectView]);

  useEffect(() => {
    if (!selectedProject) return;
    snapshotWriteRuns(projectPk(selectedProject), runsList);
  }, [runsList, selectedProject]);

  useEffect(() => {
    if (!selectedRun?.id) return;
    const id = selectedRun.id;
    const phase = workspace?.display_phase;
    // Active: inbox/tracking need fresher data. Preparing/Ready: user actions already refetch; slow poll avoids piles of waits.
    const ms =
      phase === "Active" ? 8000 : phase === "Ready" ? 20000 : phase === "Preparing" ? 45000 : 60000;
    const interval = setInterval(() => {
      if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
      // Preparing: full workspace keeps setup_summary / setup_steps in sync with the pipeline; other phases: cheap lite.
      const useLite = phase != null && phase !== "Preparing";
      void loadRunDetails(id, undefined, {
        workspace: useLite ? "lite" : "full",
        requestTimeoutMs: LOAD_RUN_DETAILS_BUNDLE_TIMEOUT_MS,
      });
    }, ms);
    return () => clearInterval(interval);
  }, [selectedRun?.id, workspace?.display_phase]);

  const createProject = async () => {
    const project = await api("/projects", {
      method: "POST",
      body: { name: projectName, type: "outreach" },
    });
    setProjectView("active");
    await loadProjects("active");
    setSelectedProject(project);
  };

  const archiveProject = async (projectId) => {
    if (!window.confirm("Archive this project?\n\nYou can restore it later.")) {
      return;
    }
    try {
      setError("");
      await api(`/projects/${projectId}/archive`, { method: "POST" });
      if (selectedProject?.id === projectId) {
        setSelectedRun(null);
        setSteps([]);
        setContacts([]);
        setDrafts([]);
      }
      await loadProjects();
    } catch (e) {
      setUiError(setError, e);
    }
  };

  const restoreProject = async (projectId) => {
    try {
      setError("");
      await api(`/projects/${projectId}/restore`, { method: "POST" });
      await loadProjects();
    } catch (e) {
      setUiError(setError, e);
    }
  };

  const openRenameProject = (project) => {
    const pid = project?.id ?? project?.project_id;
    if (pid == null || Number.isNaN(Number(pid))) return;
    setRenameProjectId(Number(pid));
    setRenameProjectNameField(String(project.name ?? "").trim() || "");
    setRenameProjectOpen(true);
  };

  const submitRenameProject = async () => {
    if (renameProjectId == null) return;
    const name = renameProjectNameField.trim();
    if (!name) return;
    setRenameProjectSaving(true);
    setError("");
    try {
      await api(`/projects/${renameProjectId}`, { method: "PATCH", body: { name } });
      setRenameProjectOpen(false);
      setRenameProjectId(null);
      setRenameProjectNameField("");
      await loadProjects();
    } catch (e) {
      setUiError(setError, e);
    } finally {
      setRenameProjectSaving(false);
    }
  };

  const canSubmitNewRun =
    !!selectedProject &&
    newRunForm.name.trim().length > 0 &&
    newRunForm.segment.trim().length > 0 &&
    newRunForm.outreach_brief.trim().length > 0 &&
    outreachBriefHasOfferOrGoal(newRunForm.outreach_brief);

  const newRunNameDirty = useMemo(() => {
    if (!newRunBaseline) return false;
    return newRunForm.name.trim() !== newRunBaseline.name;
  }, [newRunForm.name, newRunBaseline]);

  const newRunOtherDirty = useMemo(() => {
    if (!newRunBaseline) return false;
    const b = newRunBaseline;
    return (
      newRunForm.notes.trim() !== b.notes ||
      newRunForm.segment.trim() !== b.segment ||
      newRunForm.outreach_brief.trim() !== b.outreach_brief
    );
  }, [newRunForm.notes, newRunForm.segment, newRunForm.outreach_brief, newRunBaseline]);

  const canUpdateRun = Boolean(
    newRunBaseline?.runId &&
      canSubmitNewRun &&
      !newRunNameDirty &&
      newRunOtherDirty,
  );

  const canCreateRunInDialog = Boolean(
    canSubmitNewRun && (!newRunBaseline || newRunNameDirty),
  );

  const integrationInformer = useMemo(
    () => formatSetupIntegrationInformer(setupIntegration),
    [setupIntegration],
  );

  useEffect(() => {
    if (!newRunOpen) {
      setNewRunBaseline(null);
      setNewRunCreateInFlight(false);
      setNewRunUpdateInFlight(false);
    }
  }, [newRunOpen]);

  const createNewRun = async () => {
    if (newRunBaseline && !newRunNameDirty) return;
    if (!selectedProject) {
      setError("Select a project first.");
      return;
    }
    if (!newRunForm.name.trim() || !newRunForm.segment.trim()) {
      setError("Run name and segment are required.");
      return;
    }
    if (!newRunForm.outreach_brief.trim()) {
      setError("Outreach brief is required.");
      return;
    }
    if (!outreachBriefHasOfferOrGoal(newRunForm.outreach_brief)) {
      setError(
        "Outreach brief must include lines starting with Offer: and/or Goal: (see placeholder). " +
          "Labels can use markdown (e.g. **Goal:**). Professional Notes: counts as Notes, not Goal.",
      );
      return;
    }
    try {
      setNewRunCreateInFlight(true);
      setError("");
      const pid = projectPk(selectedProject);
      const run = await api("/runs/start", {
        method: "POST",
        timeoutMs: START_RUN_TIMEOUT_MS,
        body: {
          project_id: pid,
          workflow_name: "generic_outreach",
          input_json: {},
          name: newRunForm.name.trim(),
          notes: newRunForm.notes.trim() || undefined,
          segment: newRunForm.segment.trim(),
          outreach_brief: newRunForm.outreach_brief.trim(),
        },
      });
      setNewRunOpen(false);
      const runs = await api(`/runs/project/${pid}`);
      setRunsList(orderRunsOpenFirst(runs));
      await loadRunDetails(run.id);
      setNewRunForm({
        name: "",
        notes: "",
        segment: "",
        outreach_brief: DEFAULT_OUTREACH_BRIEF,
      });
    } catch (e) {
      const raw = String(e?.message ?? e ?? "");
      const timedOutOrAborted =
        raw.includes("Timed out or cancelled") ||
        (raw.includes("Abort") && (raw.includes("aborted") || raw.includes("cancel")));
      if (timedOutOrAborted) {
        setError(
          "Request timed out or was cancelled while starting the run. The server may still be working — " +
            "refresh the Runs list in a minute. If the new run never appears, try again or check the API logs.",
        );
      } else {
        setUiError(setError, e);
      }
    } finally {
      setNewRunCreateInFlight(false);
    }
  };

  const updateExistingRun = async () => {
    if (!canUpdateRun || !newRunBaseline?.runId) return;
    try {
      setNewRunUpdateInFlight(true);
      setError("");
      const updatedRun = await api(`/runs/${newRunBaseline.runId}/outreach`, {
        method: "PATCH",
        body: {
          notes: newRunForm.notes.trim() || undefined,
          segment: newRunForm.segment.trim(),
          outreach_brief: newRunForm.outreach_brief.trim(),
        },
      });
      setNewRunOpen(false);
      const pid = projectPk(selectedProject);
      setRunsList(orderRunsOpenFirst(await api(`/runs/project/${pid}`)));
      setSelectedRun((prev) =>
        prev && prev.id === updatedRun.id ? { ...prev, ...updatedRun } : prev,
      );
      refreshRunDetailsInBackground(newRunBaseline.runId);
      setNewRunForm({
        name: "",
        notes: "",
        segment: "",
        outreach_brief: DEFAULT_OUTREACH_BRIEF,
      });
    } catch (e) {
      setUiError(setError, e);
    } finally {
      setNewRunUpdateInFlight(false);
    }
  };

  const openRunEditDialog = async (runRow) => {
    if (!runRow?.id || !selectedProject) return;
    try {
      setOpenRunEditLoading(true);
      setError("");
      const run = await api(`/runs/${runRow.id}`);
      const seeded = seedNewRunFormFromRun(run);
      setNewRunForm(seeded);
      setNewRunBaseline({
        runId: run.id,
        name: seeded.name.trim(),
        notes: seeded.notes.trim(),
        segment: seeded.segment.trim(),
        outreach_brief: seeded.outreach_brief.trim(),
      });
      refreshRunDetailsInBackground(run.id);
      setNewRunOpen(true);
    } catch (e) {
      setUiError(setError, e);
    } finally {
      setOpenRunEditLoading(false);
    }
  };

  /** @param {{ prefilledFromSelected?: boolean }} [options] — prefill from current run only for “Continue outreach”; bare “New run” opens an empty form. */
  const openNewRunDialog = useCallback((options = {}) => {
    const prefilled = Boolean(options.prefilledFromSelected) && Boolean(selectedRun?.id);
    if (prefilled) {
      const seeded = seedNewRunFormFromRun(selectedRun);
      setNewRunForm(seeded);
      setNewRunBaseline({
        runId: selectedRun.id,
        name: seeded.name.trim(),
        notes: seeded.notes.trim(),
        segment: seeded.segment.trim(),
        outreach_brief: seeded.outreach_brief.trim(),
      });
    } else {
      setNewRunForm(seedNewRunFormFromRun(null));
      setNewRunBaseline(null);
    }
    setNewRunOpen(true);
  }, [selectedRun]);

  const confirmCloseRun = async () => {
    if (!selectedRun || !selectedProject) return;
    try {
      setError("");
      const closedId = selectedRun.id;
      await api(`/runs/${closedId}/close`, { method: "PATCH" });
      setCloseRunOpen(false);
      const pid = projectPk(selectedProject);
      const runs = await api(`/runs/project/${pid}`);
      const ordered = orderRunsOpenFirst(runs);
      setRunsList(ordered);
      const nextOpen = ordered.find((r) => !r.closed_at);
      await loadRunDetails(nextOpen ? nextOpen.id : closedId);
    } catch (e) {
      setUiError(setError, e);
    }
  };

  const openRunById = async (runId) => {
    setSwitchRunOpen(false);
    await loadRunDetails(runId);
    if (selectedProject) {
      try {
        const pid = projectPk(selectedProject);
        setRunsList(orderRunsOpenFirst(await api(`/runs/project/${pid}`)));
      } catch {
        /* ignore */
      }
    }
  };

  const openRestartDialog = (run) => {
    setRestartDialogRun({
      id: run.id,
      name: (run.name && String(run.name).trim()) || `Run #${run.id}`,
    });
    setRestartDialogOpen(true);
  };

  const closeRestartDialog = () => {
    setRestartDialogOpen(false);
    setRestartDialogRun(null);
  };

  const confirmRestartRun = async () => {
    if (!selectedProject || !restartDialogRun || pendingRestart) return;
    const { id: runId, name: runName } = restartDialogRun;
    setError("");
    setRestartDialogOpen(false);
    setRestartDialogRun(null);
    setPendingRestart({ id: runId, name: runName });
    try {
      const pid = projectPk(selectedProject);
      await api(`/runs/${runId}/restart`, { method: "POST", timeoutMs: RESTART_RUN_TIMEOUT_MS });
      setRunsList(orderRunsOpenFirst(await api(`/runs/project/${pid}`)));
      const ws = await loadRunDetails(runId);
      if (ws) {
        setRunsList((prev) =>
          prev.map((r) =>
            r.id !== runId
              ? r
              : {
                  ...r,
                  display_phase: ws.display_phase,
                  companies_count: ws.setup_summary?.companies_collected ?? r.companies_count,
                  contacts_count: ws.setup_summary?.contacts_found ?? r.contacts_count,
                  emails_sent: ws.performance?.emails_sent ?? r.emails_sent,
                  replies: ws.performance?.replies ?? r.replies,
                  active_threads: ws.performance?.active_threads ?? r.active_threads,
                },
          ),
        );
      }
      void loadSetupIntegration();
    } catch (e) {
      setUiError(setError, e);
    } finally {
      setPendingRestart(null);
    }
  };

  const continueRun = async () => {
    if (!selectedRun) return;
    try {
      setError("");
      const run = await api(`/runs/${selectedRun.id}/continue`, { method: "POST" });
      setSelectedRun((prev) => (prev && prev.id === run.id ? { ...prev, ...run } : prev));
      refreshRunDetailsInBackground(run.id);
    } catch (e) {
      setUiError(setError, e);
    }
  };

  const approveContact = async (contactId) => {
    try {
      setError("");
      const updated = await api(`/contacts/${contactId}/review`, {
        method: "PATCH",
        body: { review_status: "approved" },
      });
      setContacts((prev) => prev.map((c) => (c.id === contactId ? { ...c, ...updated } : c)));
      if (selectedRun) refreshRunDetailsInBackground(selectedRun.id);
    } catch (e) {
      setUiError(setError, e);
      if (selectedRun) refreshRunDetailsInBackground(selectedRun.id);
    }
  };

  const reviewContact = async (id, review_status) => {
    try {
      setError("");
      const updated = await api(`/contacts/${id}/review`, {
        method: "PATCH",
        body: { review_status },
      });
      setContacts((prev) => prev.map((c) => (c.id === id ? { ...c, ...updated } : c)));
      refreshRunDetailsInBackground(selectedRun.id);
    } catch (e) {
      setUiError(setError, e);
    }
  };

  const createDraftForContact = async (contactId) => {
    if (!selectedRun?.id) return;
    setCreateDraftContactId(contactId);
    try {
      setError("");
      const draft = await api(`/contacts/${contactId}/create-draft`, { method: "POST" });
      setDrafts((prev) => {
        const idx = prev.findIndex((d) => d.id === draft.id);
        if (idx >= 0) return prev.map((d, i) => (i === idx ? { ...d, ...draft } : d));
        return [...prev, draft];
      });
      refreshRunDetailsInBackground(selectedRun.id);
    } catch (e) {
      setUiError(setError, e);
    } finally {
      setCreateDraftContactId(null);
    }
  };

  const reviewDraft = async (id, review_status, review_notes) => {
    const idKey = String(id);
    const busyKind =
      review_status === "approved"
        ? review_notes === OUTBOUND_REVIEW_SEND_LATER
          ? "later"
          : "approve"
        : "reject";
    setOutboundDraftReviewBusy((p) => ({ ...p, [idKey]: busyKind }));
    try {
      setError("");
      const body = { review_status };
      if (review_notes !== undefined) body.review_notes = review_notes;
      const updated = await api(`/email-drafts/${id}/review`, {
        method: "PATCH",
        body,
      });
      setDrafts((prev) => prev.map((d) => (d.id === id ? { ...d, ...updated } : d)));
      refreshRunDetailsInBackground(selectedRun.id);
    } catch (e) {
      setUiError(setError, e);
    } finally {
      setOutboundDraftReviewBusy((p) => {
        const next = { ...p };
        delete next[idKey];
        return next;
      });
    }
  };

  const regenerateOutboundDraft = async (draftId) => {
    if (!selectedRun) return;
    const idKey = String(draftId);
    setRegeneratingOutboundDraftIds((p) => ({ ...p, [idKey]: true }));
    try {
      setError("");
      const updated = await api(`/email-drafts/${draftId}/regenerate`, { method: "POST" });
      setDrafts((prev) => prev.map((d) => (d.id === draftId ? { ...d, ...updated } : d)));
      refreshRunDetailsInBackground(selectedRun.id);
    } catch (e) {
      setUiError(setError, e);
    } finally {
      setRegeneratingOutboundDraftIds((p) => {
        const next = { ...p };
        delete next[idKey];
        return next;
      });
    }
  };

  const deleteDeadMailboxDraft = async (draftId) => {
    if (!selectedRun) return;
    try {
      setError("");
      await api(`/email-drafts/${draftId}`, { method: "DELETE" });
      if (editDraft?.id === draftId) setEditDraft(null);
      setDrafts((prev) => prev.filter((d) => d.id !== draftId));
      refreshRunDetailsInBackground(selectedRun.id);
    } catch (e) {
      setUiError(setError, e);
    }
  };

  const sendDraft = async (draftId) => {
    if (!selectedRun) return;
    if (!gmailSendReady) {
      openGmailSetup();
      return;
    }
    const idKey = String(draftId);
    setSendingOutboundDraftIds((p) => ({ ...p, [idKey]: true }));
    try {
      setError("");
      await api(`/sending/drafts/${draftId}/send`, { method: "POST" });
      refreshRunDetailsInBackground(selectedRun.id);
    } catch (e) {
      setUiError(setError, e);
      void loadSetupIntegration();
    } finally {
      setSendingOutboundDraftIds((p) => {
        const next = { ...p };
        delete next[idKey];
        return next;
      });
    }
  };

  const sendAllApproved = async () => {
    if (!selectedRun) return;
    if (!gmailSendReady) {
      openGmailSetup();
      return;
    }
    setSendAllApprovedBusy(true);
    try {
      setError("");
      await api(`/sending/runs/${selectedRun.id}/send`, { method: "POST" });
      refreshRunDetailsInBackground(selectedRun.id);
    } catch (e) {
      setUiError(setError, e);
      void loadSetupIntegration();
    } finally {
      setSendAllApprovedBusy(false);
    }
  };

  /** Sends first sendable approved draft to the same mailbox as From (self-test; no DB updates). */
  const testSendFirstApproved = async () => {
    if (!selectedRun) return;
    if (!gmailSendReady) {
      openGmailSetup();
      return;
    }
    setTestSendBusy(true);
    try {
      setError("");
      await api(`/sending/runs/${selectedRun.id}/mock-send-preview`, { method: "POST" });
    } catch (e) {
      setUiError(setError, e);
      void loadSetupIntegration();
    } finally {
      setTestSendBusy(false);
    }
  };

  const verifyContactAnalyzerOne = async (emailNormalized) => {
    if (!selectedRun?.id) return;
    const runId = selectedRun.id;
    setAnalyzerBulkNote("");
    setAnalyzerRowBusy((m) => ({ ...m, [emailNormalized]: true }));
    try {
      setError("");
      await api(`/runs/${runId}/contact-analyzer/verify`, {
        method: "POST",
        body: { email_normalized: emailNormalized },
        timeoutMs: CONTACT_ANALYZER_VERIFY_ONE_TIMEOUT_MS,
      });
    } catch (e) {
      setUiError(setError, e);
    } finally {
      try {
        await loadContactAnalyzer();
        refreshRunDetailsInBackground(runId);
      } catch {
        /* refresh failed — user can reopen the tab */
      }
      setAnalyzerRowBusy((m) => ({ ...m, [emailNormalized]: false }));
    }
  };

  const importContactAnalyzerInbox = async (emailNormalized) => {
    if (!selectedRun?.id) return;
    const runId = selectedRun.id;
    setAnalyzerBulkNote("");
    setAnalyzerRowBusy((m) => ({ ...m, [emailNormalized]: true }));
    try {
      setError("");
      await api(`/runs/${runId}/contact-analyzer/import-inbox`, {
        method: "POST",
        body: { email_normalized: emailNormalized },
        timeoutMs: CONTACT_ANALYZER_IMPORT_INBOX_TIMEOUT_MS,
      });
    } catch (e) {
      setUiError(setError, e);
    } finally {
      try {
        await loadContactAnalyzer();
        refreshRunDetailsInBackground(runId);
      } catch {
        /* ignore */
      }
      setAnalyzerRowBusy((m) => ({ ...m, [emailNormalized]: false }));
    }
  };

  const verifyContactAnalyzerAll = async () => {
    if (!selectedRun?.id) return;
    const runId = selectedRun.id;
    setAnalyzerBulkBusy(true);
    setAnalyzerBulkNote("");
    let bulkNote = "";
    try {
      setError("");
      const res = await api(`/runs/${runId}/contact-analyzer/verify-all`, {
        method: "POST",
        timeoutMs: CONTACT_ANALYZER_VERIFY_ALL_TIMEOUT_MS,
      });
      const n = res?.verified ?? 0;
      const fails = Array.isArray(res?.failures) ? res.failures : [];
      if (fails.length) {
        bulkNote = `Verified ${n}. Issues: ${fails.map((f) => `${f.email}: ${f.error}`).join("; ")}`;
      } else {
        bulkNote = n > 0 ? `Verified ${n} address(es).` : "Nothing left to verify.";
      }
    } catch (e) {
      setUiError(setError, e);
      bulkNote =
        "Request failed or timed out — refreshing the list. If verification finished on the server, statuses will appear below.";
    } finally {
      try {
        await loadContactAnalyzer();
        refreshRunDetailsInBackground(runId);
      } catch {
        /* ignore */
      }
      setAnalyzerBulkNote(bulkNote);
      setAnalyzerBulkBusy(false);
    }
  };

  const connectGmailOAuth = async () => {
    setGmailSetupBusy(true);
    setGmailSetupErr("");
    try {
      setError("");
      const cid = gmailForm.clientId.trim();
      const sec = gmailForm.clientSecret.trim();
      const ruri = gmailForm.redirectUri.trim();
      const hasFormCreds = Boolean(cid && sec);
      const serverHasClient = setupIntegration?.gmail_client_configured === true;
      if (!hasFormCreds && !serverHasClient) {
        setGmailSetupErr(
          "Add OAuth Client ID and Client secret below (saved to backend .env when allowed), " +
            "or set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in backend/.env, restart the API, then click Connect again with empty fields.",
        );
        return;
      }
      if (cid && sec) {
        if (!setupIntegration?.allow_env_write) {
          throw new Error(
            "Saving credentials from the browser is disabled. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to backend/.env, " +
              "restart the API, then use Connect Gmail (or enable ALLOW_SETUP_ENV_WRITE for local dev).",
          );
        }
        await api("/setup/gmail-credentials", {
          method: "POST",
          body: {
            client_id: cid,
            client_secret: sec,
            ...(ruri ? { redirect_uri: ruri } : {}),
          },
        });
        await loadSetupIntegration();
      }
      const startRes = await api("/oauth/google/start", {
        method: "POST",
        body: {
          public_origin: window.location.origin,
          return_path: window.location.pathname || "/",
        },
      });
      const authUrl = startRes?.authorization_url;
      if (!authUrl || typeof authUrl !== "string") {
        throw new Error(
          "API did not return authorization_url — ensure the backend is running and GET/POST /oauth/google/start is mounted.",
        );
      }
      window.location.assign(authUrl);
    } catch (e) {
      const raw = formatApiError(e);
      const friendly = detailFromApiErrorMessage(raw);
      setGmailSetupErr(friendly);
      setError(friendly);
    } finally {
      setGmailSetupBusy(false);
    }
  };

  const openEditDraft = (d) => {
    setApplyAssetsToAllPendingDrafts(false);
    setEditDraft(d);
    setDraftForm({
      subject: d.subject ?? "",
      body: d.body ?? "",
      attached_asset_ids: normalizeAttachedAssetIds(d.attached_asset_ids),
    });
    void (async () => {
      try {
        const packetsData = await api(`/asset-packets/run/${selectedRun.id}`);
        setRunAssetPackets(Array.isArray(packetsData) ? packetsData : []);
      } catch {
        /* keep previous packets if request fails */
      }
      await loadAssetsLibrary();
    })();
  };

  const saveEditDraft = async () => {
    if (!editDraft || !selectedRun || editDraftSaving) return;
    const runId = selectedRun.id;
    const draftId = editDraft.id;
    const applyAll = applyAssetsToAllPendingDrafts;
    setEditDraftSaving(true);
    let updatedDraft = null;
    try {
      setError("");
      updatedDraft = await api(`/email-drafts/${draftId}/edit`, {
        method: "PATCH",
        body: {
          subject: draftForm.subject,
          body: draftForm.body,
          attached_asset_ids: draftForm.attached_asset_ids,
          apply_assets_to_pending_drafts: applyAll,
        },
        timeoutMs: applyAll ? 120000 : 60000,
      });
    } catch (e) {
      setUiError(setError, e);
      return;
    } finally {
      setEditDraftSaving(false);
    }
    setEditDraft(null);
    if (updatedDraft && !applyAll) {
      setDrafts((prev) => prev.map((d) => (d.id === draftId ? { ...d, ...updatedDraft } : d)));
    }
    refreshRunDetailsInBackground(runId);
  };

  const openSignatureSetup = () => {
    setSignatureFormHtml(selectedRun?.sender_signature_html ?? "");
    setSignatureEditorKey((k) => k + 1);
    setSignatureSetupOpen(true);
    setSignatureEditorMount(false);
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        setSignatureEditorMount(true);
      });
    });
  };

  const openPromptSetup = () => {
    setPromptSetupSaving(false);
    setPromptSetupText(getPromptSetupEditorInitialText(selectedRun));
    setPromptSetupOpen(true);
  };

  const savePromptSetup = async () => {
    if (!selectedRun?.id) return;
    const rid = selectedRun.id;
    try {
      setPromptSetupSaving(true);
      setError("");
      const updated = await api(`/runs/${rid}/prompt-setup`, {
        method: "PATCH",
        body: { prompt_setup_text: promptSetupText },
        timeoutMs: RUN_SETUP_PATCH_TIMEOUT_MS,
      });
      snapshotWriteRunSetupPrefs(rid, {
        prompt_setup_saved: promptSetupText.trim().length > 0,
      });
      setRunSetupPrefsRev((x) => x + 1);
      setSelectedRun((prev) => (prev && prev.id === rid ? { ...prev, ...updated } : prev));
      setPromptSetupOpen(false);
      refreshRunDetailsInBackground(rid);
    } catch (e) {
      setUiError(setError, e);
    } finally {
      setPromptSetupSaving(false);
    }
  };

  const saveSignatureSetup = async () => {
    if (!selectedRun?.id) return;
    const rid = selectedRun.id;
    try {
      setSignatureSetupSaving(true);
      setError("");
      const updated = await api(`/runs/${rid}/signature`, {
        method: "PATCH",
        body: { signature_html: signatureFormHtml },
        timeoutMs: RUN_SETUP_PATCH_TIMEOUT_MS,
      });
      snapshotWriteRunSetupPrefs(rid, {
        sender_signature_configured: runSignatureHasMeaningfulContent(signatureFormHtml),
      });
      setRunSetupPrefsRev((x) => x + 1);
      setSelectedRun((prev) => (prev && prev.id === rid ? { ...prev, ...updated } : prev));
      setSignatureSetupOpen(false);
      refreshRunDetailsInBackground(rid);
    } catch (e) {
      setUiError(setError, e);
    } finally {
      setSignatureSetupSaving(false);
    }
  };

  const contactsMatchingSearch = useMemo(() => {
    return contactsVisible.filter((c) => {
      const q = search.trim().toLowerCase();
      return (
        !q || [c.company, c.name, c.role, c.email].some((v) => (v || "").toLowerCase().includes(q))
      );
    });
  }, [contactsVisible, search]);

  const draftsVisibleInReview = useMemo(
    () => (Array.isArray(drafts) ? drafts.filter((d) => !isOutboundDraftClosedForReview(d)) : []),
    [drafts],
  );

  const draftsMatchingSearch = useMemo(() => {
    return draftsVisibleInReview.filter((d) => {
      const q = search.trim().toLowerCase();
      return (
        !q || [d.company, d.to_email, d.subject, d.body].some((v) => (v || "").toLowerCase().includes(q))
      );
    });
  }, [draftsVisibleInReview, search]);

  const draftReviewTabCounts = useMemo(() => {
    const pendingReview = draftsMatchingSearch.filter(
      (d) => d.review_status === "pending" || d.review_status === "rejected",
    ).length;
    const approved = draftsMatchingSearch.filter((d) =>
      ["approved", "edited"].includes(d.review_status),
    ).length;
    return { pendingReview, approved };
  }, [draftsMatchingSearch]);

  const liveDraftReviewCounts = useMemo(
    () => ({
      pendingReview: draftReviewTabCounts.pendingReview,
      approved: draftReviewTabCounts.approved,
    }),
    [draftReviewTabCounts],
  );

  const filteredDrafts = useMemo(() => {
    return draftsMatchingSearch.filter((d) => {
      const isApprovedBucket = ["approved", "edited"].includes(d.review_status);
      const isPendingReviewBucket = d.review_status === "pending" || d.review_status === "rejected";
      if (draftReviewTab === "approved") return isApprovedBucket;
      return isPendingReviewBucket;
    });
  }, [draftsMatchingSearch, draftReviewTab]);

  const contactHasBadEmailHealth = (c) =>
    c.email_health === "dead_mailbox" || c.email_health === "bounced";

  const contactHasEmail = (c) => Boolean((c?.email || "").trim());

  /** Normalized company name only — for “touched” badge across split website-based groups. */
  const contactCompanyNameOnlyKey = (c) =>
    (c.company || "")
      .trim()
      .toLowerCase()
      .replace(/\s+/g, " ");

  /** Stable key to group review cards by company (no backend merge). */
  const contactCompanyGroupKey = (c) => {
    const co = contactCompanyNameOnlyKey(c);
    let w = (c.website || "").trim().toLowerCase();
    w = w.replace(/^https?:\/\//, "").replace(/^www\./, "");
    w = w.replace(/\/+$/, "");
    if (!co && !w) return `__single_${c.id}`;
    return `${co}\x1f${w}`;
  };

  /** Same company header only when review_status matches (per-tab list is already same delivery bucket). */
  const groupContactsByCompanyAndReviewStatus = (list) => {
    const keyToContacts = new Map();
    for (const c of list) {
      const k = `${contactCompanyGroupKey(c)}\x1f${c.review_status}`;
      if (!keyToContacts.has(k)) keyToContacts.set(k, []);
      keyToContacts.get(k).push(c);
    }
    const seen = new Set();
    const groups = [];
    for (const c of list) {
      const k = `${contactCompanyGroupKey(c)}\x1f${c.review_status}`;
      if (seen.has(k)) continue;
      seen.add(k);
      groups.push(keyToContacts.get(k));
    }
    return groups;
  };

  const pickGroupContactCardClass = (group) => {
    const rank = (c) => {
      if (c.email_health === "dead_mailbox") return 0;
      if (c.email_health === "bounced") return 1;
      if (c.review_status === "rejected") return 2;
      if (c.review_status === "pending") return 3;
      return 4;
    };
    const worst = [...group].sort((a, b) => rank(a) - rank(b))[0];
    return contactCardClass(worst);
  };

  const contactById = useMemo(() => new Map(contacts.map((c) => [c.id, c])), [contacts]);
  const draftByContactId = useMemo(() => {
    const m = new Map();
    for (const d of drafts) {
      if (d.contact_id != null) m.set(d.contact_id, d);
    }
    return m;
  }, [drafts]);

  const approvedContactsReachable = contactsVisible.filter(
    (c) =>
      ["approved", "edited"].includes(c.review_status) &&
      !contactHasBadEmailHealth(c) &&
      contactHasEmail(c),
  ).length;
  const approvedDrafts = draftsVisibleInReview.filter((d) =>
    ["approved", "edited"].includes(d.review_status),
  ).length;
  const pendingContacts = contactsVisible.filter((c) => c.review_status === "pending").length;

  const contactsByReviewTab = useMemo(() => {
    const buckets = {
      pending: [],
      approved: [],
      rejected: [],
      bounced: [],
      dead_mailbox: [],
      no_email: [],
    };
    for (const c of contactsMatchingSearch) {
      buckets[contactReviewTabBucket(c)].push(c);
    }
    return buckets;
  }, [contactsMatchingSearch]);

  const liveContactReviewCounts = useMemo(
    () => ({
      pending: contactsByReviewTab.pending.length,
      approved: contactsByReviewTab.approved.length,
      rejected: contactsByReviewTab.rejected.length,
      bounced: contactsByReviewTab.bounced.length,
      dead_mailbox: contactsByReviewTab.dead_mailbox.length,
      no_email: contactsByReviewTab.no_email.length,
    }),
    [contactsByReviewTab],
  );

  const innerTabSnap = useMemo(() => {
    if (!selectedRun?.id) return null;
    return snapshotReadInnerTabCounts(selectedRun.id);
  }, [selectedRun?.id]);

  const displayContactReviewCounts = useMemo(() => {
    const live = liveContactReviewCounts;
    if (runDetailsHydratedId === selectedRun?.id) return live;
    return mergeContactReviewSnap(innerTabSnap?.contacts, live);
  }, [liveContactReviewCounts, runDetailsHydratedId, selectedRun?.id, innerTabSnap?.contacts]);

  const displayDraftReviewCounts = useMemo(() => {
    const live = liveDraftReviewCounts;
    if (runDetailsHydratedId === selectedRun?.id) return live;
    return mergeDraftReviewSnap(innerTabSnap?.drafts, live);
  }, [liveDraftReviewCounts, runDetailsHydratedId, selectedRun?.id, innerTabSnap?.drafts]);

  const contactsRunHydrated =
    Boolean(selectedRun?.id) && runDetailsHydratedId === selectedRun?.id;
  const reviewContactsSnapModeVal = useMemo(
    () => reviewContactsSnapMode(innerTabSnap?.contacts),
    [innerTabSnap?.contacts],
  );
  const reviewDraftsSnapModeVal = useMemo(
    () => reviewDraftsSnapMode(innerTabSnap?.drafts),
    [innerTabSnap?.drafts],
  );

  const runPanelLiteHuman = useMemo(
    () => (selectedRun?.id ? snapshotReadRunPanelLite(selectedRun.id) : null),
    [selectedRun?.id, runDetailsHydratedId],
  );

  const contactsPanelLiteFiltered = useMemo(() => {
    const list = runPanelLiteHuman?.contactsPreview || [];
    return list.filter((c) => contactReviewTabBucket(c) === contactReviewTab);
  }, [runPanelLiteHuman?.contactsPreview, contactReviewTab]);

  const draftsPanelLiteFiltered = useMemo(() => {
    const list = runPanelLiteHuman?.draftsPreview || [];
    if (!list.length) return [];
    if (draftReviewTab === "pending") {
      return list.filter((d) => d.review_status === "pending" || d.review_status === "rejected");
    }
    return list.filter((d) => ["approved", "edited"].includes(d.review_status));
  }, [runPanelLiteHuman?.draftsPreview, draftReviewTab]);

  useEffect(() => {
    if (!selectedRun?.id || runDetailsHydratedId !== selectedRun.id) return;
    snapshotMergeWriteInnerTabs(selectedRun.id, {
      contacts: liveContactReviewCounts,
      drafts: liveDraftReviewCounts,
    });
  }, [selectedRun?.id, runDetailsHydratedId, liveContactReviewCounts, liveDraftReviewCounts]);

  /**
   * Group order used to follow raw contact id order. If companies interleave by id (Acme, Beta, Acme),
   * approving the first Acme left the second Acme after Beta — the card “jumped” to the end. Sort groups by
   * stable company key, then min contact id in the group.
   */
  const contactReviewTabGroups = useMemo(() => {
    const list = contactsByReviewTab[contactReviewTab];
    const groups = groupContactsByCompanyAndReviewStatus(list);
    return [...groups].sort((a, b) => {
      const keyA = contactCompanyGroupKey(a[0]);
      const keyB = contactCompanyGroupKey(b[0]);
      const cmp = keyA.localeCompare(keyB);
      if (cmp !== 0) return cmp;
      return Math.min(...a.map((c) => c.id)) - Math.min(...b.map((c) => c.id));
    });
  }, [contactsByReviewTab, contactReviewTab]);

  const companiesListForPage = companiesPanel?.companies;
  const companiesPageCount = Math.max(
    1,
    Math.ceil((companiesListForPage?.length ?? 0) / WORKSPACE_TABLE_PAGE_SIZE),
  );
  const companiesPageSlice = useMemo(() => {
    const list = companiesListForPage ?? [];
    const start = (companiesPage - 1) * WORKSPACE_TABLE_PAGE_SIZE;
    return list.slice(start, start + WORKSPACE_TABLE_PAGE_SIZE);
  }, [companiesListForPage, companiesPage]);

  const contactsReviewPageCount = Math.max(
    1,
    Math.ceil(contactReviewTabGroups.length / WORKSPACE_TABLE_PAGE_SIZE),
  );

  const contactReviewGroupsPage = useMemo(() => {
    const start = (contactsReviewPage - 1) * WORKSPACE_TABLE_PAGE_SIZE;
    return contactReviewTabGroups.slice(start, start + WORKSPACE_TABLE_PAGE_SIZE);
  }, [contactReviewTabGroups, contactsReviewPage]);

  useEffect(() => {
    setCompaniesPage((p) => Math.min(Math.max(1, p), companiesPageCount));
  }, [companiesPageCount, companiesListForPage]);

  useEffect(() => {
    setContactsReviewPage((p) => Math.min(Math.max(1, p), contactsReviewPageCount));
  }, [contactsReviewPageCount, contactReviewTabGroups]);

  useEffect(() => {
    setCompaniesPage(1);
    setContactsReviewPage(1);
  }, [selectedRun?.id, search]);

  useEffect(() => {
    setContactsReviewPage(1);
  }, [contactReviewTab]);

  useEffect(() => {
    setDraftReviewTab("pending");
  }, [selectedRun?.id]);

  const draftsPending = filteredDrafts.filter((d) => d.review_status === "pending");
  const draftsApprovedList = filteredDrafts.filter((d) =>
    ["approved", "edited"].includes(d.review_status),
  );
  const draftsRejectedList = filteredDrafts.filter((d) => d.review_status === "rejected");

  const canContinue = approvedContactsReachable > 0;

  /** Share of outbound drafts with a terminal delivery outcome (for “next wave” gating). */
  const outreachBatchProgress = useMemo(() => {
    if (!drafts.length) return { fraction: 0, done: 0, total: 0 };
    const terminal = new Set(["sent", "replied", "bounced", "dead_mailbox", "failed"]);
    const done = drafts.filter((d) => {
      const st = String(d.tracking_status || d.status || "").toLowerCase();
      return terminal.has(st);
    }).length;
    return { fraction: done / drafts.length, done, total: drafts.length };
  }, [drafts]);

  const totalPerformance24hUi = useMemo(
    () => totalPerformance24hBand(totalPerformance?.emails_sent_24h ?? 0),
    [totalPerformance?.emails_sent_24h],
  );

  const promptSetupSavedFilled = useMemo(() => {
    const rid = selectedRun?.id;
    if (rid == null) return false;
    const snap = snapshotReadRunSetupPrefs(rid);
    if (snap) return Boolean(snap.prompt_setup_saved);
    if (typeof selectedRun?.prompt_setup_saved === "boolean") return selectedRun.prompt_setup_saved;
    const raw = selectedRun?.context_json?.[PROMPT_SETUP_STORAGE_KEY];
    return typeof raw === "string" && raw.trim().length > 0;
  }, [
    selectedRun?.id,
    selectedRun?.context_json,
    selectedRun?.prompt_setup_saved,
    runDetailsHydratedId,
    runSetupPrefsRev,
  ]);

  const signatureSetupFilled = useMemo(() => {
    const rid = selectedRun?.id;
    if (rid == null) return false;
    const snap = snapshotReadRunSetupPrefs(rid);
    if (snap) return Boolean(snap.sender_signature_configured);
    if (typeof selectedRun?.sender_signature_configured === "boolean") {
      return selectedRun.sender_signature_configured;
    }
    const html = selectedRun?.sender_signature_html ?? workspace?.sender_signature_html ?? "";
    return runSignatureHasMeaningfulContent(html);
  }, [
    selectedRun?.id,
    selectedRun?.sender_signature_html,
    selectedRun?.sender_signature_configured,
    workspace?.sender_signature_html,
    runDetailsHydratedId,
    runSetupPrefsRev,
  ]);

  /** Shown in Review workspace (Contacts) above “N contacts left to review”, not in Run setup. */
  const approveContactsContinueCta = useMemo(() => {
    if (!selectedRun?.id) return null;
    if (workspace?.display_phase !== "Preparing") return null;
    if (selectedRun.status === "needs_review") {
      return {
        label: "Approve contacts to continue",
        disabled: approvedContactsReachable === 0,
        hint:
          approvedContactsReachable === 0
            ? "Approve or edit at least one reachable contact first (bounced / dead mailbox do not count)."
            : null,
        onClick: () => void continueRun(),
      };
    }
    return {
      label: "Approve contacts to continue",
      disabled: true,
      hint: "Run setup is in progress.",
      onClick: null,
    };
  }, [selectedRun?.id, selectedRun?.status, workspace?.display_phase, approvedContactsReachable, continueRun]);

  const primaryCta = useMemo(() => {
    if (!selectedRun?.id) return null;
    const phase = workspace?.display_phase;
    if (phase === "Closed") return null;
    if (phase === "Preparing") {
      return null;
    }
    if (phase === "Ready") {
      return {
        label: "Start outreach",
        disabled: false,
        hint: null,
        onClick: () => setMainNav("drafts"),
      };
    }
    if (phase === "Active") {
      const { fraction, done, total } = outreachBatchProgress;
      const halfDone = total > 0 && fraction >= 0.5;
      return {
        label: "Continue outreach",
        disabled: !halfDone,
        hint: !halfDone
          ? total === 0
            ? "No drafts on this run yet — send and track the current batch first."
            : `Enable after ≥50% of outbound emails are resolved (${done}/${total} · ${Math.round(fraction * 100)}%). Counts: sent, replied, bounced, failed, dead mailbox.`
          : "Opens Runs and New run — a new search & batch in this project (current run stays in the list).",
        onClick: () => {
          setMainNav("runs");
          openNewRunDialog({ prefilledFromSelected: true });
        },
      };
    }
    return null;
  }, [selectedRun, workspace?.display_phase, outreachBatchProgress, openNewRunDialog]);

  const contactCardClass = (c) => {
    if (contactHasBadEmailHealth(c)) {
      return "rounded-2xl border-2 border-red-700/50 bg-red-950/10 shadow-none dark:border-red-700/40 dark:bg-red-950/20";
    }
    const rs = c.review_status;
    if (["approved", "edited"].includes(rs)) {
      return "rounded-2xl border-2 border-green-600/40 bg-green-500/5 shadow-none";
    }
    if (rs === "pending") {
      return "rounded-2xl border-2 border-muted bg-muted/25 shadow-none";
    }
    return "rounded-2xl border-2 border-border shadow-none";
  };

  const draftCardClass = (d) => {
    const st = d.tracking_status ?? d.status;
    if (st === "sent") {
      return "rounded-2xl border-2 border-green-600/40 bg-green-500/5 shadow-none";
    }
    if (st === "failed") {
      return "rounded-2xl border-2 border-destructive/45 bg-destructive/5 shadow-none";
    }
    if (st === "sending") {
      return "rounded-2xl border-2 border-blue-500/40 bg-blue-500/5 shadow-none";
    }
    if (st === "replied") {
      return "rounded-2xl border-2 border-emerald-600/40 bg-emerald-500/5 shadow-none";
    }
    if (st === "bounced") {
      return "rounded-2xl border-2 border-orange-500/40 bg-orange-500/5 shadow-none";
    }
    if (st === "dead_mailbox") {
      return "rounded-2xl border-2 border-red-700/40 bg-red-600/5 shadow-none";
    }
    const rs = d.review_status;
    if (["approved", "edited"].includes(rs)) {
      return "rounded-2xl border-2 border-green-600/40 bg-green-500/5 shadow-none";
    }
    if (rs === "pending") {
      return "rounded-2xl border-2 border-muted bg-muted/25 shadow-none";
    }
    return "rounded-2xl border-2 border-border shadow-none";
  };

  const canSendDraft = (d) =>
    ["approved", "edited"].includes(d.review_status) &&
    !!(d.to_email || "").trim() &&
    !["sent", "sending"].includes(d.status);

  const canRegenerateOutboundDraft = (d) =>
    ["draft", "failed"].includes(d.status) && !["sent", "sending"].includes(d.status);

  const renderContactBlock = (contact, { grouped }) => {
    const rs = contact.review_status;
    const isPending = rs === "pending";
    const isRejected = rs === "rejected";
    const isReplacement = contact.source_json?.source === "replacement_search";
    const badEmailHealth = contactHasBadEmailHealth(contact);
    const isDeadMailbox = contact.email_health === "dead_mailbox";
    const hasEmail = contactHasEmail(contact);
    return (
      <div>
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              {badEmailHealth ? (
                <CircleAlert className="h-5 w-5 shrink-0 text-red-600 dark:text-red-400" aria-hidden />
              ) : null}
              {!grouped ? (
                <div className="text-lg font-semibold">{contact.company || "Unnamed company"}</div>
              ) : null}
              {isReplacement ? (
                <Badge variant="default" className="bg-violet-600 hover:bg-violet-600">
                  Replacement
                </Badge>
              ) : null}
              {!badEmailHealth ? <StatusBadge value={contact.status} /> : null}
              {!badEmailHealth ? <StatusBadge value={contact.review_status} /> : null}
              {badEmailHealth ? (
                <Badge variant="destructive" className="font-normal text-xs">
                  {contact.email_health === "dead_mailbox"
                    ? "Dead mailbox"
                    : contact.email_health === "bounced"
                      ? "Bounced"
                      : pretty(contact.email_health)}
                </Badge>
              ) : null}
              {!contact.email ? <Badge variant="destructive">No email</Badge> : null}
              {(contact.confidence || "").toLowerCase() === "low" ? (
                <Badge variant="secondary">Low confidence</Badge>
              ) : null}
              {!badEmailHealth && contact.email_health && contact.email_health !== "unknown" ? (
                <Badge variant="outline" className="text-xs">
                  Email: {pretty(contact.email_health)}
                </Badge>
              ) : null}
            </div>
            <div className="text-sm text-muted-foreground">
              {contact.name || "No name"} · {contactRoleFromPayload(contact) || "No role"}
            </div>
            <div className="text-sm">{contact.email || "No email"}</div>
            <div className="text-xs text-muted-foreground">{contact.website || "No website"}</div>
          </div>
          <div className="flex w-full shrink-0 flex-wrap items-center justify-end gap-2 lg:w-auto lg:flex-nowrap">
            {!isDeadMailbox ? (
              <Button
                size="sm"
                variant="outline"
                onClick={() =>
                  setEditingContact({
                    id: contact.id,
                    name: contact.name ?? "",
                    role: contactRoleFromPayload(contact),
                    email: contact.email ?? "",
                  })
                }
              >
                <Pencil className="mr-1 h-3 w-3" /> Edit
              </Button>
            ) : null}
            {isPending ? (
              <>
                {hasEmail ? (
                  <Button size="sm" onClick={() => approveContact(contact.id)}>
                    Approve
                  </Button>
                ) : null}
                {!isDeadMailbox ? (
                  <Button size="sm" variant="outline" onClick={() => reviewContact(contact.id, "rejected")}>
                    Reject
                  </Button>
                ) : null}
              </>
            ) : null}
            {!isPending && !isRejected && !isDeadMailbox ? (
              <Button size="sm" variant="outline" onClick={() => reviewContact(contact.id, "rejected")}>
                Reject
              </Button>
            ) : null}
            {isRejected && hasEmail ? (
              <Button size="sm" onClick={() => approveContact(contact.id)}>
                Approve
              </Button>
            ) : null}
            {!isPending &&
            !isRejected &&
            ["approved", "edited"].includes(rs) &&
            !draftByContactId.has(contact.id) &&
            createDraftContactId !== contact.id ? (
              <Button
                size="sm"
                variant="outline"
                disabled={!((contact.email || "").trim())}
                title={
                  !(contact.email || "").trim() ? "Add an email to this contact first" : undefined
                }
                onClick={() => void createDraftForContact(contact.id)}
              >
                Create draft
              </Button>
            ) : null}
          </div>
        </div>
        {editingContact?.id === contact.id && !isDeadMailbox ? (
          <div className="mt-3 space-y-2 border-t border-border pt-3">
            <div>
              <div className="mb-1 text-xs text-muted-foreground">Recipient name</div>
              <Input
                placeholder="Contact name"
                value={editingContact.name ?? ""}
                onChange={(e) =>
                  setEditingContact({
                    ...editingContact,
                    name: e.target.value,
                  })
                }
              />
            </div>
            <div>
              <div className="mb-1 text-xs text-muted-foreground">Job title</div>
              <Input
                placeholder="e.g. Head of Partnerships"
                value={editingContact.role ?? ""}
                onChange={(e) =>
                  setEditingContact({
                    ...editingContact,
                    role: e.target.value,
                  })
                }
              />
            </div>
            <div>
              <div className="mb-1 text-xs text-muted-foreground">Email</div>
              <Input
                placeholder="Email"
                value={editingContact.email || ""}
                disabled={contact.status === "valid"}
                title={
                  contact.status === "valid"
                    ? "This email is verified — editing is disabled."
                    : undefined
                }
                onChange={(e) =>
                  setEditingContact({
                    ...editingContact,
                    email: e.target.value,
                  })
                }
              />
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                onClick={async () => {
                  try {
                    setError("");
                    const nameVal = (editingContact.name ?? "").trim();
                    const roleVal = (editingContact.role ?? "").trim();
                    const emailVal = (editingContact.email ?? "").trim();
                    const body = {
                      name: nameVal || null,
                      role: roleVal,
                    };
                    if (contact.status !== "valid") {
                      body.email = emailVal || null;
                    }
                    const updated = await api(`/contacts/${contact.id}/edit`, {
                      method: "PATCH",
                      body,
                    });
                    setEditingContact(null);
                    setContacts((prev) => prev.map((c) => (c.id === contact.id ? { ...c, ...updated } : c)));
                    if (selectedRun) refreshRunDetailsInBackground(selectedRun.id);
                  } catch (e) {
                    setUiError(setError, e);
                  }
                }}
              >
                Save
              </Button>
              <Button size="sm" variant="outline" onClick={() => setEditingContact(null)}>
                Cancel
              </Button>
            </div>
          </div>
        ) : null}
      </div>
    );
  };

  /**
   * True if any contact at this company (same normalized name, any website / card group)
   * has outbound sent with tracking sent/replied — not bounce / dead mailbox / failed only.
   */
  const companyGroupHasActiveOutreachPending = (group) => {
    const idsInCard = new Set(group.map((c) => c.id));
    const nameKeys = new Set(
      group.map((c) => contactCompanyNameOnlyKey(c)).filter((k) => k.length > 0),
    );
    let scopeIds = idsInCard;
    if (nameKeys.size > 0) {
      const byName = new Set();
      for (const c of contacts) {
        const nk = contactCompanyNameOnlyKey(c);
        if (nk && nameKeys.has(nk)) byName.add(c.id);
      }
      scopeIds = byName;
    }
    return drafts.some(
      (d) =>
        d.contact_id != null &&
        scopeIds.has(d.contact_id) &&
        String(d.status) === "sent" &&
        COMPANY_OUTREACH_PENDING_TRACKING.has(String(d.tracking_status || "")),
    );
  };

  const renderContactGroupCard = (group) => {
    const multi = group.length > 1;
    const cardClass = multi ? pickGroupContactCardClass(group) : contactCardClass(group[0]);
    const cardKey = multi ? `grp-${group.map((c) => c.id).join("-")}` : group[0].id;
    const touched = companyGroupHasActiveOutreachPending(group);
    return (
      <Card key={cardKey} className={cardClass}>
        <CardContent className="p-5">
          <div className="mb-4 border-b border-border pb-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-lg font-semibold">{group[0].company || "Unnamed company"}</span>
              {touched ? (
                <Badge
                  variant="default"
                  className="bg-green-600 font-normal text-white hover:bg-green-600 dark:bg-green-700 dark:text-white dark:hover:bg-green-700"
                >
                  Pending
                </Badge>
              ) : (
                <Badge
                  variant="outline"
                  className="border-border bg-muted/40 font-normal text-muted-foreground"
                >
                  No touch
                </Badge>
              )}
            </div>
          </div>
          {group.map((contact, idx) => (
            <div key={contact.id}>
              {idx > 0 ? <Separator className="my-4 bg-border/90" decorative /> : null}
              {renderContactBlock(contact, { grouped: true })}
            </div>
          ))}
        </CardContent>
      </Card>
    );
  };

  const renderDraftCard = (draft) => {
    const draftContact = contactById.get(draft.contact_id);
    const isReplacementDraft = draftContact?.source_json?.source === "replacement_search";
    const draftLifecycle = draft.tracking_status ?? draft.status;
    const isDeadMailboxDraft = draftLifecycle === "dead_mailbox";
    const isSendLater =
      draft.review_notes === OUTBOUND_REVIEW_SEND_LATER &&
      ["approved", "edited"].includes(draft.review_status);
    const isRegeneratingOutbound = Boolean(regeneratingOutboundDraftIds[String(draft.id)]);
    const isSendingOutbound = Boolean(sendingOutboundDraftIds[String(draft.id)]);
    const draftReviewKind = outboundDraftReviewBusy[String(draft.id)];
    const isDraftReviewBusy = Boolean(draftReviewKind);
    return (
    <Card key={draft.id} className={draftCardClass(draft)}>
      <CardContent className="p-5">
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] lg:items-start lg:gap-4">
            <div className="min-w-0 space-y-2">
              <div className="flex min-w-0 items-center gap-2">
                {isDeadMailboxDraft ? (
                  <CircleAlert
                    className="h-5 w-5 shrink-0 text-red-600 dark:text-red-400"
                    aria-hidden
                  />
                ) : null}
                <div className="min-w-0 text-lg font-semibold break-words">
                  {draft.company || "Untitled draft"}
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {isReplacementDraft ? (
                  <Badge variant="default" className="bg-violet-600 hover:bg-violet-600">
                    Replacement draft
                  </Badge>
                ) : null}
                <SendLifecycleBadge status={draftLifecycle} />
                <StatusBadge value={draft.review_status} />
                {isSendLater ? (
                  <Badge
                    variant="outline"
                    className="inline-flex items-center gap-1 border-amber-500/50 font-normal text-amber-900 dark:text-amber-100"
                    title="Approved — send later (clock)"
                  >
                    <Clock className="h-3 w-3 shrink-0" aria-hidden />
                    Send later
                  </Badge>
                ) : null}
                {isRegeneratingOutbound ? (
                  <Badge
                    variant="outline"
                    className="inline-flex items-center gap-1 border-pink-500/50 bg-pink-500/15 font-normal text-pink-900 dark:border-pink-400/45 dark:bg-pink-500/20 dark:text-pink-100"
                    aria-live="polite"
                  >
                    <Clock className="h-3 w-3 shrink-0" aria-hidden />
                    Regenerating
                  </Badge>
                ) : null}
              </div>
            </div>
            <div className="flex min-w-0 flex-nowrap items-center justify-start gap-1.5 overflow-x-auto pt-0.5 [-ms-overflow-style:none] [scrollbar-width:thin] sm:gap-2 lg:justify-end [&::-webkit-scrollbar]:h-1 [&_button]:shrink-0 [&_button]:whitespace-nowrap">
              {isDeadMailboxDraft ? (
                <Button
                  type="button"
                  size="sm"
                  variant="destructive"
                  onClick={() => void deleteDeadMailboxDraft(draft.id)}
                >
                  Delete
                </Button>
              ) : (
                <>
                  <Button size="sm" variant="outline" onClick={() => openEditDraft(draft)}>
                    <Pencil className="mr-1 h-3 w-3" /> Edit
                  </Button>
                  {draft.review_status === "pending" ? (
                    <>
                      <Button
                        size="sm"
                        disabled={isDraftReviewBusy}
                        aria-busy={draftReviewKind === "approve"}
                        onClick={() => void reviewDraft(draft.id, "approved")}
                      >
                        {draftReviewKind === "approve" ? (
                          <Loader2 className="mr-2 h-3.5 w-3.5 shrink-0 animate-spin" aria-hidden />
                        ) : null}
                        Approve
                      </Button>
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={isDraftReviewBusy}
                        aria-busy={draftReviewKind === "later"}
                        onClick={() =>
                          void reviewDraft(draft.id, "approved", OUTBOUND_REVIEW_SEND_LATER)
                        }
                        className="px-2.5"
                        aria-label="Send later"
                        title="Send later — approve without sending now"
                      >
                        {draftReviewKind === "later" ? (
                          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                        ) : (
                          <Clock className="h-4 w-4" aria-hidden />
                        )}
                      </Button>
                      {canRegenerateOutboundDraft(draft) ? (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={isRegeneratingOutbound || isDraftReviewBusy}
                          onClick={() => void regenerateOutboundDraft(draft.id)}
                        >
                          Regenerate
                        </Button>
                      ) : null}
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={isDraftReviewBusy}
                        aria-busy={draftReviewKind === "reject"}
                        onClick={() => void reviewDraft(draft.id, "rejected")}
                      >
                        {draftReviewKind === "reject" ? (
                          <Loader2 className="mr-2 h-3.5 w-3.5 shrink-0 animate-spin" aria-hidden />
                        ) : null}
                        Reject
                      </Button>
                    </>
                  ) : null}
                  {["approved", "edited"].includes(draft.review_status) ? (
                    <>
                      {canRegenerateOutboundDraft(draft) ? (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={isRegeneratingOutbound || isDraftReviewBusy}
                          onClick={() => void regenerateOutboundDraft(draft.id)}
                        >
                          Regenerate
                        </Button>
                      ) : null}
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={isDraftReviewBusy}
                        aria-busy={draftReviewKind === "reject"}
                        onClick={() => void reviewDraft(draft.id, "rejected")}
                      >
                        {draftReviewKind === "reject" ? (
                          <Loader2 className="mr-2 h-3.5 w-3.5 shrink-0 animate-spin" aria-hidden />
                        ) : null}
                        Reject
                      </Button>
                    </>
                  ) : null}
                  {draft.review_status === "rejected" ? (
                    <Button
                      size="sm"
                      disabled={isDraftReviewBusy}
                      aria-busy={draftReviewKind === "approve"}
                      onClick={() => void reviewDraft(draft.id, "approved")}
                    >
                      {draftReviewKind === "approve" ? (
                        <Loader2 className="mr-2 h-3.5 w-3.5 shrink-0 animate-spin" aria-hidden />
                      ) : null}
                      Approve
                    </Button>
                  ) : null}
                  {canSendDraft(draft) ? (
                    <Button
                      size="sm"
                      className="gap-1.5"
                      disabled={isSendingOutbound}
                      aria-busy={isSendingOutbound}
                      onClick={() => void sendDraft(draft.id)}
                    >
                      {isSendingOutbound ? (
                        <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" aria-hidden />
                      ) : !gmailSendReady ? (
                        <CircleX
                          className="h-3.5 w-3.5 shrink-0 text-red-600 dark:text-red-500"
                          aria-hidden
                        />
                      ) : null}
                      Send
                    </Button>
                  ) : null}
                </>
              )}
            </div>
            <div className="min-w-0 space-y-1 text-sm lg:col-span-2">
              <div>
                <span className="font-medium">To:</span> {draft.to_email || "No recipient"}
              </div>
              <div>
                <span className="font-medium">Subject:</span> {draft.subject}
              </div>
            </div>
          </div>
          {draft.error_message &&
          !["bounced", "dead_mailbox", "replied"].includes(String(draft.tracking_status || "")) &&
          !dismissedOutboundDraftErrorKeys.has(`${draft.id}:${draft.error_message}`) ? (
            <div className="flex items-start gap-2 rounded-xl border-2 border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
              <p className="min-w-0 flex-1">{draft.error_message}</p>
              <button
                type="button"
                className="shrink-0 rounded-md p-1 opacity-80 hover:bg-destructive/15 hover:opacity-100"
                aria-label="Dismiss"
                onClick={() =>
                  setDismissedOutboundDraftErrorKeys((prev) =>
                    new Set(prev).add(`${draft.id}:${draft.error_message}`),
                  )
                }
              >
                <X className="h-4 w-4" aria-hidden />
              </button>
            </div>
          ) : null}
          <EmailDraftBodyPreview
            body={draft.body}
            showSignaturePlaceholder={runSignatureHasMeaningfulContent(
              selectedRun?.sender_signature_html ?? workspace?.sender_signature_html ?? "",
            )}
            attachedAssetIds={normalizeAttachedAssetIds(draft.attached_asset_ids)}
            assetLibrary={assetsLibrary}
          />
        </div>
      </CardContent>
    </Card>
    );
  };

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="mx-auto max-w-7xl p-6 md:p-8">
        <div className="mb-6 space-y-4">
          <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
            <div>
              <div className="mb-2 inline-flex items-baseline gap-2 rounded-2xl bg-primary/10 px-3 py-1 text-sm font-medium text-primary">
                <span>AI Biz OS</span>
                <span className="text-xs font-normal tabular-nums text-primary/80">v{appPkg.version}</span>
              </div>
              <h1 className="text-2xl font-bold tracking-tight md:text-3xl">Business outreach dashboard</h1>
            </div>
            <div className="flex flex-wrap gap-2">
              <Dialog>
                <DialogTrigger asChild>
                  <Button variant="outline">New project</Button>
                </DialogTrigger>
                <DialogContent className="sm:max-w-lg">
                  <DialogHeader>
                    <DialogTitle>Create project</DialogTitle>
                  </DialogHeader>
                  <div className="space-y-3 py-2">
                    <Input
                      value={projectName}
                      onChange={(e) => setProjectName(e.target.value)}
                      placeholder="Project name"
                    />
                  </div>
                  <NewProjectFooter projectName={projectName} onCreated={createProject} />
                </DialogContent>
              </Dialog>
              <ThemeToggle />
            </div>
          </div>

          {pendingRestart ? (
            <div
              role="status"
              className="flex items-start gap-3 rounded-2xl border-2 border-border bg-muted/30 px-4 py-3 text-sm"
            >
              <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-primary" aria-hidden />
              <p className="text-muted-foreground">
                <span className="font-medium text-foreground">Restarting {pendingRestart.name}</span>
                {" — "}
                the server is re-running company search and validation. You can keep using the dashboard; run stats
                will refresh when it completes.
              </p>
            </div>
          ) : null}

          <div className="flex flex-col gap-3 lg:flex-row lg:items-stretch">
            <div className="flex min-w-0 flex-1 flex-col gap-3 rounded-2xl border-2 border-border bg-card p-4 md:flex-row md:items-center md:justify-between">
              <div className="space-y-1 text-sm">
                <div>
                  <span className="text-muted-foreground">Project</span>{" "}
                  <span className="font-medium">{selectedProject?.name ?? "—"}</span>
                </div>
                <div>
                  <span className="text-muted-foreground">Run</span>{" "}
                  <span className="font-medium">
                    {selectedRun
                      ? selectedRun.name?.trim() || `Run #${selectedRun.id}`
                      : "Select a run"}
                  </span>
                </div>
                <div>
                  <span className="text-muted-foreground">Status</span>{" "}
                  <span className="font-medium">{workspace?.display_phase ?? "—"}</span>
                </div>
                <div className="text-foreground/90">
                  <span className="text-muted-foreground">LLMs</span>{" "}
                  <span className="font-medium">{integrationInformer.llmPart}</span>
                  <span className="px-1.5 text-muted-foreground">·</span>
                  <span className="text-muted-foreground">CDN</span>{" "}
                  <span className="font-medium">{integrationInformer.cdnPart}</span>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  disabled={!selectedProject || selectedProject.is_archived}
                  onClick={() => openNewRunDialog()}
                >
                  New run
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  disabled={!selectedProject || runsList.length === 0}
                  onClick={() => setSwitchRunOpen(true)}
                >
                  <RefreshCw className="mr-2 h-4 w-4" aria-hidden />
                  Switch run
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  disabled={!selectedRun || workspace?.display_phase === "Closed"}
                  onClick={() => setCloseRunOpen(true)}
                >
                  Close run
                </Button>
              </div>
            </div>
            <Card
              className={cn(
                "min-h-0 min-w-0 w-full shrink-0 rounded-2xl border-2 shadow-none lg:w-80",
                totalPerformance24hUi.cardClass,
              )}
            >
              <CardHeader className="pb-3">
                <CardTitle>Total performance</CardTitle>
                <p className={cn("mt-1 text-xs font-medium leading-snug", totalPerformance24hUi.captionClass)}>
                  {totalPerformance24hUi.label}
                </p>
              </CardHeader>
              <CardContent className="min-w-0">
                <ul className="space-y-2 break-words text-sm">
                  <li>
                    Emails sent:{" "}
                    <span className="font-medium">{totalPerformance?.emails_sent ?? 0}</span>
                  </li>
                  <li>
                    Emails sent (24 hrs):{" "}
                    <span className="font-medium">{totalPerformance?.emails_sent_24h ?? 0}</span>
                  </li>
                </ul>
              </CardContent>
            </Card>
          </div>
        </div>

        {error ? (
          <Card className="mb-6 border-2 border-destructive/50">
            <CardContent className="flex items-start gap-3 p-4">
              <p className="min-w-0 flex-1 text-sm text-destructive">{error}</p>
              <button
                type="button"
                className="shrink-0 rounded-md p-1 text-destructive opacity-80 hover:bg-destructive/10 hover:opacity-100"
                aria-label="Dismiss"
                onClick={() => setError("")}
              >
                <X className="h-4 w-4" aria-hidden />
              </button>
            </CardContent>
          </Card>
        ) : null}

        <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
          <Card className="rounded-2xl border-2 border-border shadow-none">
            <CardHeader>
              <CardTitle>Projects</CardTitle>
              <CardDescription>Choose a project, then create or open a run</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <NativeFilterSelect
                className="w-full"
                value={projectView}
                onValueChange={setProjectView}
                options={PROJECT_VIEW_OPTS}
              />
              <ScrollArea className="h-[560px] pr-3">
                <div className="space-y-3">
                  {projects.map((project) => (
                    <div
                      key={project.id}
                      className={`rounded-2xl border-2 p-4 transition ${
                        selectedProject?.id === project.id ? "border-primary bg-primary/5" : "border-border"
                      }`}
                    >
                      <div className="flex items-start gap-2">
                        <button
                          type="button"
                          onClick={() => setSelectedProject(project)}
                          className="min-w-0 flex-1 rounded-lg text-left hover:opacity-90"
                        >
                          <div className="font-medium">{project.name}</div>
                          <div className="mt-1 text-xs text-muted-foreground">{pretty(project.type)}</div>
                          {selectedProject?.id === project.id ? (
                            <div className="mt-2 border-l-2 border-primary/50 pl-2 text-left text-xs leading-snug">
                              <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                                Run
                              </div>
                              {selectedRun != null && selectedRun.project_id !== project.id ? (
                                <div className="mt-0.5 text-muted-foreground">Loading…</div>
                              ) : selectedRun != null && selectedRun.project_id === project.id ? (
                                <>
                                  <div
                                    className="mt-0.5 truncate font-medium text-foreground"
                                    title={selectedRun.name?.trim() || `Run #${selectedRun.id}`}
                                  >
                                    {selectedRun.name?.trim() || `Run #${selectedRun.id}`}
                                  </div>
                                  {workspace?.display_phase && workspace?.id === selectedRun.id ? (
                                    <div className="mt-0.5 text-muted-foreground">{workspace.display_phase}</div>
                                  ) : null}
                                </>
                              ) : runsList.length > 0 &&
                                !runsList.some((r) => r.project_id === project.id) ? (
                                <div className="mt-0.5 text-muted-foreground">Loading…</div>
                              ) : runsList.some((r) => r.project_id === project.id) && !selectedRun ? (
                                <div className="mt-0.5 text-muted-foreground">Loading…</div>
                              ) : (
                                <div className="mt-0.5 font-medium text-muted-foreground">No runs yet</div>
                              )}
                            </div>
                          ) : null}
                        </button>
                        <div className="flex shrink-0 items-start gap-0.5">
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            className="h-8 w-8 shrink-0 p-0 text-muted-foreground"
                            aria-label="Rename project"
                            title="Rename project"
                            onClick={(e) => {
                              e.preventDefault();
                              e.stopPropagation();
                              openRenameProject(project);
                            }}
                          >
                            <Settings className="h-4 w-4" aria-hidden />
                          </Button>
                          {projectView === "active" ? (
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-8 w-8 shrink-0 p-0 text-muted-foreground"
                              aria-label="Archive project"
                              title="Archive"
                              onClick={(e) => {
                                e.stopPropagation();
                                void archiveProject(project.id);
                              }}
                            >
                              <Archive className="h-4 w-4" aria-hidden />
                            </Button>
                          ) : (
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-8 w-8 shrink-0 p-0 text-muted-foreground"
                              aria-label="Restore project"
                              title="Restore"
                              onClick={(e) => {
                                e.stopPropagation();
                                void restoreProject(project.id);
                              }}
                            >
                              <ArchiveRestore className="h-4 w-4" aria-hidden />
                            </Button>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                  {!projects.length && (
                    <div className="rounded-2xl border-2 border-dashed p-6 text-sm text-muted-foreground">
                      {loading
                        ? "Loading projects..."
                        : projectView === "archived"
                          ? "No archived projects."
                          : "No projects yet."}
                    </div>
                  )}
                </div>
              </ScrollArea>

            </CardContent>
          </Card>

          <div className="space-y-6">
            {selectedRun && workspace ? (
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_20rem] lg:items-start">
                <Card className="min-w-0 rounded-2xl border-2 border-border shadow-none">
                  <CardHeader className="min-w-0 space-y-0">
                    <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                      <div className="min-w-0">
                        <CardTitle>Run setup</CardTitle>
                        {!selectedRun.closed_at ? (
                          <CardDescription>Prepare this run before starting outreach</CardDescription>
                        ) : null}
                      </div>
                      {primaryCta ? (
                        <div className="flex shrink-0 flex-col items-stretch gap-1 sm:items-end">
                          <Button
                            size="sm"
                            className="whitespace-normal sm:whitespace-nowrap"
                            disabled={primaryCta.disabled || !primaryCta.onClick}
                            onClick={() => primaryCta.onClick?.()}
                          >
                            {primaryCta.label}
                          </Button>
                          {primaryCta.hint ? (
                            <span className="max-w-full text-right text-xs text-muted-foreground sm:max-w-xs">
                              {primaryCta.hint}
                            </span>
                          ) : null}
                        </div>
                      ) : null}
                    </div>
                  </CardHeader>
                  <CardContent className="min-w-0 space-y-4">
                    <div className="grid grid-cols-1 gap-3 min-[520px]:grid-cols-3">
                      {(workspace.setup_steps || []).map((st) => {
                        const capClass =
                          st.ui_status === "Completed"
                            ? "bg-primary text-primary-foreground"
                            : "bg-muted text-muted-foreground";
                        return (
                          <div
                            key={st.step_name}
                            className="overflow-hidden rounded-2xl border-2 border-border bg-card shadow-none"
                          >
                            <div
                              className={`px-3 py-2 text-center text-xs font-semibold ${capClass}`}
                            >
                              {st.ui_status}
                            </div>
                            <div className="p-3 pt-3">
                              <div className="text-sm font-medium leading-snug">{st.title}</div>
                              <div className="mt-2 text-xs text-muted-foreground">
                                Retry count: {st.retry_count}
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                    <div className="rounded-2xl border-2 border-border bg-muted/30 p-3 text-sm">
                      <div className="font-medium">Setup summary</div>
                      <ul className="mt-2 space-y-1 text-muted-foreground">
                        <li>
                          Companies collected:{" "}
                          <span className="font-medium text-foreground">
                            {workspace.setup_summary?.companies_collected ?? "—"}
                          </span>
                        </li>
                        <li className="text-muted-foreground">
                          Contacts found:{" "}
                          <span className="font-semibold text-foreground">
                            {workspace.setup_summary?.contacts_found ?? "—"}
                          </span>
                        </li>
                        <li>
                          Contacts validated:{" "}
                          <span className="font-medium text-foreground">
                            {workspace.setup_summary?.contacts_validated ?? "—"}
                          </span>
                          {typeof workspace.setup_summary?.contacts_validated_distinct_companies === "number" ? (
                            <>
                              {" "}
                              [{workspace.setup_summary.contacts_validated_distinct_companies} companies]
                            </>
                          ) : null}
                        </li>
                        <li>
                          Contacts with no email:{" "}
                          <span className="font-medium text-foreground">
                            {workspace.setup_summary?.contacts_with_no_email ?? "—"}
                          </span>
                        </li>
                        <li>
                          Contacts approved:{" "}
                          <span className="font-medium text-foreground">
                            {workspace.setup_summary?.contacts_approved ?? "—"}
                          </span>
                        </li>
                      </ul>
                      {selectedRun.closed_at ? (
                        <p className="mt-3 font-medium text-destructive">Run closed</p>
                      ) : (
                        <p className="mt-3 text-foreground">{workspace.setup_state_message}</p>
                      )}
                    </div>
                  </CardContent>
                </Card>

                <Card className="min-w-0 w-full rounded-2xl border-2 border-border shadow-none">
                  <CardHeader className="pb-3">
                    <CardTitle>Run performance</CardTitle>
                  </CardHeader>
                  <CardContent className="min-w-0">
                    <ul className="space-y-2 break-words text-sm">
                      <li>
                        Emails sent:{" "}
                        <span className="font-medium">{workspace.performance?.emails_sent ?? 0}</span>
                      </li>
                      <li>
                        Emails sent (24 hrs):{" "}
                        <span className="font-medium">{workspace.performance?.emails_sent_24h ?? 0}</span>
                      </li>
                      <li>
                        Replies:{" "}
                        <span className="font-medium">{workspace.performance?.replies ?? 0}</span>
                      </li>
                      <li>
                        Active:{" "}
                        <span className="font-medium">{workspace.performance?.active_threads ?? 0}</span>
                      </li>
                      <li>
                        Interested:{" "}
                        <span className="font-medium">{workspace.performance?.interested ?? 0}</span>
                      </li>
                      <li>
                        Need more info:{" "}
                        <span className="font-medium">{workspace.performance?.need_more_info ?? 0}</span>
                      </li>
                      <li>
                        Dead mailboxes:{" "}
                        <span className="font-medium">{workspace.performance?.dead_mailboxes ?? 0}</span>
                      </li>
                      <li>
                        Bounced:{" "}
                        <span className="font-medium">{workspace.performance?.bounced ?? 0}</span>
                      </li>
                    </ul>
                    {workspace.conversations ? (
                      <div className="mt-4 border-t border-border pt-4">
                        <div className="text-sm font-medium">Conversations</div>
                        <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
                          <li>Active threads: {workspace.conversations.active_threads}</li>
                          <li>Replies received: {workspace.conversations.replies_received}</li>
                          <li>Reply drafts: {workspace.conversations.reply_drafts}</li>
                          <li>Reminders (active): {workspace.conversations.reminders_active}</li>
                          <li>Reminders due: {workspace.conversations.reminders_due}</li>
                        </ul>
                      </div>
                    ) : null}
                  </CardContent>
                </Card>
              </div>
            ) : null}

            <div className="flex flex-wrap gap-1 rounded-2xl border-2 border-border bg-muted/20 p-1">
              {visibleMainNavItems.map((item) => {
                const active = mainNav === item.value;
                return (
                  <Button
                    key={item.value}
                    type="button"
                    size="sm"
                    variant={active ? "default" : "ghost"}
                    className={cn(
                      "rounded-xl",
                      !active &&
                        "border-2 border-transparent shadow-none hover:border-primary hover:bg-transparent",
                    )}
                    onClick={() => setMainNav(item.value)}
                  >
                    {item.label}
                  </Button>
                );
              })}
            </div>

            {mainNav === "runs" ? (
              <Card className="rounded-2xl border-2 border-border shadow-none">
                <CardHeader>
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <CardTitle>Runs</CardTitle>
                      <CardDescription>Manage outreach waves inside this project</CardDescription>
                    </div>
                    <Button
                      type="button"
                      disabled={!selectedProject || selectedProject.is_archived}
                      onClick={() => openNewRunDialog()}
                    >
                      New run
                    </Button>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3">
                  {!selectedProject ? (
                    <p className="text-sm text-muted-foreground">Select a project first.</p>
                  ) : runsList.length === 0 ? (
                    <p className="text-sm text-muted-foreground">
                      No runs yet — create one with <strong>New run</strong>.
                    </p>
                  ) : (
                    runsList.map((r) => (
                      <Card
                        key={r.id}
                        className={cn(
                          "rounded-2xl border-2 shadow-none transition",
                          selectedRun?.id === r.id ? "border-primary bg-primary/5" : "border-border",
                        )}
                      >
                        <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
                          <div className="space-y-1 text-sm">
                            <div className="font-semibold">{r.name}</div>
                            <div className="text-muted-foreground">Status: {r.display_phase}</div>
                            <div className="text-xs text-muted-foreground">
                              Companies {r.companies_count} · Contacts {r.contacts_count} · Sent{" "}
                              {r.emails_sent} · Replies {r.replies} · Threads {r.active_threads}
                            </div>
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              disabled={openRunEditLoading}
                              onClick={() => void openRunEditDialog(r)}
                            >
                              Open
                            </Button>
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              disabled={r.display_phase === "Closed" || pendingRestart != null}
                              onClick={() => openRestartDialog(r)}
                            >
                              Continue outreach
                            </Button>
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              title="Switch to this run"
                              disabled={
                                selectedRun?.id === r.id || pendingRestart != null || openRunEditLoading
                              }
                              onClick={() => void openRunById(r.id)}
                            >
                              <RefreshCw className="mr-1 h-4 w-4" aria-hidden />
                              Switch
                            </Button>
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              disabled={r.display_phase === "Closed"}
                              onClick={() => {
                                refreshRunDetailsInBackground(r.id);
                                setCloseRunOpen(true);
                              }}
                            >
                              Close run
                            </Button>
                          </div>
                        </CardContent>
                      </Card>
                    ))
                  )}
                </CardContent>
              </Card>
            ) : null}

            {mainNav === "companies" ? (
              <Card className="rounded-2xl border-2 border-border shadow-none">
                <CardHeader>
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
                    <div className="min-w-0 space-y-1.5">
                      <CardTitle>Companies</CardTitle>
                      <CardDescription>
                        List from the collect step. Status reflects find-contacts: match with at least one email,
                        matches but no emails (Not available), no match (Not found), or search still in progress.
                      </CardDescription>
                      {companiesPanel?.collect_step_status != null || companiesPanel?.find_step_status != null ? (
                        <p className="text-xs text-muted-foreground">
                          Collect step:{" "}
                          <span className="font-medium text-foreground">
                            {companiesPanel?.collect_step_status ?? "—"}
                          </span>
                          {" · "}
                          Find contacts step:{" "}
                          <span className="font-medium text-foreground">
                            {companiesPanel?.find_step_status ?? "—"}
                          </span>
                        </p>
                      ) : null}
                    </div>
                    <div className="flex shrink-0 flex-col gap-2 self-start sm:mt-0.5 sm:items-end">
                      {companiesPanel?.companies?.some((c) => c.contact_status === "pending") &&
                      selectedRun &&
                      !selectedRun.closed_at &&
                      pendingRestart == null ? (
                        <Button
                          type="button"
                          variant="secondary"
                          size="sm"
                          disabled={companiesLoading || continueCompanyFindLoading}
                          onClick={() => void continueCompanyFindAllPending(selectedRun.id)}
                        >
                          {continueCompanyFindLoading ? (
                            <>
                              <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                              Searching…
                            </>
                          ) : (
                            "Continue searching"
                          )}
                        </Button>
                      ) : null}
                      {companiesPanel?.companies?.some(
                        (c) =>
                          (c.contact_status === "none" || c.contact_status === "no_email") &&
                          !companyFindUnavailable[c.collect_index],
                      ) &&
                      selectedRun &&
                      !selectedRun.closed_at &&
                      pendingRestart == null ? (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          disabled={
                            companiesLoading ||
                            continueCompanyFindLoading ||
                            companyRetryAllLoading ||
                            Object.keys(companyRetryLoading).length > 0
                          }
                          onClick={() => void retryAllCompanyFindNotFound(selectedRun.id)}
                        >
                          {companyRetryAllLoading ? (
                            <>
                              <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                              Retrying all…
                            </>
                          ) : (
                            "Retry all"
                          )}
                        </Button>
                      ) : null}
                    </div>
                  </div>
                </CardHeader>
                <CardContent>
                  {!selectedRun ? (
                    <p className="text-sm text-muted-foreground">Select a run first.</p>
                  ) : companiesLoading && !companiesPanel ? (
                    <p className="text-sm text-muted-foreground">Loading companies...</p>
                  ) : !companiesPanel?.companies?.length ? (
                    <p className="text-sm text-muted-foreground">
                      No companies in this run&apos;s collect step yet. They appear after search adds them (or restart
                      the run).
                    </p>
                  ) : (
                    <div className="space-y-4">
                      <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
                        <span className="inline-flex items-center gap-1.5">
                          <Badge variant="default" className="shrink-0 whitespace-nowrap font-normal">
                            Contacts found
                          </Badge>
                          <span>
                            At least one matching person has a usable email in find-contacts output. If{" "}
                            <strong>all</strong> contacts for that company become bounced or dead mailbox, the row shows{" "}
                            <strong>Not available</strong> instead.
                          </span>
                        </span>
                        <span className="inline-flex items-center gap-1.5">
                          <Badge variant="secondary" className="font-normal">
                            Not found
                          </Badge>
                          <span>Find-contacts finished; no matching row for this company.</span>
                        </span>
                        <span className="inline-flex items-center gap-1.5">
                          <Badge variant="destructive" className="font-normal">
                            Not available
                          </Badge>
                          <span>
                            Find returned people without emails, or retry added nothing — further retries are hidden
                            for that row.
                          </span>
                        </span>
                        <span className="inline-flex items-center gap-1.5">
                          <Badge variant="outline" className="border-amber-500/50 font-normal text-amber-950 dark:text-amber-100">
                            Not searched yet
                          </Badge>
                          <span>Find-contacts still running or not completed — more results may arrive.</span>
                        </span>
                      </div>
                      <div className="overflow-x-auto rounded-xl border-2 border-border">
                        <table className="w-full min-w-[520px] text-left text-sm">
                          <thead className="border-b border-border bg-muted/40 text-xs font-semibold text-muted-foreground">
                            <tr>
                              <th className="px-3 py-2">Company</th>
                              <th className="px-3 py-2">Website</th>
                              <th className="px-3 py-2">Contact search</th>
                            </tr>
                          </thead>
                          <tbody>
                            {companiesPageSlice.map((row) => {
                              const st = row.contact_status;
                              const unavailable = !!companyFindUnavailable[row.collect_index];
                              const onlyBouncedOrDead =
                                st === "found" && companyHasOnlyBouncedOrDeadContacts(contacts, row);
                              const badge =
                                onlyBouncedOrDead ? (
                                  <Badge variant="destructive" className="font-normal">
                                    Not available
                                  </Badge>
                                ) : st === "found" ? (
                                  <Badge variant="default" className="shrink-0 whitespace-nowrap font-normal">
                                    Contacts found
                                  </Badge>
                                ) : st === "no_email" ? (
                                  <Badge variant="destructive" className="font-normal">
                                    Not available
                                  </Badge>
                                ) : st === "none" && unavailable ? (
                                  <Badge variant="destructive" className="font-normal">
                                    Not available
                                  </Badge>
                                ) : st === "none" ? (
                                  <Badge variant="secondary" className="font-normal">
                                    Not found
                                  </Badge>
                                ) : (
                                  <Badge
                                    variant="outline"
                                    className="border-amber-500/50 font-normal text-amber-950 dark:text-amber-100"
                                  >
                                    Not searched yet
                                  </Badge>
                                );
                              const retryingRow = !!companyRetryLoading[row.collect_index];
                              const canRetryCompanyFind =
                                (st === "none" || st === "no_email") &&
                                !unavailable &&
                                selectedRun &&
                                !selectedRun.closed_at &&
                                pendingRestart == null;
                              return (
                                <tr
                                  key={`company-${row.collect_index}`}
                                  className="border-b border-border last:border-0"
                                >
                                  <td className="px-3 py-2.5 font-medium">{row.name}</td>
                                  <td className="px-3 py-2.5 text-muted-foreground">
                                    {row.website ? (
                                      <a
                                        href={row.website.startsWith("http") ? row.website : `https://${row.website}`}
                                        className="text-primary underline-offset-4 hover:underline"
                                        target="_blank"
                                        rel="noreferrer"
                                      >
                                        {row.website}
                                      </a>
                                    ) : (
                                      "—"
                                    )}
                                  </td>
                                  <td className="px-3 py-2.5">
                                    <div className="flex flex-wrap items-center gap-2">
                                      {badge}
                                      {canRetryCompanyFind ? (
                                        <Button
                                          type="button"
                                          size="sm"
                                          variant="outline"
                                          className="h-6 rounded-full px-2.5 text-xs font-medium"
                                          disabled={retryingRow}
                                          onClick={() => void retryCompanyFind(selectedRun.id, row.collect_index)}
                                        >
                                          {retryingRow ? (
                                            <>
                                              <Loader2 className="mr-1 h-3 w-3 animate-spin" aria-hidden />
                                              Retry
                                            </>
                                          ) : (
                                            "Retry"
                                          )}
                                        </Button>
                                      ) : null}
                                    </div>
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                      {companiesListForPage && companiesListForPage.length > WORKSPACE_TABLE_PAGE_SIZE ? (
                        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between text-sm text-muted-foreground">
                          <span>
                            {(companiesPage - 1) * WORKSPACE_TABLE_PAGE_SIZE + 1}–
                            {Math.min(companiesPage * WORKSPACE_TABLE_PAGE_SIZE, companiesListForPage.length)} of{" "}
                            {companiesListForPage.length}
                          </span>
                          <div className="flex flex-wrap gap-2">
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              disabled={companiesPage <= 1}
                              onClick={() => setCompaniesPage((p) => Math.max(1, p - 1))}
                            >
                              Previous
                            </Button>
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              disabled={companiesPage >= companiesPageCount}
                              onClick={() => setCompaniesPage((p) => Math.min(companiesPageCount, p + 1))}
                            >
                              Next
                            </Button>
                          </div>
                        </div>
                      ) : companiesListForPage && companiesListForPage.length > 0 ? (
                        <p className="text-xs text-muted-foreground">
                          {companiesListForPage.length}{" "}
                          {companiesListForPage.length === 1 ? "company" : "companies"} total.
                        </p>
                      ) : null}
                    </div>
                  )}
                </CardContent>
              </Card>
            ) : null}

            {mainNav === "contacts" || mainNav === "drafts" ? (
            <Card className="rounded-2xl border-2 border-border shadow-none">
              <CardHeader>
                <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                  <div>
                    <CardTitle>
                      {mainNav === "drafts" ? "Review email drafts" : "Review contacts"}
                    </CardTitle>
                    <CardDescription>
                      {mainNav === "drafts"
                        ? "A list of generated email drafts. To send a message, you must first approve it. You can send all approved messages at once."
                        : "List of found contacts. To create a draft email, the contact must be approved."}
                    </CardDescription>
                  </div>
                  <div className="flex w-full flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center md:max-w-none md:justify-end">
                    <div className="flex flex-wrap gap-2">
                      {mainNav === "drafts" ? (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className="gap-1.5"
                          title="Send the first sendable approved draft to yourself (To = From: GMAIL_SEND_AS_EMAIL when set, else primary Gmail). Does not update drafts or the database."
                          onClick={() => void testSendFirstApproved()}
                          disabled={!selectedRun || approvedDrafts === 0 || testSendBusy}
                        >
                          {testSendBusy ? (
                            <Loader2 className="h-4 w-4 shrink-0 animate-spin" aria-hidden />
                          ) : !gmailSendReady ? (
                            <CircleX className="h-4 w-4 shrink-0 text-red-600 dark:text-red-500" aria-hidden />
                          ) : (
                            <Mail className="h-4 w-4 shrink-0 opacity-70" aria-hidden />
                          )}
                          Test
                        </Button>
                      ) : null}
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="gap-1.5"
                        onClick={() => openPromptSetup()}
                        disabled={!selectedRun}
                      >
                        {promptSetupSavedFilled ? (
                          <CircleCheck
                            className="h-4 w-4 shrink-0 text-green-600 dark:text-green-500"
                            aria-hidden
                          />
                        ) : (
                          <CircleX
                            className="h-4 w-4 shrink-0 text-red-600 dark:text-red-500"
                            aria-hidden
                          />
                        )}
                        Prompt setup
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="gap-1.5"
                        onClick={() => openSignatureSetup()}
                        disabled={!selectedRun}
                      >
                        {signatureSetupFilled ? (
                          <CircleCheck
                            className="h-4 w-4 shrink-0 text-green-600 dark:text-green-500"
                            aria-hidden
                          />
                        ) : (
                          <CircleX
                            className="h-4 w-4 shrink-0 text-red-600 dark:text-red-500"
                            aria-hidden
                          />
                        )}
                        Signature setup
                      </Button>
                    </div>
                    <Input
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                      placeholder="Search company, name, email, subject..."
                      className="min-w-0 sm:max-w-[220px] md:max-w-sm"
                    />
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                {mainNav === "contacts" ? (
                  <div className="space-y-6">
                    {contactsRunHydrated ? (
                    <>
                    {approveContactsContinueCta ? (
                      <div className="flex max-w-xl flex-col gap-1">
                        <Button
                          type="button"
                          size="sm"
                          className="w-fit whitespace-normal sm:whitespace-nowrap"
                          disabled={
                            approveContactsContinueCta.disabled || !approveContactsContinueCta.onClick
                          }
                          onClick={() => approveContactsContinueCta.onClick?.()}
                        >
                          {approveContactsContinueCta.label}
                        </Button>
                        {approveContactsContinueCta.hint ? (
                          <span className="text-xs text-muted-foreground">
                            {approveContactsContinueCta.hint}
                          </span>
                        ) : null}
                      </div>
                    ) : null}
                    <div className="text-sm text-muted-foreground">
                      {pendingContacts} contacts left to review
                      {approvedContactsReachable > 0 ? (
                        <span className="text-muted-foreground">
                          {" "}
                          · {approvedContactsReachable} approved (reachable)
                        </span>
                      ) : null}
                    </div>

                    {pendingContacts === 0 && contactsVisible.length > 0 ? (
                      <div className="rounded-2xl border-2 border-dashed border-muted-foreground/25 py-10 text-center">
                        <div className="text-lg font-medium">All contacts reviewed 🎉</div>
                        {selectedRun?.status === "needs_review" ? (
                          <>
                            <div className="mb-4 text-sm text-muted-foreground">
                              You can continue to generate emails
                            </div>
                            <Button onClick={continueRun} disabled={!canContinue}>
                              Continue to email drafts
                            </Button>
                            {!canContinue ? (
                              <p className="mx-auto mt-3 max-w-md text-xs text-muted-foreground">
                                Approve or edit at least one reachable contact (bounced / dead mailbox do not
                                count).
                              </p>
                            ) : null}
                          </>
                        ) : (
                          <>
                            <div className="mb-4 text-sm text-muted-foreground">
                              Contact review for this step is done. Open Drafts to work on emails.
                            </div>
                            <Button type="button" onClick={() => setMainNav("drafts")}>
                              Open Drafts
                            </Button>
                          </>
                        )}
                      </div>
                    ) : null}

                    {contactsVisible.length > 0 ? (
                      <div className="space-y-3">
                        <div
                          className="flex w-full min-w-0 flex-nowrap items-center justify-center gap-1.5 overflow-x-auto pb-0.5 [-ms-overflow-style:none] [scrollbar-width:thin] [&::-webkit-scrollbar]:h-1"
                          role="tablist"
                          aria-label="Contact review category"
                        >
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            role="tab"
                            aria-selected={contactReviewTab === "pending"}
                            className={cn(
                              "h-8 shrink-0 rounded-lg border-2 px-2.5 text-xs font-semibold sm:h-9 sm:px-3 sm:text-sm",
                              contactReviewTab === "pending"
                                ? "border-green-500 bg-green-600 text-white hover:bg-green-600 dark:border-green-400 dark:bg-green-600 dark:hover:bg-green-600"
                                : "border-green-600/50 bg-green-600/15 text-green-900 hover:bg-green-600/25 dark:border-green-600/45 dark:bg-green-950/40 dark:text-green-100 dark:hover:bg-green-950/55",
                            )}
                            onClick={() => setContactReviewTab("pending")}
                          >
                            Pending ({displayContactReviewCounts.pending})
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            role="tab"
                            aria-selected={contactReviewTab === "approved"}
                            className={cn(
                              "h-8 shrink-0 rounded-lg border-2 px-2.5 text-xs font-semibold sm:h-9 sm:px-3 sm:text-sm",
                              contactReviewTab === "approved"
                                ? "border-sky-500 bg-sky-600 text-white hover:bg-sky-600 dark:border-sky-400 dark:bg-sky-600 dark:hover:bg-sky-600"
                                : "border-sky-600/50 bg-sky-600/15 text-sky-950 hover:bg-sky-600/25 dark:border-sky-500/45 dark:bg-sky-950/40 dark:text-sky-100 dark:hover:bg-sky-950/55",
                            )}
                            onClick={() => setContactReviewTab("approved")}
                          >
                            Approved ({displayContactReviewCounts.approved})
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            role="tab"
                            aria-selected={contactReviewTab === "rejected"}
                            className={cn(
                              "h-8 shrink-0 rounded-lg border-2 px-2.5 text-xs font-semibold sm:h-9 sm:px-3 sm:text-sm",
                              contactReviewTab === "rejected"
                                ? "border-neutral-500 bg-neutral-600 text-white hover:bg-neutral-600 dark:border-neutral-400 dark:bg-neutral-600 dark:hover:bg-neutral-600"
                                : "border-neutral-600/50 bg-neutral-600/15 text-neutral-900 hover:bg-neutral-600/25 dark:border-neutral-500/45 dark:bg-neutral-900/35 dark:text-neutral-100 dark:hover:bg-neutral-900/50",
                            )}
                            onClick={() => setContactReviewTab("rejected")}
                          >
                            Rejected ({displayContactReviewCounts.rejected})
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            role="tab"
                            aria-selected={contactReviewTab === "bounced"}
                            className={cn(
                              "h-8 shrink-0 rounded-lg border-2 px-2.5 text-xs font-semibold sm:h-9 sm:px-3 sm:text-sm",
                              contactReviewTab === "bounced"
                                ? "border-amber-500 bg-amber-600 text-white hover:bg-amber-600 dark:border-amber-400 dark:bg-amber-600 dark:hover:bg-amber-600"
                                : "border-amber-600/50 bg-amber-600/15 text-amber-950 hover:bg-amber-600/25 dark:border-amber-500/45 dark:bg-amber-950/40 dark:text-amber-100 dark:hover:bg-amber-950/55",
                            )}
                            onClick={() => setContactReviewTab("bounced")}
                          >
                            Bounced ({displayContactReviewCounts.bounced})
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            role="tab"
                            aria-selected={contactReviewTab === "dead_mailbox"}
                            className={cn(
                              "h-8 shrink-0 rounded-lg border-2 px-2.5 text-xs font-semibold sm:h-9 sm:px-3 sm:text-sm",
                              contactReviewTab === "dead_mailbox"
                                ? "border-red-500 bg-red-600 text-white hover:bg-red-600 dark:border-red-400 dark:bg-red-600 dark:hover:bg-red-600"
                                : "border-red-700/50 bg-red-950/20 text-red-900 hover:bg-red-950/30 dark:border-red-700/45 dark:bg-red-950/35 dark:text-red-100 dark:hover:bg-red-950/50",
                            )}
                            onClick={() => setContactReviewTab("dead_mailbox")}
                          >
                            Dead mailbox ({displayContactReviewCounts.dead_mailbox})
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            role="tab"
                            aria-selected={contactReviewTab === "no_email"}
                            className={cn(
                              "h-8 shrink-0 rounded-lg border-2 px-2.5 text-xs font-semibold sm:h-9 sm:px-3 sm:text-sm",
                              contactReviewTab === "no_email"
                                ? "border-zinc-500 bg-zinc-600 text-white hover:bg-zinc-600 dark:border-zinc-400 dark:bg-zinc-600 dark:hover:bg-zinc-600"
                                : "border-zinc-600/50 bg-zinc-600/15 text-zinc-900 hover:bg-zinc-600/25 dark:border-zinc-500/45 dark:bg-zinc-950/40 dark:text-zinc-100 dark:hover:bg-zinc-950/55",
                            )}
                            onClick={() => setContactReviewTab("no_email")}
                          >
                            No email ({displayContactReviewCounts.no_email})
                          </Button>
                        </div>

                        {contactReviewTabGroups.length === 0 ? (
                          <div className="text-sm text-muted-foreground">
                            {contactReviewTab === "pending"
                              ? "No pending contacts here — try another tab or clear search."
                              : contactReviewTab === "approved"
                                ? "No approved contacts in this filter — try Pending or delivery tabs."
                                : contactReviewTab === "rejected"
                                  ? "No rejected contacts here."
                                  : contactReviewTab === "bounced"
                                    ? "No bounced contacts — check other tabs or search."
                                    : contactReviewTab === "dead_mailbox"
                                      ? "No dead mailbox contacts."
                                      : "No contacts without a usable email address here."}
                          </div>
                        ) : (
                          <div className="grid gap-3">
                            {contactReviewGroupsPage.map((g) => renderContactGroupCard(g))}
                          </div>
                        )}

                        {contactReviewTabGroups.length > WORKSPACE_TABLE_PAGE_SIZE ? (
                          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between text-sm text-muted-foreground">
                            <span>
                              {(contactsReviewPage - 1) * WORKSPACE_TABLE_PAGE_SIZE + 1}–
                              {Math.min(
                                contactsReviewPage * WORKSPACE_TABLE_PAGE_SIZE,
                                contactReviewTabGroups.length,
                              )}{" "}
                              of {contactReviewTabGroups.length}
                            </span>
                            <div className="flex flex-wrap gap-2">
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                disabled={contactsReviewPage <= 1}
                                onClick={() => setContactsReviewPage((p) => Math.max(1, p - 1))}
                              >
                                Previous
                              </Button>
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                disabled={contactsReviewPage >= contactsReviewPageCount}
                                onClick={() =>
                                  setContactsReviewPage((p) => Math.min(contactsReviewPageCount, p + 1))
                                }
                              >
                                Next
                              </Button>
                            </div>
                          </div>
                        ) : contactReviewTabGroups.length > 0 ? (
                          <p className="text-xs text-muted-foreground">
                            {contactReviewTabGroups.length} group
                            {contactReviewTabGroups.length === 1 ? "" : "s"} total.
                          </p>
                        ) : null}
                      </div>
                    ) : null}

                    {contactsVisible.length === 0 ? (
                      <div className="text-center text-sm text-muted-foreground">
                        No contacts for this run yet.
                      </div>
                    ) : null}
                    </>
                    ) : selectedRun?.id ? (
                      <div className="space-y-3">
                        <div
                          className="flex w-full min-w-0 flex-nowrap items-center justify-center gap-1.5 overflow-x-auto pb-0.5 [-ms-overflow-style:none] [scrollbar-width:thin] [&::-webkit-scrollbar]:h-1"
                          role="tablist"
                          aria-label="Contact review category"
                        >
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            role="tab"
                            aria-selected={contactReviewTab === "pending"}
                            className={cn(
                              "h-8 shrink-0 rounded-lg border-2 px-2.5 text-xs font-semibold sm:h-9 sm:px-3 sm:text-sm",
                              contactReviewTab === "pending"
                                ? "border-green-500 bg-green-600 text-white hover:bg-green-600 dark:border-green-400 dark:bg-green-600 dark:hover:bg-green-600"
                                : "border-green-600/50 bg-green-600/15 text-green-900 hover:bg-green-600/25 dark:border-green-600/45 dark:bg-green-950/40 dark:text-green-100 dark:hover:bg-green-950/55",
                            )}
                            onClick={() => setContactReviewTab("pending")}
                          >
                            Pending ({displayContactReviewCounts.pending})
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            role="tab"
                            aria-selected={contactReviewTab === "approved"}
                            className={cn(
                              "h-8 shrink-0 rounded-lg border-2 px-2.5 text-xs font-semibold sm:h-9 sm:px-3 sm:text-sm",
                              contactReviewTab === "approved"
                                ? "border-sky-500 bg-sky-600 text-white hover:bg-sky-600 dark:border-sky-400 dark:bg-sky-600 dark:hover:bg-sky-600"
                                : "border-sky-600/50 bg-sky-600/15 text-sky-950 hover:bg-sky-600/25 dark:border-sky-500/45 dark:bg-sky-950/40 dark:text-sky-100 dark:hover:bg-sky-950/55",
                            )}
                            onClick={() => setContactReviewTab("approved")}
                          >
                            Approved ({displayContactReviewCounts.approved})
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            role="tab"
                            aria-selected={contactReviewTab === "rejected"}
                            className={cn(
                              "h-8 shrink-0 rounded-lg border-2 px-2.5 text-xs font-semibold sm:h-9 sm:px-3 sm:text-sm",
                              contactReviewTab === "rejected"
                                ? "border-neutral-500 bg-neutral-600 text-white hover:bg-neutral-600 dark:border-neutral-400 dark:bg-neutral-600 dark:hover:bg-neutral-600"
                                : "border-neutral-600/50 bg-neutral-600/15 text-neutral-900 hover:bg-neutral-600/25 dark:border-neutral-500/45 dark:bg-neutral-900/35 dark:text-neutral-100 dark:hover:bg-neutral-900/50",
                            )}
                            onClick={() => setContactReviewTab("rejected")}
                          >
                            Rejected ({displayContactReviewCounts.rejected})
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            role="tab"
                            aria-selected={contactReviewTab === "bounced"}
                            className={cn(
                              "h-8 shrink-0 rounded-lg border-2 px-2.5 text-xs font-semibold sm:h-9 sm:px-3 sm:text-sm",
                              contactReviewTab === "bounced"
                                ? "border-amber-500 bg-amber-600 text-white hover:bg-amber-600 dark:border-amber-400 dark:bg-amber-600 dark:hover:bg-amber-600"
                                : "border-amber-600/50 bg-amber-600/15 text-amber-950 hover:bg-amber-600/25 dark:border-amber-500/45 dark:bg-amber-950/40 dark:text-amber-100 dark:hover:bg-amber-950/55",
                            )}
                            onClick={() => setContactReviewTab("bounced")}
                          >
                            Bounced ({displayContactReviewCounts.bounced})
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            role="tab"
                            aria-selected={contactReviewTab === "dead_mailbox"}
                            className={cn(
                              "h-8 shrink-0 rounded-lg border-2 px-2.5 text-xs font-semibold sm:h-9 sm:px-3 sm:text-sm",
                              contactReviewTab === "dead_mailbox"
                                ? "border-red-500 bg-red-600 text-white hover:bg-red-600 dark:border-red-400 dark:bg-red-600 dark:hover:bg-red-600"
                                : "border-red-700/50 bg-red-950/20 text-red-900 hover:bg-red-950/30 dark:border-red-700/45 dark:bg-red-950/35 dark:text-red-100 dark:hover:bg-red-950/50",
                            )}
                            onClick={() => setContactReviewTab("dead_mailbox")}
                          >
                            Dead mailbox ({displayContactReviewCounts.dead_mailbox})
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            role="tab"
                            aria-selected={contactReviewTab === "no_email"}
                            className={cn(
                              "h-8 shrink-0 rounded-lg border-2 px-2.5 text-xs font-semibold sm:h-9 sm:px-3 sm:text-sm",
                              contactReviewTab === "no_email"
                                ? "border-zinc-500 bg-zinc-600 text-white hover:bg-zinc-600 dark:border-zinc-400 dark:bg-zinc-600 dark:hover:bg-zinc-600"
                                : "border-zinc-600/50 bg-zinc-600/15 text-zinc-900 hover:bg-zinc-600/25 dark:border-zinc-500/45 dark:bg-zinc-950/40 dark:text-zinc-100 dark:hover:bg-zinc-950/55",
                            )}
                            onClick={() => setContactReviewTab("no_email")}
                          >
                            No email ({displayContactReviewCounts.no_email})
                          </Button>
                        </div>
                        {reviewContactsSnapModeVal === "loading" &&
                        contactsPanelLiteFiltered.length > 0 ? (
                          <>
                            <p className="text-xs text-muted-foreground" role="status">
                              Showing cached contacts — refreshing…
                            </p>
                            <div className="max-h-[min(60vh,480px)] space-y-2 overflow-y-auto rounded-xl border border-border p-2">
                              {contactsPanelLiteFiltered.map((c) => (
                                <div
                                  key={c.id}
                                  className="rounded-lg border border-border/80 bg-muted/20 px-3 py-2 text-sm"
                                >
                                  <div className="font-medium">{c.company || "—"}</div>
                                  <div className="text-muted-foreground">
                                    {c.name || "—"} · {c.email || "—"}
                                  </div>
                                  <div className="mt-1 flex flex-wrap gap-1">
                                    <Badge variant="secondary" className="text-[10px] font-normal">
                                      {c.review_status || "—"}
                                    </Badge>
                                    {c.email_health ? (
                                      <Badge variant="outline" className="text-[10px] font-normal">
                                        {c.email_health}
                                      </Badge>
                                    ) : null}
                                  </div>
                                </div>
                              ))}
                            </div>
                          </>
                        ) : (
                          <SnapshotCardsPlaceholder
                            mode={reviewContactsSnapModeVal}
                            kind="Contact"
                          />
                        )}
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <div className="space-y-6">
                    {contactsRunHydrated ? (
                    <>
                    <div className="flex flex-wrap items-center gap-2">
                      <Button
                        type="button"
                        className="gap-1.5"
                        onClick={() => void sendAllApproved()}
                        disabled={!selectedRun || approvedDrafts === 0 || sendAllApprovedBusy}
                        aria-busy={sendAllApprovedBusy}
                      >
                        {sendAllApprovedBusy ? (
                          <Loader2 className="h-4 w-4 shrink-0 animate-spin" aria-hidden />
                        ) : !gmailSendReady ? (
                          <CircleX
                            className="h-4 w-4 shrink-0 text-red-600 dark:text-red-500"
                            aria-hidden
                          />
                        ) : null}
                        Send all approved
                      </Button>
                    </div>
                    {drafts.length > 0 ? (
                      <div className="space-y-3">
                        <div
                          className="flex w-full min-w-0 flex-nowrap items-center justify-center gap-1.5 overflow-x-auto pb-0.5 [-ms-overflow-style:none] [scrollbar-width:thin] [&::-webkit-scrollbar]:h-1"
                          role="tablist"
                          aria-label="Draft review category"
                        >
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            role="tab"
                            aria-selected={draftReviewTab === "pending"}
                            className={cn(
                              "h-8 shrink-0 rounded-lg border-2 px-2.5 text-xs font-semibold sm:h-9 sm:px-3 sm:text-sm",
                              draftReviewTab === "pending"
                                ? "border-green-500 bg-green-600 text-white hover:bg-green-600 dark:border-green-400 dark:bg-green-600 dark:hover:bg-green-600"
                                : "border-green-600/50 bg-green-600/15 text-green-900 hover:bg-green-600/25 dark:border-green-600/45 dark:bg-green-950/40 dark:text-green-100 dark:hover:bg-green-950/55",
                            )}
                            onClick={() => setDraftReviewTab("pending")}
                          >
                            Pending review ({displayDraftReviewCounts.pendingReview})
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            role="tab"
                            aria-selected={draftReviewTab === "approved"}
                            className={cn(
                              "h-8 shrink-0 rounded-lg border-2 px-2.5 text-xs font-semibold sm:h-9 sm:px-3 sm:text-sm",
                              draftReviewTab === "approved"
                                ? "border-sky-500 bg-sky-600 text-white hover:bg-sky-600 dark:border-sky-400 dark:bg-sky-600 dark:hover:bg-sky-600"
                                : "border-sky-600/50 bg-sky-600/15 text-sky-950 hover:bg-sky-600/25 dark:border-sky-500/45 dark:bg-sky-950/40 dark:text-sky-100 dark:hover:bg-sky-950/55",
                            )}
                            onClick={() => setDraftReviewTab("approved")}
                          >
                            Approved ({displayDraftReviewCounts.approved})
                          </Button>
                        </div>

                        {draftReviewTab === "pending" ? (
                          <>
                            {draftsPending.length > 0 ? (
                              <div className="space-y-3">
                                <div className="text-sm font-medium">Pending ({draftsPending.length})</div>
                                <div className="grid gap-3">{draftsPending.map((d) => renderDraftCard(d))}</div>
                              </div>
                            ) : null}
                            {draftsRejectedList.length > 0 ? (
                              <details className="group rounded-2xl border-2 border-border">
                                <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 text-sm font-medium [&::-webkit-details-marker]:hidden">
                                  <ChevronRight className="h-4 w-4 shrink-0 transition group-open:rotate-90" />
                                  Rejected ({draftsRejectedList.length})
                                </summary>
                                <div className="grid gap-3 border-t border-border px-4 pb-4 pt-3">
                                  {draftsRejectedList.map((d) => renderDraftCard(d))}
                                </div>
                              </details>
                            ) : null}
                            {draftsPending.length === 0 && draftsRejectedList.length === 0 ? (
                              <div className="text-sm text-muted-foreground">
                                No drafts in pending review for this search — try Approved or clear search.
                              </div>
                            ) : null}
                          </>
                        ) : draftsApprovedList.length > 0 ? (
                          <div className="space-y-3">
                            <div className="text-sm font-medium">Approved ({draftsApprovedList.length})</div>
                            <div className="grid gap-3">{draftsApprovedList.map((d) => renderDraftCard(d))}</div>
                          </div>
                        ) : (
                          <div className="text-sm text-muted-foreground">
                            No approved drafts for this search — try Pending review or clear search.
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="text-sm text-muted-foreground">No drafts yet.</div>
                    )}
                    </>
                    ) : selectedRun?.id ? (
                      <div className="space-y-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <Button
                            type="button"
                            className="gap-1.5"
                            onClick={() => void sendAllApproved()}
                            disabled={!selectedRun || approvedDrafts === 0 || sendAllApprovedBusy}
                            aria-busy={sendAllApprovedBusy}
                          >
                            {sendAllApprovedBusy ? (
                              <Loader2 className="h-4 w-4 shrink-0 animate-spin" aria-hidden />
                            ) : !gmailSendReady ? (
                              <CircleX
                                className="h-4 w-4 shrink-0 text-red-600 dark:text-red-500"
                                aria-hidden
                              />
                            ) : null}
                            Send all approved
                          </Button>
                        </div>
                        <div
                          className="flex w-full min-w-0 flex-nowrap items-center justify-center gap-1.5 overflow-x-auto pb-0.5 [-ms-overflow-style:none] [scrollbar-width:thin] [&::-webkit-scrollbar]:h-1"
                          role="tablist"
                          aria-label="Draft review category"
                        >
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            role="tab"
                            aria-selected={draftReviewTab === "pending"}
                            className={cn(
                              "h-8 shrink-0 rounded-lg border-2 px-2.5 text-xs font-semibold sm:h-9 sm:px-3 sm:text-sm",
                              draftReviewTab === "pending"
                                ? "border-green-500 bg-green-600 text-white hover:bg-green-600 dark:border-green-400 dark:bg-green-600 dark:hover:bg-green-600"
                                : "border-green-600/50 bg-green-600/15 text-green-900 hover:bg-green-600/25 dark:border-green-600/45 dark:bg-green-950/40 dark:text-green-100 dark:hover:bg-green-950/55",
                            )}
                            onClick={() => setDraftReviewTab("pending")}
                          >
                            Pending review ({displayDraftReviewCounts.pendingReview})
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            role="tab"
                            aria-selected={draftReviewTab === "approved"}
                            className={cn(
                              "h-8 shrink-0 rounded-lg border-2 px-2.5 text-xs font-semibold sm:h-9 sm:px-3 sm:text-sm",
                              draftReviewTab === "approved"
                                ? "border-sky-500 bg-sky-600 text-white hover:bg-sky-600 dark:border-sky-400 dark:bg-sky-600 dark:hover:bg-sky-600"
                                : "border-sky-600/50 bg-sky-600/15 text-sky-950 hover:bg-sky-600/25 dark:border-sky-500/45 dark:bg-sky-950/40 dark:text-sky-100 dark:hover:bg-sky-950/55",
                            )}
                            onClick={() => setDraftReviewTab("approved")}
                          >
                            Approved ({displayDraftReviewCounts.approved})
                          </Button>
                        </div>
                        {reviewDraftsSnapModeVal === "loading" && draftsPanelLiteFiltered.length > 0 ? (
                          <>
                            <p className="text-xs text-muted-foreground" role="status">
                              Showing cached drafts — refreshing…
                            </p>
                            <div className="max-h-[min(60vh,480px)] space-y-2 overflow-y-auto rounded-xl border border-border p-2">
                              {draftsPanelLiteFiltered.map((d) => (
                                <div
                                  key={d.id}
                                  className="rounded-lg border border-border/80 bg-muted/20 px-3 py-2 text-sm"
                                >
                                  <div className="font-medium">{d.company || "Untitled"}</div>
                                  <div className="text-muted-foreground">{d.to_email || "—"}</div>
                                  <div className="mt-0.5 line-clamp-2">{d.subject || "—"}</div>
                                  <div className="mt-1 flex flex-wrap gap-1">
                                    <Badge variant="secondary" className="text-[10px] font-normal">
                                      {d.review_status}
                                    </Badge>
                                    <Badge variant="outline" className="text-[10px] font-normal">
                                      {d.tracking_status || d.status}
                                    </Badge>
                                  </div>
                                </div>
                              ))}
                            </div>
                          </>
                        ) : (
                          <SnapshotCardsPlaceholder
                            mode={reviewDraftsSnapModeVal}
                            kind="Draft"
                          />
                        )}
                      </div>
                    ) : null}
                  </div>
                )}
              </CardContent>
            </Card>
            ) : null}

            {mainNav === "contact-analyzer" && selectedRun?.id ? (
              <Card className="rounded-2xl border-2 border-border shadow-none">
                <CardHeader>
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div>
                      <CardTitle>Contact analyzer</CardTitle>
                      <CardDescription>
                        One row per unique email in this run. <strong>Verify</strong> runs a single Gmail search (to/from
                        that address); results are stored and Gmail is not queried again for the same address.
                      </CardDescription>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        disabled={
                          !gmailSendReady ||
                          analyzerBulkBusy ||
                          analyzerLoading ||
                          analyzerRows.filter((r) => r.gmail_history_status == null).length === 0
                        }
                        onClick={() => void verifyContactAnalyzerAll()}
                      >
                        {analyzerBulkBusy ? (
                          <>
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                            Verifying…
                          </>
                        ) : (
                          "Verify all"
                        )}
                      </Button>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3">
                  {!gmailSendReady ? (
                    <p className="text-sm text-muted-foreground">
                      Connect Gmail first — this tool checks your connected mailbox.
                    </p>
                  ) : analyzerLoading ? (
                    <p className="text-sm text-muted-foreground">Loading…</p>
                  ) : analyzerRows.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No contacts with an email in this run.</p>
                  ) : (
                    <>
                      {analyzerBulkNote ? (
                        <p className="text-sm text-muted-foreground">{analyzerBulkNote}</p>
                      ) : null}
                      <div className="overflow-x-auto rounded-xl border-2 border-border">
                        <table className="w-full min-w-[520px] text-left text-sm">
                          <thead className="border-b border-border bg-muted/40 text-xs font-semibold text-muted-foreground">
                            <tr>
                              <th className="px-3 py-2">Email</th>
                              <th
                                className="px-3 py-2"
                                aria-sort={analyzerGmailHistorySortDesc ? "descending" : "ascending"}
                              >
                                <button
                                  type="button"
                                  className="inline-flex max-w-full items-center gap-1 rounded-md text-left font-semibold text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                                  title={
                                    analyzerGmailHistorySortDesc
                                      ? "Gmail history: History detected first — click to sort the other way"
                                      : "Gmail history: Not verified first — click to reverse order"
                                  }
                                  onClick={() => {
                                    setAnalyzerGmailHistorySortDesc((d) => !d);
                                    setAnalyzerPage(1);
                                  }}
                                >
                                  Gmail history
                                  {analyzerGmailHistorySortDesc ? (
                                    <ArrowDownWideNarrow className="h-3.5 w-3.5 shrink-0 opacity-80" aria-hidden />
                                  ) : (
                                    <ArrowUpNarrowWide className="h-3.5 w-3.5 shrink-0 opacity-80" aria-hidden />
                                  )}
                                </button>
                              </th>
                              <th className="px-3 py-2 w-[120px]" />
                            </tr>
                          </thead>
                          <tbody>
                            {analyzerRowsPage.map((row) => {
                              const norm = row.email_normalized;
                              const st = row.gmail_history_status;
                              const pending = st == null;
                              return (
                                <tr key={norm} className="border-b border-border/80">
                                  <td className="px-3 py-2 align-middle">
                                    <span className="break-all font-medium">{row.email}</span>
                                  </td>
                                  <td className="px-3 py-2 align-middle">
                                    {pending ? (
                                      <Badge variant="secondary" className="font-normal">
                                        Not verified
                                      </Badge>
                                    ) : st === "no_history" ? (
                                      <Badge variant="outline" className="font-normal">
                                        No history
                                      </Badge>
                                    ) : (
                                      <div className="flex flex-wrap items-center gap-2">
                                        <Badge className="bg-emerald-600 font-normal hover:bg-emerald-600">
                                          History detected
                                        </Badge>
                                        {!row.gmail_inbox_imported_at ? (
                                          <Button
                                            type="button"
                                            size="sm"
                                            variant="outline"
                                            className="h-7 gap-1 rounded-full border-border px-2.5 text-xs font-normal"
                                            disabled={Boolean(analyzerRowBusy[norm]) || analyzerBulkBusy}
                                            onClick={() => void importContactAnalyzerInbox(norm)}
                                          >
                                            {analyzerRowBusy[norm] ? (
                                              <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" aria-hidden />
                                            ) : (
                                              <RefreshCw className="h-3.5 w-3.5 shrink-0" aria-hidden />
                                            )}
                                            Import 6 months
                                          </Button>
                                        ) : null}
                                      </div>
                                    )}
                                  </td>
                                  <td className="px-3 py-2 align-middle text-right">
                                    {pending ? (
                                      <Button
                                        type="button"
                                        size="sm"
                                        variant="outline"
                                        disabled={Boolean(analyzerRowBusy[norm]) || analyzerBulkBusy}
                                        onClick={() => void verifyContactAnalyzerOne(norm)}
                                      >
                                        {analyzerRowBusy[norm] ? (
                                          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                                        ) : (
                                          "Verify"
                                        )}
                                      </Button>
                                    ) : (
                                      <span className="text-xs text-muted-foreground">—</span>
                                    )}
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                      {analyzerRows.length > CONTACT_ANALYZER_PAGE_SIZE ? (
                        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between text-sm text-muted-foreground">
                          <span>
                            {(analyzerPage - 1) * CONTACT_ANALYZER_PAGE_SIZE + 1}–
                            {Math.min(analyzerPage * CONTACT_ANALYZER_PAGE_SIZE, analyzerRows.length)} of{" "}
                            {analyzerRows.length}
                          </span>
                          <div className="flex flex-wrap gap-2">
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              disabled={analyzerPage <= 1}
                              onClick={() => setAnalyzerPage((p) => Math.max(1, p - 1))}
                            >
                              Previous
                            </Button>
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              disabled={analyzerPage >= analyzerPageCount}
                              onClick={() => setAnalyzerPage((p) => Math.min(analyzerPageCount, p + 1))}
                            >
                              Next
                            </Button>
                          </div>
                        </div>
                      ) : analyzerRows.length > 0 ? (
                        <p className="text-xs text-muted-foreground">{analyzerRows.length} address(es) total.</p>
                      ) : null}
                    </>
                  )}
                </CardContent>
              </Card>
            ) : null}

            {!["runs", "contacts", "drafts", "companies", "contact-analyzer"].includes(mainNav) &&
            selectedRun?.id ? (
              <TrackingView
                runId={selectedRun.id}
                runSignatureHtml={selectedRun.sender_signature_html ?? ""}
                contextJson={selectedRun.context_json ?? {}}
                activeTab={mainNavToTrackingTab(mainNav)}
                singleTabMode
                onActiveTabChange={(tab) => setMainNav(trackingTabToMainNav(tab))}
                onRunWorkspaceRefresh={() => refreshRunDetailsInBackground(selectedRun.id)}
                workspaceDisplayPhase={workspace?.display_phase ?? selectedRun?.display_phase}
                cdnR2UploadReady={setupIntegration?.cdn_r2_upload_ready === true}
              />
            ) : null}

            {!["runs", "contacts", "drafts", "companies", "contact-analyzer"].includes(mainNav) &&
            !selectedRun?.id ? (
              <div className="rounded-2xl border-2 border-dashed border-border p-8 text-center text-sm text-muted-foreground">
                Select a run to view this section.
              </div>
            ) : null}
          </div>
        </div>
      </div>

      <Dialog open={newRunOpen} onOpenChange={setNewRunOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{newRunBaseline ? "Edit run" : "New run"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <p className="text-xs text-muted-foreground">
              This brief drives company search, contact roles, and the master email for the whole run.
              {newRunBaseline
                ? " Keep the same run name and use Update run for notes, segment, or brief. Change the run name to use Create run (new wave)."
                : null}
            </p>
            <div>
              <div className="mb-1 text-xs text-muted-foreground">
                Run name <span className="text-destructive">*</span>
              </div>
              <Input
                value={newRunForm.name}
                onChange={(e) => setNewRunForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="US distributors — April batch"
                aria-required
              />
            </div>
            <div>
              <div className="mb-1 text-xs text-muted-foreground">Notes (optional)</div>
              <Textarea
                value={newRunForm.notes}
                onChange={(e) => setNewRunForm((f) => ({ ...f, notes: e.target.value }))}
                placeholder="Internal notes for this wave (not sent to contacts)"
                rows={2}
              />
            </div>
            <div>
              <div className="mb-1 text-xs text-muted-foreground">
                Segment <span className="text-destructive">*</span>
              </div>
              <Input
                value={newRunForm.segment}
                onChange={(e) => setNewRunForm((f) => ({ ...f, segment: e.target.value }))}
                placeholder="List label: market, region, or audience"
                aria-required
              />
            </div>
            <div>
              <div className="mb-1 text-xs text-muted-foreground">
                Outreach brief <span className="text-destructive">*</span>
              </div>
              <Textarea
                value={newRunForm.outreach_brief}
                onChange={(e) => setNewRunForm((f) => ({ ...f, outreach_brief: e.target.value }))}
                placeholder={
                  "Offer:\nTarget:\nRoles:\nGoal:\nTone:\nNotes:"
                }
                rows={14}
                className="font-mono text-sm"
                aria-required
              />
              <p className="mt-1 text-xs text-muted-foreground">
                Use the labels <strong>Offer</strong>, <strong>Target</strong>, <strong>Roles</strong>,{" "}
                <strong>Goal</strong>, <strong>Tone</strong>, <strong>Notes</strong> (each line may continue on
                the next line until the next label). At least Offer or Goal must be filled in.
              </p>
            </div>
          </div>
          <DialogFooter className="flex flex-col gap-2 sm:flex-row sm:justify-end">
            <Button
              type="button"
              variant="outline"
              disabled={newRunDialogBusy}
              onClick={() => setNewRunOpen(false)}
            >
              Cancel
            </Button>
            {newRunBaseline ? (
              <>
                <Button
                  type="button"
                  variant="secondary"
                  disabled={!canUpdateRun || newRunDialogBusy}
                  onClick={() => void updateExistingRun()}
                >
                  {newRunUpdateInFlight ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                  ) : null}
                  Update run
                </Button>
                <Button
                  type="button"
                  disabled={!canCreateRunInDialog || newRunDialogBusy}
                  onClick={() => void createNewRun()}
                >
                  {newRunCreateInFlight ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                  ) : null}
                  Create run
                </Button>
              </>
            ) : (
              <Button
                type="button"
                disabled={!canSubmitNewRun || newRunDialogBusy}
                onClick={() => void createNewRun()}
              >
                {newRunCreateInFlight ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                ) : null}
                Create run
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={renameProjectOpen}
        onOpenChange={(open) => {
          setRenameProjectOpen(open);
          if (!open) {
            setRenameProjectId(null);
            setRenameProjectNameField("");
          }
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Rename project</DialogTitle>
          </DialogHeader>
          <div className="space-y-2 py-1">
            <label className="text-sm font-medium text-foreground" htmlFor="rename-project-name">
              Project name
            </label>
            <Input
              id="rename-project-name"
              value={renameProjectNameField}
              onChange={(e) => setRenameProjectNameField(e.target.value)}
              placeholder="Project name"
              disabled={renameProjectSaving}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void submitRenameProject();
                }
              }}
            />
          </div>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button
              type="button"
              variant="outline"
              disabled={renameProjectSaving}
              onClick={() => {
                setRenameProjectOpen(false);
                setRenameProjectId(null);
                setRenameProjectNameField("");
              }}
            >
              Cancel
            </Button>
            <Button
              type="button"
              disabled={renameProjectSaving || !renameProjectNameField.trim()}
              onClick={() => void submitRenameProject()}
            >
              {renameProjectSaving ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                  Renaming…
                </>
              ) : (
                "Rename"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={switchRunOpen} onOpenChange={setSwitchRunOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Switch run</DialogTitle>
          </DialogHeader>
          <ScrollArea className="max-h-[360px] pr-3">
            <div className="space-y-2 py-2">
              {runsList.map((r) => {
                const isCurrent = selectedRun?.id === r.id;
                return (
                  <button
                    key={r.id}
                    type="button"
                    aria-current={isCurrent ? "true" : undefined}
                    className={`w-full rounded-2xl border-2 p-3 text-left text-sm transition-colors hover:bg-muted/50 ${
                      isCurrent ? "border-primary bg-primary/5" : "border-border"
                    }`}
                    onClick={() => void openRunById(r.id)}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{r.name}</span>
                      {isCurrent ? (
                        <Badge variant="secondary" className="font-normal text-xs">
                          Current
                        </Badge>
                      ) : null}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {r.display_phase} · Companies {r.companies_count} · Contacts {r.contacts_count} · Sent{" "}
                      {r.emails_sent}
                    </div>
                  </button>
                );
              })}
              {!runsList.length ? (
                <p className="text-sm text-muted-foreground">No runs in this project.</p>
              ) : null}
            </div>
          </ScrollArea>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setSwitchRunOpen(false)}>
              Cancel
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={closeRunOpen} onOpenChange={setCloseRunOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Close run?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            This run will no longer be used for new outreach sending. Existing threads, replies,
            reminders, and packets will remain available.
          </p>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button type="button" variant="outline" onClick={() => setCloseRunOpen(false)}>
              Cancel
            </Button>
            <Button type="button" variant="destructive" onClick={() => void confirmCloseRun()}>
              Close run
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {editDraft ? (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
          <button
            type="button"
            className="fixed inset-0 bg-black/50"
            aria-label="Close"
            disabled={editDraftSaving}
            onClick={() => {
              if (!editDraftSaving) setEditDraft(null);
            }}
          />
          <div className="relative z-50 w-full max-w-2xl rounded-xl border-2 border-border bg-card p-6 shadow-lg">
            <h2 className="text-lg font-semibold">Edit email draft</h2>
            <div className="mt-4 grid gap-3">
              <Input
                placeholder="Subject"
                value={draftForm.subject}
                onChange={(e) => setDraftForm((f) => ({ ...f, subject: e.target.value }))}
              />
              <EmailDraftRichTextEditor
                key={editDraft.id}
                initialBody={draftForm.body}
                onChange={(body) => setDraftForm((f) => ({ ...f, body }))}
              />
              <DraftAssetAttachmentsField
                assets={assetsLibrary}
                assetPackets={runAssetPackets}
                selectedIds={draftForm.attached_asset_ids}
                onSelectedIdsChange={(attached_asset_ids) =>
                  setDraftForm((f) => ({ ...f, attached_asset_ids }))
                }
              />
            </div>
            <div className="mt-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
              <label className="flex max-w-[min(100%,20rem)] cursor-pointer items-start gap-2.5 text-sm leading-snug text-muted-foreground">
                <input
                  type="checkbox"
                  className="mt-0.5 h-4 w-4 shrink-0 rounded border-2 border-border accent-primary"
                  checked={applyAssetsToAllPendingDrafts}
                  disabled={editDraftSaving}
                  onChange={(e) => setApplyAssetsToAllPendingDrafts(e.target.checked)}
                />
                <span>
                  <span className="font-medium text-foreground">Apply assets to all drafts</span>
                  <span className="mt-0.5 block text-xs">
                    Pending review only — same attachments as here after Save.
                  </span>
                </span>
              </label>
              <div className="flex shrink-0 justify-end gap-2">
                <Button variant="outline" disabled={editDraftSaving} onClick={() => setEditDraft(null)}>
                  Cancel
                </Button>
                <Button
                  type="button"
                  disabled={editDraftSaving}
                  aria-busy={editDraftSaving}
                  onClick={() => void saveEditDraft()}
                >
                  {editDraftSaving ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                  ) : null}
                  Save
                </Button>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {restartDialogOpen && restartDialogRun ? (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
          <button
            type="button"
            className="fixed inset-0 bg-black/50"
            aria-label="Close"
            onClick={closeRestartDialog}
          />
          <div className="relative z-50 w-full max-w-lg rounded-xl border-2 border-border bg-card p-6 shadow-lg">
            <h2 className="text-lg font-semibold">Continue outreach</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              <span className="font-medium text-foreground">{restartDialogRun.name}</span>
              {" — "}
              company search and contact validation will run again on top of what you already have (same brief). Existing
              contacts, drafts, and tracking data stay in place; new companies or contacts are merged in. After you
              confirm, this window closes; progress appears as a slim banner under the page title.
            </p>
            <div className="mt-6 flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={closeRestartDialog}>
                Cancel
              </Button>
              <Button type="button" onClick={() => void confirmRestartRun()} disabled={pendingRestart != null}>
                Continue...
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      {promptSetupOpen ? (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
          <button
            type="button"
            className="fixed inset-0 bg-black/50"
            aria-label="Close"
            disabled={promptSetupSaving}
            onClick={() => {
              if (!promptSetupSaving) setPromptSetupOpen(false);
            }}
          />
          <div className="relative z-50 w-full max-w-2xl rounded-xl border-2 border-border bg-card p-6 shadow-lg">
            <h2 className="text-lg font-semibold">Prompt setup</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Labeled outreach brief (same shape as when the run was created). If nothing was saved yet, this opens with
              the current run values. When a non-empty prompt is saved, each new approved contact gets a draft via the
              LLM from this brief plus recipient details; Regenerate uses the same. If the prompt is empty, drafts use
              the standard master variants from run setup. Saving updates the stored text only — use Regenerate or new
              approvals to refresh existing drafts.
            </p>
            <div className="mt-4">
              <Textarea
                value={promptSetupText}
                onChange={(e) => setPromptSetupText(e.target.value)}
                className="min-h-[280px] font-mono text-sm"
                spellCheck={false}
              />
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={promptSetupSaving}
                onClick={() => setPromptSetupOpen(false)}
              >
                Cancel
              </Button>
              <Button type="button" disabled={promptSetupSaving} onClick={() => void savePromptSetup()}>
                {promptSetupSaving ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                ) : null}
                Save
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      {gmailSetupOpen ? (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
          <button
            type="button"
            className="fixed inset-0 bg-black/50"
            aria-label="Close"
            onClick={() => setGmailSetupOpen(false)}
          />
          <div className="relative z-50 max-h-[90vh] w-full max-w-5xl overflow-y-auto rounded-xl border-2 border-border bg-card p-6 shadow-lg sm:p-8">
            <h2 className="text-lg font-semibold">Connect Gmail</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              One Google mailbox sends all outreach from this deployment. Sending uses the real Gmail API — not a mock
              — once the three variables at the bottom of this dialog are present in{" "}
              <span className="font-mono text-foreground/90">backend/.env</span> for the API process that answers{" "}
              <span className="font-mono text-foreground/90">/setup/status</span>.
            </p>
            <div className="mt-3 rounded-lg border border-blue-500/35 bg-blue-500/10 px-3 py-2 text-xs leading-relaxed text-foreground">
              <span className="font-medium text-foreground">Important — finish in this browser tab: </span>
              Do <strong>not</strong> copy links from Google screens (
              <span className="font-mono">oauth/warning</span>, <span className="font-mono">consentsummary</span>, etc.).
              The app only receives tokens after Google <strong>redirects your browser</strong> to{" "}
              <span className="font-mono break-all">…/api/oauth/google/callback?code=…</span>, then back here with{" "}
              <span className="font-mono">?gmail_connected=1</span> or <span className="font-mono">?gmail_error=…</span>{" "}
              in the address bar. If Google shows &quot;Google hasn&apos;t verified this app&quot;, open{" "}
              <strong>Advanced</strong> / <strong>Continue</strong> (unsafe). Until that final redirect happens, nothing is
              written to <span className="font-mono">.env</span>.
            </div>
            {setupIntegration && setupIntegration.gmail_send_ready !== true ? (
              <div className="mt-3 rounded-lg border border-amber-500/45 bg-amber-500/10 px-3 py-2.5 text-sm leading-relaxed text-amber-950 dark:text-amber-50">
                <p className="font-medium text-foreground">If you already edited backend/.env but the status still looks wrong</p>
                <ul className="mt-2 list-disc space-y-1.5 pl-5 text-foreground/90">
                  <li>
                    The UI reflects what the <strong>running API</strong> sees — not only the file open in your editor.
                    Below, check &quot;API loads variables from&quot; and compare with the file you saved.
                  </li>
                  <li>
                    <strong>Docker:</strong> Compose <span className="font-mono text-xs">env_file</span> is applied when the
                    container is <strong>created</strong>. After adding <span className="font-mono text-xs">GOOGLE_REFRESH_TOKEN</span>{" "}
                    on the host, recreate the backend (for example{" "}
                    <span className="font-mono text-xs">
                      docker compose -f infra/docker-compose.yml up -d --force-recreate backend
                    </span>
                    ). Optional: bind-mount <span className="font-mono text-xs">backend/.env</span> →{" "}
                    <span className="font-mono text-xs">/app/.env</span> so file edits are picked up without stale env (
                    <span className="font-mono text-xs">infra/docker-compose.bind-env.yml</span>).
                  </li>
                  <li>
                    Key name must be exactly <span className="font-mono text-xs">GOOGLE_REFRESH_TOKEN</span> (see{" "}
                    <span className="font-mono text-xs">backend/.env.example</span>). If you have more than one{" "}
                    <span className="font-mono text-xs">.env</span>, the <strong>later</strong> path in the list below wins for
                    duplicate names.
                  </li>
                  <li>
                    CLI fallback (no in-app redirect): from <span className="font-mono text-xs">ai-biz-os/backend</span> run{" "}
                    <span className="font-mono text-xs">python3 scripts/fetch_google_refresh_token.py</span> — add its localhost
                    callback URI in Google Cloud next to the web callback.
                  </li>
                </ul>
              </div>
            ) : null}
            {gmailSetupHintsFromApi.length ? (
              <div
                className="mt-3 rounded-lg border border-muted bg-muted/30 px-3 py-2 text-xs leading-relaxed text-foreground/90"
                role="status"
              >
                <span className="font-medium text-foreground">API notes: </span>
                <ul className="mt-1.5 list-disc space-y-1 pl-5">
                  {gmailSetupHintsFromApi.map((h) => (
                    <li key={h}>{h.replace(/^Gmail setup:\s*/, "")}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            {gmailSetupErr ? (
              <div
                className="mt-3 flex items-start gap-2 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
                role="alert"
              >
                <p className="min-w-0 flex-1">{gmailSetupErr}</p>
                <button
                  type="button"
                  className="shrink-0 rounded-md p-1 opacity-80 hover:bg-destructive/15 hover:opacity-100"
                  aria-label="Dismiss"
                  onClick={() => setGmailSetupErr("")}
                >
                  <X className="h-4 w-4" aria-hidden />
                </button>
              </div>
            ) : null}
            {setupIntegration?.env_write_blocked_reason ? (
              <div
                className="mt-3 rounded-lg border border-amber-500/50 bg-amber-500/10 px-3 py-2 text-sm text-amber-950 dark:text-amber-100"
                role="status"
              >
                <span className="font-medium">Saving to .env is disabled in the running API: </span>
                {setupIntegration.env_write_blocked_reason}
              </div>
            ) : null}
            {setupIntegration?.env_paths_found?.length ? (
              <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
                API loads variables from (later paths override earlier):{" "}
                <span className="font-mono text-[11px] text-foreground/90">
                  {setupIntegration.env_paths_found.join(" → ")}
                </span>
                . After a <strong>successful</strong> callback (see green note above),{" "}
                <span className="font-medium text-foreground">GOOGLE_REFRESH_TOKEN</span> is written when saving is
                allowed. In Docker without mounting host <span className="font-mono">backend/.env</span> to{" "}
                <span className="font-mono">/app/.env</span>, the refresh token may exist only inside the container —
                check <span className="font-mono">infra/docker-compose.yml</span> comments. Current: client{" "}
                {setupIntegration.gmail_client_configured ? "✓" : "✗"}, refresh token{" "}
                {setupIntegration.gmail_refresh_token_set ? "✓" : "✗"}.
              </p>
            ) : null}
            <ol className="mt-4 list-decimal space-y-2 pl-5 text-sm text-foreground">
              <li>
                In{" "}
                <a
                  className="font-medium text-accent underline"
                  href="https://console.cloud.google.com/apis/credentials"
                  target="_blank"
                  rel="noreferrer"
                >
                  Google Cloud Console → Credentials
                </a>
                , create an OAuth 2.0 Client ID (Web application).
              </li>
              <li>
                In that <strong>same</strong> project:{" "}
                <a
                  className="font-medium text-accent underline"
                  href="https://console.cloud.google.com/apis/library/gmail.googleapis.com"
                  target="_blank"
                  rel="noreferrer"
                >
                  APIs &amp; Services → Library
                </a>{" "}
                → open <strong>Gmail API</strong> → <strong>Enable</strong>. Without this, OAuth succeeds but sending
                mail returns 403 (Gmail API disabled).
              </li>
              <li>
                Under Authorized redirect URIs, add:
                <div className="mt-1 rounded-lg border border-muted bg-muted/40 px-2 py-1.5 font-mono text-xs break-all">
                  {`${typeof window !== "undefined" ? window.location.origin : ""}/api/oauth/google/callback`}
                </div>
                <span className="text-muted-foreground">
                  (Must match this app&apos;s address bar origin. Optional: set GOOGLE_REDIRECT_URI in backend
                  <span className="font-mono">.env</span> instead.)
                </span>
              </li>
              <li>
                If Google says the app is blocked or did not pass verification: open{" "}
                <a
                  className="font-medium text-accent underline"
                  href="https://console.cloud.google.com/apis/credentials/consent"
                  target="_blank"
                  rel="noreferrer"
                >
                  OAuth consent screen
                </a>
                , leave <span className="font-medium">Publishing status</span> as <strong>Testing</strong> for dev, and
                add your Google account under <strong>Test users</strong>. Only those accounts can sign in until the app
                passes Google&apos;s production verification (not required for a single mailbox you control).
              </li>
              <li>
                Paste Client ID and Client Secret below and save into backend <span className="font-mono">.env</span>{" "}
                {setupIntegration?.allow_env_write ? (
                  <span className="text-muted-foreground">(allowed here in this environment).</span>
                ) : (
                  <span className="text-amber-800 dark:text-amber-200">
                    — browser save is disabled; add them to <span className="font-mono">.env</span> manually and restart
                    the API, then leave these fields empty and click Connect.
                  </span>
                )}
              </li>
              <li>
                Click <span className="font-medium">Connect Gmail</span>, complete consent, then the API exchanges the
                code, sends a test email to the same mailbox with subject{" "}
                <span className="font-mono">Business outreach dashboard check</span>, reads it back, and stores a
                refresh token in <span className="font-mono">.env</span> when saving is enabled.
              </li>
              <li>
                Access tokens refresh automatically. If the refresh is revoked or expires and cannot be renewed, the red
                indicator returns — open this dialog and connect again.
              </li>
            </ol>
            <div className="mt-4 space-y-3">
              <div>
                <div className="mb-1 text-xs text-muted-foreground">OAuth Client ID</div>
                <Input
                  value={gmailForm.clientId}
                  onChange={(e) => setGmailForm((f) => ({ ...f, clientId: e.target.value }))}
                  autoComplete="off"
                  spellCheck={false}
                  className="font-mono text-sm"
                  placeholder="xxxxx.apps.googleusercontent.com"
                />
              </div>
              <div>
                <div className="mb-1 text-xs text-muted-foreground">OAuth Client secret</div>
                <Input
                  type="password"
                  value={gmailForm.clientSecret}
                  onChange={(e) => setGmailForm((f) => ({ ...f, clientSecret: e.target.value }))}
                  autoComplete="off"
                  spellCheck={false}
                  className="font-mono text-sm"
                />
              </div>
              <div>
                <div className="mb-1 text-xs text-muted-foreground">Optional: override redirect URI (else origin-based)</div>
                <Input
                  value={gmailForm.redirectUri}
                  onChange={(e) => setGmailForm((f) => ({ ...f, redirectUri: e.target.value }))}
                  autoComplete="off"
                  spellCheck={false}
                  className="font-mono text-sm"
                  placeholder="https://your-host/api/oauth/google/callback"
                />
              </div>
            </div>
            <div className="mt-6 flex flex-wrap justify-end gap-2">
              <Button type="button" variant="outline" onClick={() => setGmailSetupOpen(false)} disabled={gmailSetupBusy}>
                Cancel
              </Button>
              <Button type="button" onClick={() => void connectGmailOAuth()} disabled={gmailSetupBusy}>
                {gmailSetupBusy ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                    Redirecting…
                  </>
                ) : (
                  <>
                    <Mail className="mr-2 h-4 w-4" aria-hidden />
                    Connect Gmail
                  </>
                )}
              </Button>
            </div>
            <div className="mt-6 rounded-xl border border-primary/25 bg-primary/5 px-4 py-3 text-sm leading-relaxed">
              <p className="font-medium text-foreground">What “ready to send” actually means</p>
              <p className="mt-1 text-muted-foreground">
                The dashboard turns green when this deployment&apos;s API loads all three values (non-empty) from the{" "}
                <span className="font-mono text-[13px] text-foreground/90">.env</span> chain it lists above. Names must match
                exactly:
              </p>
              <ul className="mt-2 space-y-1.5 font-mono text-[13px] text-foreground/95">
                <li className="rounded-md bg-background/80 px-2 py-1.5">GOOGLE_CLIENT_ID</li>
                <li className="rounded-md bg-background/80 px-2 py-1.5">GOOGLE_CLIENT_SECRET</li>
                <li className="rounded-md bg-background/80 px-2 py-1.5">GOOGLE_REFRESH_TOKEN</li>
              </ul>
              <p className="mt-2 text-xs text-muted-foreground">
                They belong in <span className="font-mono text-[12px] text-foreground/80">ai-biz-os/backend/.env</span> on the
                host (or the paths your compose file / <span className="font-mono text-[12px]">AI_BIZ_OS_DOTENV</span> use).
                Optional: <span className="font-mono text-[12px]">GOOGLE_REDIRECT_URI</span> if your public URL is not the
                browser origin shown in step 2.
              </p>
            </div>
          </div>
        </div>
      ) : null}

      {signatureSetupOpen ? (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
          <button
            type="button"
            className="fixed inset-0 bg-black/50"
            aria-label="Close"
            disabled={signatureSetupSaving}
            onClick={() => {
              if (!signatureSetupSaving) setSignatureSetupOpen(false);
            }}
          />
          <div className="relative z-50 w-full max-w-2xl rounded-xl border-2 border-border bg-card p-6 shadow-lg">
            <h2 className="text-lg font-semibold">Signature setup</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Rich-text signature for this run. It is appended when sending outreach and reply drafts. After you save, if
              a signature is set, outreach and reply draft previews add{" "}
              <span className="font-mono text-xs">[Signature]</span> on its own line at the end.
            </p>
            <div className="mt-4">
              {signatureEditorMount ? (
                <EmailDraftRichTextEditor
                  key={signatureEditorKey}
                  initialBody={signatureFormHtml}
                  onChange={setSignatureFormHtml}
                />
              ) : (
                <div
                  className="flex min-h-[260px] items-center justify-center rounded-md border border-input bg-muted/20 text-sm text-muted-foreground"
                  aria-hidden
                >
                  Loading editor…
                </div>
              )}
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <Button
                variant="outline"
                disabled={signatureSetupSaving}
                onClick={() => setSignatureSetupOpen(false)}
              >
                Cancel
              </Button>
              <Button type="button" disabled={signatureSetupSaving} onClick={() => void saveSignatureSetup()}>
                {signatureSetupSaving ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                ) : null}
                Save
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
