import React, {
  Fragment,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
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
import { RunSetupHourlySendsChart } from "@/components/RunSetupHourlySendsChart";
import { cn } from "@/lib/utils";
import {
  snapshotMergeRunSetupBodiesFromRun,
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
  snapshotReadTotalPerformance,
  snapshotWriteLastContext,
  snapshotWriteProjects,
  snapshotWriteRunCards,
  snapshotWriteRunSetupPrefs,
  snapshotWriteRuns,
  snapshotWriteTotalPerformance,
} from "@/lib/humanUiSnapshot";
import {
  MAX_CONTACTS_PANEL_LITE,
  stripContactForPanelLite,
  stripDraftForPanelLite,
} from "@/lib/runPanelLite";
import { fetchAllPagedItems } from "@/lib/paginatedApi";
import { formatDateTimeYmdHms, formatDateYmd } from "@/lib/formatDate";
import {
  Archive,
  ArchiveRestore,
  ArrowDownWideNarrow,
  ArrowUpNarrowWide,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  CircleX,
  Clock,
  FileText,
  Loader2,
  Mail,
  Notebook,
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
const API_BASE =
  ENV_API && ENV_API.length > 0
    ? ENV_API.replace(/\/$/, "")
    : import.meta.env.DEV
      ? "/api"
      : "http://127.0.0.1:8000";

/** GET /email-drafts/run/:id — compact list (`body_preview` only; full `body` via GET /email-drafts/:id when editing). */
function emailDraftsRunListPath(runId) {
  return `/email-drafts/run/${runId}`;
}

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
  "Respondent's field of activity:\n\n" +
  "Narrowly focused areas of activity:\n\n" +
  "Reason for search (licensing, sales, partnership):\n\n" +
  "How long has the respondent company been in the market:\n\n" +
  "Additional information:\n\n";

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

/** Lite snapshot + cached cards — only drafts still in the Review pipeline (not historical sent rows). */
function draftsForRunPanelLitePreview(draftsArray) {
  if (!Array.isArray(draftsArray)) return [];
  return draftsArray.filter((d) => !isOutboundDraftClosedForReview(d));
}

function DraftCollapsibleSection({ title, children, className }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={cn("rounded-lg border border-border bg-muted/20 p-3", className)}>
      <button
        type="button"
        className="flex w-full items-center gap-2 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground hover:text-foreground"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <ChevronDown
          className={cn("h-4 w-4 shrink-0 transition-transform", open && "rotate-180")}
          aria-hidden
        />
        {title}
      </button>
      {open ? <div className="mt-2">{children}</div> : null}
    </div>
  );
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

/** GET /contacts/run/:id — array, or paginated { items }, or bucket { contacts }. */
function normalizeContactsRunPayload(data) {
  if (Array.isArray(data)) return data;
  if (data && typeof data === "object" && Array.isArray(data.items)) return data.items;
  if (data && typeof data === "object" && Array.isArray(data.contacts)) return data.contacts;
  return [];
}

function mergeDraftReviewSnap(snap, live) {
  const liveSum = (live.pendingReview ?? 0) + (live.approved ?? 0);
  /** Prefer live counts whenever we already have draft rows — stale inner-tab snapshot must not override (e.g. after approve + poll refresh without draftsListReadyRunId set). */
  if (liveSum > 0) return live;
  if (!snap || typeof snap !== "object") return live;
  return {
    pendingReview: snap.pendingReview ?? 0,
    approved: snap.approved ?? 0,
  };
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
      className="rounded-2xl border-2 border-dashed border-muted-foreground/25 py-10 text-center text-sm text-muted-foreground"
      role="status"
      aria-live="polite"
    >
      <p>{kind} data is loading…</p>
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

/** One row in the Switch run dialog (open + closed sections use the same layout). */
function SwitchRunListRow({ run, selectedRun, onSelect }) {
  const isCurrent = selectedRun?.id === run.id;
  return (
    <button
      type="button"
      aria-current={isCurrent ? "true" : undefined}
      className={`w-full rounded-2xl border-2 p-3 text-left text-sm transition-colors hover:bg-muted/50 ${
        isCurrent ? "border-primary bg-primary/5" : "border-border"
      }`}
      onClick={() => void onSelect(run.id, run)}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{run.name}</span>
        {isCurrent ? (
          <Badge variant="secondary" className="font-normal text-xs">
            Current
          </Badge>
        ) : null}
      </div>
      <div className="space-y-0.5 text-xs text-muted-foreground">
        <div>{run.display_phase}</div>
        <div>
          Companies {run.companies_count} · Contacts {run.contacts_count}
        </div>
        <div>
          Sent {run.emails_sent} · Replies {run.replies} · Threads {run.active_threads}
        </div>
      </div>
    </button>
  );
}

/** Longest first so e.g. "professional notes:" wins over embedded "notes:". */
const BRIEF_LABEL_PREFIXES = [
  ["how long has the respondent company been in the market:", "offer"],
  ["reason for search (licensing, sales, partnership):", "goal"],
  ["narrowly focused areas of activity:", "target_roles"],
  ["respondent's field of activity:", "target_entities"],
  ["additional information:", "notes"],
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

/** Mirrors backend outreach_brief_has_minimum_content (search + legacy Offer/Goal). */
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
  return Boolean(
    (acc.goal && acc.goal.length > 0) ||
      (acc.target_entities && acc.target_entities.length > 0) ||
      (acc.offer && acc.offer.length > 0) ||
      (acc.target_roles && acc.target_roles.length > 0),
  );
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
  const tone = String(ctx.tone ?? "").trim();
  const extra = String(ctx.notes ?? "").trim();
  let notes = extra;
  if (tone && tone.toLowerCase() !== "professional") {
    notes = notes ? `${notes}\n\n(Previous tone: ${tone})` : `(Previous tone: ${tone})`;
  }
  return [
    "Respondent's field of activity:",
    ctx.target_entities || "",
    "",
    "Narrowly focused areas of activity:",
    ctx.target_roles || "",
    "",
    "Reason for search (licensing, sales, partnership):",
    ctx.goal || "",
    "",
    "How long has the respondent company been in the market:",
    ctx.offer || "",
    "",
    "Additional information:",
    notes || "",
    "",
  ].join("\n");
}

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

/** After failed optimistic Prompt/Signature save: full prefs row for snapshotWriteRunSetupPrefs (before may be null). */
function runSetupPrefsRollbackPartial(prefsBefore, prevRun) {
  if (prefsBefore != null) {
    return {
      prompt_setup_saved: Boolean(prefsBefore.prompt_setup_saved),
      sender_signature_configured: Boolean(prefsBefore.sender_signature_configured),
      prompt_setup_text:
        typeof prefsBefore.prompt_setup_text === "string" ? prefsBefore.prompt_setup_text : "",
      signature_html: typeof prefsBefore.signature_html === "string" ? prefsBefore.signature_html : "",
    };
  }
  const pt = typeof prevRun?.prompt_setup_text === "string" ? prevRun.prompt_setup_text : "";
  return {
    prompt_setup_saved: pt.trim().length > 0,
    sender_signature_configured: runSignatureHasMeaningfulContent(prevRun?.sender_signature_html ?? ""),
    prompt_setup_text: pt,
    signature_html: String(prevRun?.sender_signature_html ?? ""),
  };
}

function getPromptSetupEditorInitialText(run) {
  if (!run) return DEFAULT_OUTREACH_BRIEF;
  if (typeof run.prompt_setup_text === "string" && run.prompt_setup_text.length > 0) {
    return run.prompt_setup_text;
  }
  const ctx = contextFromRun(run);
  return contextToOutreachBriefText(ctx);
}

/** Instant dialog text: cached bodies (localStorage) beat card-only selectedRun (no context_json). */
function getPromptSetupDialogSeed(runId, selectedRun) {
  const snap = snapshotReadRunSetupPrefs(runId);
  if (snap && typeof snap.prompt_setup_text === "string") {
    return snap.prompt_setup_text;
  }
  return getPromptSetupEditorInitialText(selectedRun);
}

function getSignatureDialogSeed(runId, selectedRun, workspace) {
  const snap = snapshotReadRunSetupPrefs(runId);
  if (snap && typeof snap.signature_html === "string") {
    return snap.signature_html;
  }
  return String(selectedRun?.sender_signature_html ?? workspace?.sender_signature_html ?? "");
}

/** Prefill dialog from a run (GET /runs/:id or selected run). */
function seedNewRunFormFromRun(run) {
  if (!run) {
    return {
      name: "",
      notes: "",
      segment: "",
      outreach_brief: DEFAULT_OUTREACH_BRIEF,
      email_style_mode: "auto",
    };
  }
  const ctx = contextFromRun(run);
  const brief = ctx ? contextToOutreachBriefText(ctx) : DEFAULT_OUTREACH_BRIEF;
  const baseName = String(run.name ?? "").trim();
  const seg = String(run.segment ?? "").trim();
  const dateStr = formatDateYmd(new Date());
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
    email_style_mode: normalizeProfessionalProfileFromApi(run?.email_style_mode),
  };
}

/** Prefill from GET /runs/:id/edit-form — avoids full RunRead (large JSON). */
function seedNewRunFormFromEditFormRead(payload) {
  if (!payload || typeof payload !== "object") {
    return seedNewRunFormFromRun(null);
  }
  const baseName = String(payload.name ?? "").trim();
  const seg = String(payload.segment ?? "").trim();
  const dateStr = formatDateYmd(new Date());
  const name = baseName ? baseName : seg ? seg : `Outreach wave · ${dateStr}`;
  return {
    name,
    notes: String(payload.notes ?? "").trim(),
    segment: seg,
    outreach_brief: String(payload.outreach_brief ?? "").trim() || DEFAULT_OUTREACH_BRIEF,
    email_style_mode: normalizeProfessionalProfileFromApi(payload.email_style_mode),
  };
}

/** Default timeout so the UI never sits on “Loading…” forever if the proxy/API hangs. */
const API_TIMEOUT_MS = 25000;
/** POST /runs/start runs `run_workflow` synchronously on the server (same class of long work as restart). */
const START_RUN_TIMEOUT_MS = 600000;
/** Single-company find retry calls the LLM again; allow longer than default API timeout. */
const COMPANY_RETRY_FIND_TIMEOUT_MS = 120000;
/** POST …/companies/analyze-fit-pending — many LLM calls in one request. */
const COMPANY_AI_FIT_BATCH_TIMEOUT_MS = 600000;
/** Background PATCH after optimistic UI; server is fast — this bounds how long we retry reconciling. */
const RUN_SETUP_PATCH_TIMEOUT_MS = 45000;
/** GET /runs/:id/review-setup-fields — tiny JSON for Prompt/Signature dialogs (no full run row). */
const RUN_REVIEW_SETUP_LITE_TIMEOUT_MS = 20000;
/** Run-details bundle is many parallel GETs; allow the same headroom when refreshing after setup saves. */
const LOAD_RUN_DETAILS_BUNDLE_TIMEOUT_MS = 120000;
/** Edit-form is light on the server; client timeout is generous so a slow/blocked worker does not fail before heavier GET /runs. */
const EDIT_FORM_OPEN_TIMEOUT_MS = LOAD_RUN_DETAILS_BUNDLE_TIMEOUT_MS;
/** GET /runs/:id/companies — allow long wait when the server worker is busy (do not abort client-side). */
const COMPANIES_HTTP_TIMEOUT_MS = 300000;
/** POST /sending/.../mock-send-preview — synchronous Gmail on server; allow long wait. */
const MOCK_SEND_PREVIEW_POST_TIMEOUT_MS = 120000;
/** Poll GET /email-drafts/:id until terminal status (API returns 202 immediately; Gmail runs in background). */
const OUTBOUND_SEND_POLL_MS = 2000;
const OUTBOUND_SEND_POLL_MAX = 30;
/** After «Send all approved»: poll draft list this often so cards leave Review one-by-one (sequential Gmail). */
const BULK_SEND_DRAFTS_POLL_MS = 450;
const BULK_SEND_DRAFTS_POLL_MAX_ITER = 140;
/** Background poll / metrics-only refresh: workspace-tick + global performance (no contact/draft lists). */
const POLL_METRICS_TIMEOUT_MS = 60000;
/** Don’t spam the activity log with the same silent metrics failure on every poll tick. */
const METRICS_SILENT_FAILURE_LOG_INTERVAL_MS = 45000;
/** GET /email-drafts/:id for edit modal — list often already has full body; this caps wait when a second GET is needed. */
const EMAIL_DRAFT_GET_FOR_EDIT_TIMEOUT_MS = 45000;
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
/** One GET loads up to this many company rows; pagination is client-side only. */
const COMPANIES_FETCH_MAX = 500;
/** Retry-all queue scan: find next candidate across this many companies (API allows up to 5000). */
const COMPANIES_RETRY_QUEUE_SCAN_MAX = 5000;

function normalizeCompaniesPanelResponse(data, offsetFallback = 0) {
  const rawList = data?.companies;
  const companies = Array.isArray(rawList) ? rawList : [];
  const totalRaw = data?.companies_total;
  const pageLen = companies.length;
  const respOffset = Number(data?.offset ?? offsetFallback);
  const minTotalFromPaging = respOffset + pageLen;
  const parsedTotal =
    typeof totalRaw === "number" && Number.isFinite(totalRaw)
      ? totalRaw
      : typeof totalRaw === "string" && String(totalRaw).trim() !== ""
        ? Number(totalRaw)
        : NaN;
  const companies_total = Number.isFinite(parsedTotal)
    ? Math.max(parsedTotal, minTotalFromPaging)
    : respOffset > 0
      ? minTotalFromPaging
      : pageLen;
  return {
    ...data,
    companies,
    companies_total,
    offset: respOffset,
    limit: data?.limit != null ? Number(data.limit) : COMPANIES_FETCH_MAX,
  };
}

/** Single numeric key for per-row company UI state (must match between queue scan API and table rows). */
function normalizeCompanyCollectIndex(row) {
  if (row == null || typeof row !== "object") return null;
  const n = Number(row.collect_index);
  return Number.isFinite(n) && n >= 0 ? n : null;
}

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
  const outreachPart = si?.apollo_outreach_ready === true ? "Apollo" : "—";
  return { llmPart, cdnPart, outreachPart };
}

/** Known-fixed server bug text — hide in Review even if drafts state was cached before API strip. */
function isStaleOutboundDraftErrorMessage(msg) {
  if (msg == null || msg === "") return false;
  return String(msg).toLowerCase().includes("simplenamespace");
}

/** Append server-pushed Activity lines (e.g. Apollo progress) from workspace-lite / workspace-tick. */
function appendHumanUiActivityInformers(lite, appendLog) {
  const rows = lite?.activity_informers;
  if (!Array.isArray(rows) || rows.length === 0) return;
  for (const row of rows) {
    const text = typeof row?.text === "string" ? row.text.trim() : "";
    if (!text) continue;
    appendLog(text);
  }
}

/** Merge GET /runs/:id/workspace-lite or workspace-tick into existing workspace (metrics-only refresh path). */
function mergeWorkspaceLiteInto(prevWorkspace, lite) {
  if (!lite || typeof lite !== "object") return prevWorkspace;
  const base =
    prevWorkspace && typeof prevWorkspace === "object"
      ? prevWorkspace
      : {
          display_phase: lite.display_phase ?? "Preparing",
          setup_state_message: lite.setup_state_message ?? "",
          setup_summary: {},
          setup_steps: [],
          performance: {},
          conversations: {},
          hourly_sends_24h: Array.isArray(lite.hourly_sends_24h) ? lite.hourly_sends_24h : [],
        };
  const next = {
    ...base,
    display_phase: lite.display_phase ?? base.display_phase,
    setup_state_message: lite.setup_state_message ?? base.setup_state_message,
    performance: {
      ...(base.performance && typeof base.performance === "object" ? base.performance : {}),
      ...(lite.performance && typeof lite.performance === "object" ? lite.performance : {}),
    },
    conversations: {
      ...(base.conversations && typeof base.conversations === "object" ? base.conversations : {}),
      ...(lite.conversations && typeof lite.conversations === "object" ? lite.conversations : {}),
    },
  };
  if (lite.setup_summary && typeof lite.setup_summary === "object") {
    next.setup_summary = lite.setup_summary;
  }
  if (Array.isArray(lite.hourly_sends_24h)) {
    next.hourly_sends_24h = lite.hourly_sends_24h;
  }
  return next;
}

/** Dashboard `workspace` state from GET /runs/:id/workspace-lite — avoids heavy GET /workspace (full Run row + same metrics). */
function workspaceFromLiteApi(lite, runId) {
  const rid = Number(runId);
  const merged = mergeWorkspaceLiteInto(null, lite);
  if (!merged || typeof merged !== "object") {
    return {
      id: rid,
      display_phase: "Preparing",
      setup_steps: [],
      setup_summary: {},
      setup_state_message: "",
      performance: {},
      conversations: {},
      hourly_sends_24h: [],
    };
  }
  return { ...merged, id: rid };
}

/** Job title for header + edit form: column `role`, else common keys in source_json (LLM / legacy). */
function contactRoleFromPayload(contact) {
  if (!contact) return "";
  const col = String(contact.role ?? "").trim();
  if (col) return col;
  const sj = contact.source_json && typeof contact.source_json === "object" ? contact.source_json : {};
  return String(sj.role ?? sj.title ?? sj.job_title ?? sj.position ?? "").trim();
}

/** Expand panel-lite snapshot row to a full contact-shaped object for display (GET /contacts/run not applied yet). */
function contactRowFromPanelLitePreview(p, runId) {
  if (!p || typeof p !== "object") return null;
  return {
    id: p.id,
    run_id: runId ?? null,
    company: p.company ?? null,
    website: p.website ?? null,
    name: p.name ?? null,
    role: p.role ?? null,
    email: p.email ?? null,
    linkedin: p.linkedin ?? null,
    status: p.status ?? "valid",
    confidence: p.confidence ?? null,
    source_json: p.source_json && typeof p.source_json === "object" ? p.source_json : {},
    personalization_json:
      p.personalization_json && typeof p.personalization_json === "object" ? p.personalization_json : {},
    review_status: p.review_status ?? "pending",
    review_notes: p.review_notes ?? null,
    reviewed_at: p.reviewed_at ?? null,
    email_health: p.email_health ?? "unknown",
    last_contact_event_at: p.last_contact_event_at ?? null,
    gmail_history_status: p.gmail_history_status ?? null,
    gmail_history_checked_at: p.gmail_history_checked_at ?? null,
    gmail_inbox_imported_at: p.gmail_inbox_imported_at ?? null,
    created_at: p.created_at ?? new Date(0).toISOString(),
  };
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

/** True when Gmail refresh failed (expired/revoked token) — UI should offer Connect Gmail even if setup still showed «ready». */
function isGmailAuthReconnectErrorMessage(raw) {
  const m = String(detailFromApiErrorMessage(raw) || raw || "").toLowerCase();
  return (
    m.includes("gmail authorization failed") ||
    m.includes("invalid_grant") ||
    m.includes("token has been expired") ||
    m.includes("token has been revoked")
  );
}

function formatApiError(e) {
  if (e?.name === "AbortError") {
    return "Timed out or cancelled";
  }
  const msg = e?.message || String(e);
  if (msg === "Failed to fetch" || msg.includes("NetworkError") || msg.includes("Load failed")) {
    return "Failed to fetch";
  }
  return msg;
}

/** Transient / bursty request failures — log only; no full-page error informer. */
function isConsoleOnlyApiFailure(message) {
  const m = String(message || "");
  const lower = m.toLowerCase();
  return (
    m.includes("Failed to fetch") ||
    m.includes("NetworkError") ||
    m.includes("Load failed") ||
    m.includes("Timed out or cancelled") ||
    lower.includes("aborted") ||
    (lower.includes("abort") && lower.includes("cancel"))
  );
}

const DEBUG_LOG_MAX_JSON = 12000;

/** Second line for activity log — JSON or string (truncated). */
function formatDebugDetail(d) {
  if (d == null) return "";
  if (typeof d === "string") {
    return d.length > DEBUG_LOG_MAX_JSON ? `${d.slice(0, DEBUG_LOG_MAX_JSON)}\n…` : d;
  }
  try {
    const s = JSON.stringify(d, null, 0);
    return s.length > DEBUG_LOG_MAX_JSON ? `${s.slice(0, DEBUG_LOG_MAX_JSON)}\n… [truncated]` : s;
  } catch {
    return String(d);
  }
}

/** Set from AiBizOsHumanUI via useLayoutEffect — setUiError writes silent failures here. */
let activityLogAppendRef = null;
/** Throttle duplicate [ui] lines for the same transient message (parallel requests → log spam). */
let uiSilentErrorLastLogAt = 0;
let uiSilentErrorLastKey = "";

function setUiError(setError, err) {
  if (err?.name === "AbortError") return;
  const raw = String(err?.message ?? err ?? "");
  if (!raw) return;
  const msg = detailFromApiErrorMessage(raw);
  if (!msg) return;
  if (isConsoleOnlyApiFailure(msg)) {
    const now = Date.now();
    const key = msg.trim().slice(0, 120);
    if (
      key === uiSilentErrorLastKey &&
      now - uiSilentErrorLastLogAt < METRICS_SILENT_FAILURE_LOG_INTERVAL_MS
    ) {
      return;
    }
    uiSilentErrorLastLogAt = now;
    uiSilentErrorLastKey = key;
    activityLogAppendRef?.(`[ui] ${msg}`, {
      name: err?.name,
      message: raw.slice(0, 2000),
    });
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

/** Stored as runs.email_style_mode slug; Auto uses contact-role heuristics (backend email_style_service). */
const PROFESSIONAL_PROFILE_OPTIONS = [
  { value: "any_top_management", label: "Any Top Management" },
  { value: "hr_director_or_management", label: "HR Director or HR Management" },
  { value: "head_of_training_center", label: "Head of Training Center / L&D" },
  { value: "founder_or_ceo", label: "Founder or CEO" },  { value: "cto_or_developer", label: "CTO or Developer" },
  { value: "cmo_or_marketing", label: "CMO or Marketing Management" },
  { value: "head_of_licensing", label: "Head of Licensing or Licensing Management" },
  { value: "cfo_or_accountants", label: "CFO or Accountants" },
  { value: "vp_or_other_dm", label: "VP or other DM" },
  { value: "any_c_level", label: "Any C-level Management" },
  { value: "any_mid_management", label: "Any Mid-management" },
  { value: "auto", label: "Auto" },
];

const LEGACY_EMAIL_VOICE_MODES = new Set(["direct", "warm", "sharp", "executive"]);

function normalizeProfessionalProfileFromApi(raw) {
  const s = String(raw ?? "").trim().toLowerCase();
  if (!s) return "auto";
  if (LEGACY_EMAIL_VOICE_MODES.has(s)) return "auto";
  return s;
}

/** @param {unknown} score */
function validationScoreToneClass(score) {
  const n = Number(score);
  if (!Number.isFinite(n)) return "bg-muted text-muted-foreground border-border";
  if (n >= 80) return "bg-emerald-600/15 text-emerald-900 border-emerald-500/40 dark:bg-emerald-500/20 dark:text-emerald-100";
  if (n >= 50) return "bg-amber-500/15 text-amber-950 border-amber-500/45 dark:bg-amber-500/20 dark:text-amber-100";
  return "bg-red-600/15 text-red-900 border-red-500/40 dark:bg-red-500/20 dark:text-red-100";
}

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

/** Nav values that show TrackingView — load minimal strip (signature + event_chain) only here. */
const TRACKING_STRIP_NAV = new Set([
  "events",
  "threads",
  "reply-drafts",
  "reminders",
  "assets",
  "packets",
  "dead",
  "queue",
]);

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

/**
 * Human UI only uses parent `assetsLibrary` / `runAssetPackets` for Drafts (attachment chips) and
 * Assets / Packets nav. Fetching them on every run switch competes with GET /runs, /workspace-lite,
 * /contacts/run (browser HTTP/1.1 connection limits — see TrackingView «load assets first» comment).
 */
function mainNavNeedsParentAssetsFetch(nav) {
  return nav === "drafts" || nav === "assets" || nav === "packets";
}

/**
 * Section lists (contacts / drafts) are not part of the run «card» bundle — each section loads its own
 * GET when you open that tab (`refreshRunContactsOnly` / `refreshRunDraftsOnly`). Keeps workspace-lite fast.
 */
function listInclusionsForMainNav(_nav) {
  return {
    includeContacts: false,
    includeDrafts: false,
  };
}

export default function AiBizOsHumanUI() {
  const [projects, setProjects] = useState([]);
  const [selectedProject, setSelectedProject] = useState(null);
  const [selectedRun, setSelectedRun] = useState(null);
  const [contacts, setContacts] = useState([]);
  const [drafts, setDrafts] = useState([]);
  const [loading, setLoading] = useState(false);
  /** True while loadRunDetails bundle is in flight (parallel GETs for run). */
  const [runDetailsLoading, setRunDetailsLoading] = useState(false);
  /** Drafts/Contacts tab: separate GET lists (not part of workspace-only loadRunDetails). */
  const [draftsSectionFetchBusy, setDraftsSectionFetchBusy] = useState(false);
  const [contactsSectionFetchBusy, setContactsSectionFetchBusy] = useState(false);
  /** Right-top activity log: { id, t, text }[] */
  const [activityLogLines, setActivityLogLines] = useState([]);
  /** Activity panel: only visible when user opens it via the notebook button (never auto). */
  const [activityLogPinnedOpen, setActivityLogPinnedOpen] = useState(false);
  const runDetailsLoadGenRef = useRef(0);
  const activityLogEndRef = useRef(null);
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
  /** GET /runs/:id/tracking-strip while on Tracking nav — never full Run row. */
  const [trackingStrip, setTrackingStrip] = useState(null);
  const [workspace, setWorkspace] = useState(null);
  /** When === selectedRun.id, Review contacts / Drafts sub-tab counts use live data; else localStorage snapshot. */
  const [runDetailsHydratedId, setRunDetailsHydratedId] = useState(null);
  /** GET /contacts/run/:id applied for this run (Review + contact-analyzer). */
  const [contactsListReadyRunId, setContactsListReadyRunId] = useState(null);
  /** Last run where GET /contacts/run failed — stops infinite "Loading…" without marking list hydrated. */
  const [contactsListFailedRunId, setContactsListFailedRunId] = useState(null);
  /** Last run where GET /runs/:id/companies failed (incl. network) — avoids empty copy when load never applied. */
  const [companiesListFailedRunId, setCompaniesListFailedRunId] = useState(null);
  /** GET /email-drafts/run/:id applied for this run (Review Drafts). */
  const [draftsListReadyRunId, setDraftsListReadyRunId] = useState(null);
  /** Last run where GET /email-drafts/run failed — avoids infinite “cached drafts — refreshing…”. */
  const [draftsListFailedRunId, setDraftsListFailedRunId] = useState(null);
  /** Bumps when Prompt/Signature setup localStorage prefs change so icons re-read snapshots without waiting on run object. */
  const [runSetupPrefsRev, setRunSetupPrefsRev] = useState(0);
  /** All runs / all projects — from GET /sending/global-performance. */
  const [totalPerformance, setTotalPerformance] = useState(() => snapshotReadTotalPerformance());
  const [newRunOpen, setNewRunOpen] = useState(false);
  /** Snapshot when the dialog opened from an existing run: trimmed fields + optional runId for Update vs Create. */
  const [newRunBaseline, setNewRunBaseline] = useState(null);
  const [newRunCreateInFlight, setNewRunCreateInFlight] = useState(false);
  const [newRunUpdateInFlight, setNewRunUpdateInFlight] = useState(false);
  /** Invalidates in-flight GET /edit-form when dialog closes or mode switches — never blocks UI. */
  const editFormFetchSeqRef = useRef(0);
  const newRunDialogBusy = newRunCreateInFlight || newRunUpdateInFlight;
  const [switchRunOpen, setSwitchRunOpen] = useState(false);
  /** PATCH /runs/:id/project — attach run to current project when project_id drifted. */
  const [runProjectMoveInFlight, setRunProjectMoveInFlight] = useState(false);
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
    email_style_mode: "auto",
  });

  /** Inline edit: { id, email } */
  const [editingContact, setEditingContact] = useState(null);
  /** POST PATCH /contacts/:id/edit in flight (Review contacts Save). */
  const [contactEditSavingId, setContactEditSavingId] = useState(null);
  /** PATCH /contacts/:id/review (approve) in flight. */
  const [contactApproveBusyId, setContactApproveBusyId] = useState(null);
  /** Outbound draft is being generated in background after Approve — Drafts tab shows placeholder. */
  const [pendingOutboundDraftByContactId, setPendingOutboundDraftByContactId] = useState(() => ({}));
  const outboundDraftGenTimeoutRef = useRef({});
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
  /** True while GET /email-drafts/:id for the editor is in flight — modal still opens (was null until fetch, so Edit looked broken). */
  const [editDraftLoading, setEditDraftLoading] = useState(false);
  const [editDraftSaving, setEditDraftSaving] = useState(false);
  /** Edit draft dialog: apply chosen attachments to all drafts in Pending or Approved (matches active sub-tab). */
  const [applyAssetsEditScope, setApplyAssetsEditScope] = useState("none");
  const [assetsLibrary, setAssetsLibrary] = useState([]);
  const [runAssetPackets, setRunAssetPackets] = useState([]);
  /** Set after a successful assets GET (Tracking can also push via onStaticAssetsSynced). */
  const assetsLibraryFetchedRef = useRef(false);
  /** Last run id we stored packets for (kept in sync with onStaticAssetsSynced). */
  const assetPacketsLoadedForRunIdRef = useRef(null);
  /** Bumped on each assets/packets fetch start so stale async completions never wipe state. */
  const assetsFetchGenerationRef = useRef(0);
  /** Latest in-flight `loadRunDetails` run id — stale responses must not apply state. */
  const runLoadTargetRef = useRef(null);
  /** Invalidate in-flight GET /email-drafts/:id when the edit modal is closed or a new edit starts. */
  const editDraftFetchSeqRef = useRef(0);
  /** Draft id being opened in the editor (set before GET returns — for delete-while-loading). */
  const editDraftOpenTargetIdRef = useRef(null);
  /** Abort in-flight GET /email-drafts/:id when closing the edit modal or opening another draft. */
  const editDraftGetAbortRef = useRef(null);
  /** Stale-response guards for list GETs (independent so Contacts-only fetch cannot overwrite Drafts from a bundled poll). */
  const contactsListFetchSeqRef = useRef(0);
  const draftsListFetchSeqRef = useRef(0);
  /** Mirrors list-ready state for deferred checks after loadRunDetails catch (avoids stale closure vs refreshRun*Only). */
  const contactsListReadyRunIdRef = useRef(null);
  const draftsListReadyRunIdRef = useRef(null);
  /** Stale-response guard for GET /runs/:id/companies (Companies tab). */
  const companiesListFetchSeqRef = useRef(0);
  /** Abort in-flight Companies GET when switching run or section (stream A); refresh stream calls `abort` at start of a new fetch. */
  const companiesListAbortRef = useRef(null);
  /** Last run id we applied Companies pagination for — detects run switch before `companiesPage` state updates. */
  const companiesFetchRunIdRef = useRef(null);
  /** Clears companies panel only when selected run id changes — not when switching Contacts ↔ Companies (keeps instant return). */
  const prevSelectedRunIdForCompaniesCacheRef = useRef(null);
  /** Last workspace.setup_summary.companies_collected seen for selected run — refresh list on real count change without re-fetching on every metrics poll tick. */
  const prevCompaniesCollectedRef = useRef(null);
  /** Aligns with `companiesRefreshNonce` so the refresh-only effect skips the first tick (primary [run,nav] already fetches). */
  const lastCompaniesRefreshNonceAppliedRef = useRef(null);
  /** One metrics poll at a time — avoids overlapping GETs when interval (e.g. 8s) < request duration. */
  const metricsPollInFlightRef = useRef(false);
  /** Abort in-flight workspace-tick/global-performance when switching to Companies tab (same-origin fetch queue). */
  const metricsPollAbortRef = useRef(null);
  /** Mirrors `restartsInFlight` for sync handlers (metrics poll skips only runs with background restart). */
  const restartsInFlightRef = useRef({});
  /** One interval per run_id polling GET /runs/:id until needs_review/failed after 202 restart. */
  const restartPollIntervalsRef = useRef({});
  /** Throttle silent metrics errors in the activity log. */
  const metricsSilentFailureLastLogAtRef = useRef(0);
  /** Concurrent section fetches share one "busy" flag — use depth so one finally() cannot clear spinner while another is still in flight. */
  const contactsSectionFetchDepthRef = useRef(0);
  const draftsSectionFetchDepthRef = useRef(0);
  /** Paged GET /contacts/run and /email-drafts/run — abort when leaving that tab so other sections (e.g. Companies) are not queued behind them. */
  const contactsRunListAbortRef = useRef(null);
  const draftsRunListAbortRef = useRef(null);
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
  /** run_id → { name } while POST /restart accepted and background workflow not finished. */
  const [restartsInFlight, setRestartsInFlight] = useState(() => ({}));
  const [companiesPanel, setCompaniesPanel] = useState(null);
  const [companiesLoading, setCompaniesLoading] = useState(false);
  /** Per-row: POST /companies/retry-find in flight (several retries can run in parallel). */
  const [companyRetryLoading, setCompanyRetryLoading] = useState(() => ({}));
  const [companyRetryAllLoading, setCompanyRetryAllLoading] = useState(false);
  const [companiesPage, setCompaniesPage] = useState(1);
  /** Increment to re-run Companies tab GET after a failed load (Retry). */
  const [companiesRefreshNonce, setCompaniesRefreshNonce] = useState(0);
  const [contactReviewTab, setContactReviewTab] = useState("pending");
  const [contactsReviewPage, setContactsReviewPage] = useState(1);
  const [continueCompanyFindLoading, setContinueCompanyFindLoading] = useState(false);
  /**
   * After retry: still no matching contact and LLM added no new rows → red "Not available", no Retry.
   * Keyed by collect_index; reset when switching runs.
   */
  const [companyFindUnavailable, setCompanyFindUnavailable] = useState(() => ({}));
  /** { name, engine: "apollo" | "llm" } while Continue searching / Retry all / per-row Retry runs find. */
  const [companyBulkFindProgress, setCompanyBulkFindProgress] = useState(null);
  const [removeCompanyDialog, setRemoveCompanyDialog] = useState(null);
  const [removeCompanyInFlight, setRemoveCompanyInFlight] = useState(false);
  const [companyAiFitBatchLoading, setCompanyAiFitBatchLoading] = useState(false);
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

  useEffect(() => {
    contactsListReadyRunIdRef.current = contactsListReadyRunId;
    draftsListReadyRunIdRef.current = draftsListReadyRunId;
  }, [contactsListReadyRunId, draftsListReadyRunId]);

  const contactsVisible = useMemo(() => {
    const rid = Number(selectedRun?.id);
    let base = contacts;
    if (
      Number.isFinite(rid) &&
      rid > 0 &&
      contactsListReadyRunId !== rid &&
      (!Array.isArray(contacts) || contacts.length === 0)
    ) {
      const snap = snapshotReadRunPanelLite(rid)?.contactsPreview;
      if (Array.isArray(snap) && snap.length > 0) {
        base = snap.map((p) => contactRowFromPanelLitePreview(p, rid)).filter(Boolean);
      }
    }
    return filterShadowNoEmailContacts(base);
  }, [contacts, contactsListReadyRunId, selectedRun?.id]);

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

  const switchRunOpenList = useMemo(
    () => (Array.isArray(runsList) ? runsList.filter((r) => !r.closed_at) : []),
    [runsList],
  );
  const switchRunClosedList = useMemo(
    () => (Array.isArray(runsList) ? runsList.filter((r) => r.closed_at) : []),
    [runsList],
  );

  const runProjectMismatch = useMemo(() => {
    if (!selectedRun?.id || !selectedProject) return false;
    const pid = projectPk(selectedProject);
    if (pid == null || pid === "") return false;
    return Number(selectedRun.project_id) !== Number(pid);
  }, [selectedRun, selectedProject]);

  const runOtherProjectLabel = useMemo(() => {
    if (!runProjectMismatch || selectedRun?.project_id == null) return null;
    const rid = Number(selectedRun.project_id);
    const row = projects.find((p) => Number(p.id) === rid || Number(p.project_id) === rid);
    return row?.name?.trim() || `Project #${selectedRun.project_id}`;
  }, [runProjectMismatch, selectedRun?.project_id, projects]);

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

  const appendActivityLog = useCallback((text, detail) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
    let full = String(text);
    if (detail !== undefined && detail !== null) {
      full += `\n${formatDebugDetail(detail)}`;
    }
    setActivityLogLines((prev) => [...prev.slice(-400), { id, t: Date.now(), text: full }]);
  }, []);

  useLayoutEffect(() => {
    activityLogAppendRef = appendActivityLog;
    return () => {
      activityLogAppendRef = null;
    };
  }, [appendActivityLog]);

  /** Run switch + assets/packets pipeline — same channel as the rest of the UI (Activity panel). */
  const appendRunTraceLog = useCallback((message, detail) => {
    appendActivityLog(`Run trace: ${message}`, detail);
  }, [appendActivityLog]);

  const appendTrackingRunTraceLog = useCallback(
    (message, detail) => {
      appendActivityLog(`Run trace: [Tracking] ${message}`, detail);
    },
    [appendActivityLog],
  );

  /**
   * Activity log: every HTTP GET/POST with duration so heavy work (workspace-lite, contacts, etc.) is visible.
   */
  const logTimedApi = useCallback(
    async (phaseLabel, path, apiOptions = {}) => {
      const t0 = typeof performance !== "undefined" ? performance.now() : Date.now();
      appendActivityLog(`[net START] ${phaseLabel} → ${path}`);
      try {
        const data = await api(path, apiOptions);
        const ms = Math.round(
          (typeof performance !== "undefined" ? performance.now() : Date.now()) - t0,
        );
        appendActivityLog(`[net OK] ${phaseLabel} ${ms}ms ← ${path}`);
        return data;
      } catch (e) {
        const ms = Math.round(
          (typeof performance !== "undefined" ? performance.now() : Date.now()) - t0,
        );
        appendActivityLog(
          `[net FAIL] ${phaseLabel} ${ms}ms ← ${path} — ${String(e?.message || e).slice(0, 500)}`,
        );
        throw e;
      }
    },
    [appendActivityLog],
  );

  /** Stable handles for Companies-tab fetch so the effect deps stay [run, nav, refreshNonce] only. */
  const appendActivityLogRef = useRef(appendActivityLog);
  appendActivityLogRef.current = appendActivityLog;

  useEffect(() => {
    if (activityLogLines.length === 0) return;
    queueMicrotask(() => {
      activityLogEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    });
  }, [activityLogLines]);

  useEffect(() => {
    restartsInFlightRef.current = restartsInFlight;
  }, [restartsInFlight]);

  const selectedRunIdRef = useRef(null);
  /** Keep in sync during render so async callbacks (e.g. Tracking onStaticAssetsSynced) see the current run before child useEffects run. */
  selectedRunIdRef.current = selectedRun?.id ?? null;
  const mainNavRef = useRef(mainNav);
  mainNavRef.current = mainNav;
  const selectedProjectRef = useRef(null);
  useEffect(() => {
    selectedProjectRef.current = selectedProject;
  }, [selectedProject]);

  const selectedRunRef = useRef(null);
  useEffect(() => {
    selectedRunRef.current = selectedRun;
  }, [selectedRun]);

  useEffect(() => {
    return () => {
      Object.keys(restartPollIntervalsRef.current).forEach((k) => {
        clearInterval(restartPollIntervalsRef.current[k]);
      });
      restartPollIntervalsRef.current = {};
    };
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
    setActivityLogLines([]);
    appendActivityLog(
      v === "archived"
        ? "Projects: GET /projects?archived=true"
        : "Projects: GET /projects?archived=false",
    );
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
      appendActivityLog(`Projects loaded (${Array.isArray(data) ? data.length : 0}).`);
    } catch (e) {
      if (signal?.aborted) return;
      appendActivityLog(`Projects error: ${detailFromApiErrorMessage(e?.message || e) || String(e)}`);
      setUiError(setError, e);
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [projectView, appendActivityLog]);

  const continueCompanyFindAllPending = async (runId) => {
    if (!runId) return;
    setError("");
    setContinueCompanyFindLoading(true);
    const engine = setupIntegration?.apollo_outreach_ready === true ? "apollo" : "llm";
    const engineLabel = engine === "apollo" ? "Apollo" : "LLM";
    appendActivityLog(`Companies: Continue searching — start (run_id=${runId}, ${engineLabel})`);
    const companiesSnapshotUrl = () => {
      const ps = new URLSearchParams();
      ps.set("limit", String(COMPANIES_FETCH_MAX));
      ps.set("offset", "0");
      return `/runs/${runId}/companies?${ps}`;
    };
    const retryQueueScanUrl = () => {
      const ps = new URLSearchParams();
      ps.set("limit", String(COMPANIES_RETRY_QUEUE_SCAN_MAX));
      ps.set("offset", "0");
      return `/runs/${runId}/companies?${ps}`;
    };
    const finalizeContinueFind = async () => {
      try {
        appendActivityLog(`Companies: POST /runs/${runId}/companies/continue-find (finalize)`);
        await api(`/runs/${runId}/companies/continue-find`, {
          method: "POST",
          timeoutMs: COMPANY_RETRY_FIND_TIMEOUT_MS,
        });
      } catch (e) {
        const msg = detailFromApiErrorMessage(e?.message || e) || String(e);
        if (!/already completed/i.test(msg)) {
          throw e;
        }
        appendActivityLog(`Continue searching finalize skipped: ${msg}`);
      }
    };
    try {
      const scan = await api(retryQueueScanUrl(), { timeoutMs: COMPANIES_HTTP_TIMEOUT_MS });
      const hasPending = (list) =>
        Array.isArray(list) && list.some((c) => c.contact_status === "pending");
      if (!hasPending(scan.companies)) {
        await finalizeContinueFind();
        const data = await api(companiesSnapshotUrl(), { timeoutMs: COMPANIES_HTTP_TIMEOUT_MS });
        setCompaniesPanel(normalizeCompaniesPanelResponse(data, 0));
        setCompanyFindUnavailable({});
        refreshRunMetricsOnly(runId);
        appendActivityLog("Continue searching finished; table refreshed.");
        return;
      }
      for (let safety = 0; safety < 500; safety++) {
        const fullScan = await api(retryQueueScanUrl(), { timeoutMs: COMPANIES_HTTP_TIMEOUT_MS });
        const row = fullScan.companies?.find((c) => {
          const idx = normalizeCompanyCollectIndex(c);
          if (idx == null) return false;
          return c.contact_status === "pending";
        });
        if (!row) {
          break;
        }
        const k = normalizeCompanyCollectIndex(row);
        if (k == null) continue;
        const rowLabel = String(row?.name ?? row?.company ?? "—").trim() || "—";
        setCompanyBulkFindProgress({ name: rowLabel, engine });
        setCompanyRetryLoading((prev) => ({ ...prev, [k]: true }));
        appendActivityLog(`Companies: Continue searching — ${engineLabel} «${rowLabel}» (collect_index=${k})`);
        try {
          await api(`/runs/${runId}/companies/retry-find`, {
            method: "POST",
            body: { collect_index: k },
            timeoutMs: COMPANY_RETRY_FIND_TIMEOUT_MS,
          });
        } finally {
          setCompanyRetryLoading((prev) => {
            const next = { ...prev };
            delete next[k];
            return next;
          });
        }
        const snap = await api(companiesSnapshotUrl(), { timeoutMs: COMPANIES_HTTP_TIMEOUT_MS });
        setCompaniesPanel(normalizeCompaniesPanelResponse(snap, 0));
      }
      await finalizeContinueFind();
      const data = await api(companiesSnapshotUrl(), { timeoutMs: COMPANIES_HTTP_TIMEOUT_MS });
      setCompaniesPanel(normalizeCompaniesPanelResponse(data, 0));
      setCompanyFindUnavailable({});
      refreshRunMetricsOnly(runId);
      appendActivityLog("Continue searching finished; table refreshed.");
    } catch (e) {
      appendActivityLog(`Continue searching: ${detailFromApiErrorMessage(e?.message || e) || String(e)}`);
      setUiError(setError, e);
    } finally {
      setCompanyBulkFindProgress(null);
      setContinueCompanyFindLoading(false);
    }
  };

  const retryCompanyFind = async (runId, collectIndex) => {
    if (!runId || collectIndex == null) return;
    const k = Number(collectIndex);
    if (!Number.isFinite(k) || k < 0) return;
    setError("");
    const engine = setupIntegration?.apollo_outreach_ready === true ? "apollo" : "llm";
    const rowHint = companiesPanel?.companies?.find((c) => normalizeCompanyCollectIndex(c) === k);
    const progressName = String(rowHint?.name ?? rowHint?.company ?? "—").trim() || "—";
    setCompanyBulkFindProgress({ name: progressName, engine });
    setCompanyRetryLoading((prev) => ({ ...prev, [k]: true }));
    appendActivityLog(`Companies: POST /runs/${runId}/companies/retry-find { collect_index: ${k} }`);
    try {
      const result = await api(`/runs/${runId}/companies/retry-find`, {
        method: "POST",
        body: { collect_index: k },
        timeoutMs: COMPANY_RETRY_FIND_TIMEOUT_MS,
      });
      const merged =
        typeof result?.new_contacts_merged === "number"
          ? result.new_contacts_merged
          : typeof result?.newContactsMerged === "number"
            ? result.newContactsMerged
            : 0;
      const ps = new URLSearchParams();
      ps.set("limit", String(COMPANIES_FETCH_MAX));
      ps.set("offset", "0");
      const data = await api(`/runs/${runId}/companies?${ps}`, {
        timeoutMs: COMPANIES_HTTP_TIMEOUT_MS,
      });
      const normalized = normalizeCompaniesPanelResponse(data, 0);
      setCompaniesPanel(normalized);
      const rowAfter = normalized.companies?.find((c) => normalizeCompanyCollectIndex(c) === k);
      if (
        (rowAfter?.contact_status === "none" || rowAfter?.contact_status === "no_email") &&
        merged === 0
      ) {
        setCompanyFindUnavailable((prev) => ({ ...prev, [k]: true }));
      }
      if (rowAfter?.contact_status === "found") {
        setCompanyFindUnavailable((prev) => {
          if (!prev[k]) return prev;
          const next = { ...prev };
          delete next[k];
          return next;
        });
      }
      refreshRunMetricsOnly(runId);
      const label = String(rowAfter?.name ?? rowAfter?.company ?? "—").trim() || "—";
      appendActivityLog(
        `Companies: retry-find done — collect_index=${k} "${label}" → contact_status=${rowAfter?.contact_status ?? "—"}, new_contacts_merged=${merged}`,
        { runId, collectIndex: k },
      );
    } catch (e) {
      const msg = detailFromApiErrorMessage(e?.message || e) || String(e);
      appendActivityLog(`Companies: retry-find error (collect_index=${k}) — ${msg}`, {
        runId,
        collectIndex: k,
      });
      setUiError(setError, e);
    } finally {
      setCompanyBulkFindProgress(null);
      setCompanyRetryLoading((prev) => {
        const next = { ...prev };
        delete next[k];
        return next;
      });
    }
  };

  /** Sequential POST /companies/retry-find for «Not found» or «no email» rows (excludes Not available). */
  const retryAllCompanyFindNotFound = async (runId) => {
    if (!runId) return;
    setError("");
    const engine = setupIntegration?.apollo_outreach_ready === true ? "apollo" : "llm";
    setCompanyRetryAllLoading(true);
    appendActivityLog(`Companies: Retry all — start (run_id=${runId})`);
    let retryAllAbortedByError = false;
    let unavailableAcc = { ...companyFindUnavailable };
    const companiesSnapshotUrl = () => {
      const ps = new URLSearchParams();
      ps.set("limit", String(COMPANIES_FETCH_MAX));
      ps.set("offset", "0");
      return `/runs/${runId}/companies?${ps}`;
    };
    const retryQueueScanUrl = () => {
      const ps = new URLSearchParams();
      ps.set("limit", String(COMPANIES_RETRY_QUEUE_SCAN_MAX));
      ps.set("offset", "0");
      return `/runs/${runId}/companies?${ps}`;
    };
    try {
      for (let safety = 0; safety < 500; safety++) {
        const fullScan = await api(retryQueueScanUrl(), {
          timeoutMs: COMPANIES_HTTP_TIMEOUT_MS,
        });
        const row = fullScan.companies?.find((c) => {
          const idx = normalizeCompanyCollectIndex(c);
          if (idx == null) return false;
          if (c.ai_fit_status === "incorrect") return false;
          return (
            (c.contact_status === "none" ||
              c.contact_status === "no_email" ||
              c.contact_status === "unknown") &&
            !unavailableAcc[idx]
          );
        });
        if (!row) {
          const snap = await api(companiesSnapshotUrl(), { timeoutMs: COMPANIES_HTTP_TIMEOUT_MS });
          setCompaniesPanel(normalizeCompaniesPanelResponse(snap, 0));
          const findSt = snap?.find_step_status;
          appendActivityLog(
            findSt && findSt !== "completed"
              ? `Companies: Retry all — no rows with Not found / no email / unknown (or all skipped as unavailable); find step=${findSt}. For «Not searched yet» use Continue searching. Table refreshed (run_id=${runId}).`
              : `Companies: Retry all — queue empty, table refreshed (run_id=${runId}).`,
          );
          break;
        }

        const collectIndex = normalizeCompanyCollectIndex(row);
        if (collectIndex == null) continue;
        const rowLabel = String(row?.name ?? row?.company ?? "—").trim() || "—";
        setCompanyBulkFindProgress({ name: rowLabel, engine });
        appendActivityLog(
          `Companies: Retry all — POST retry-find collect_index=${collectIndex} "${rowLabel}" (was: contact_status=${row?.contact_status ?? "—"})`,
          { runId, collectIndex },
        );
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
          const dataAfter = await api(retryQueueScanUrl(), {
            timeoutMs: COMPANIES_HTTP_TIMEOUT_MS,
          });
          const rowAfter = dataAfter.companies?.find((c) => normalizeCompanyCollectIndex(c) === collectIndex);
          const snap = await api(companiesSnapshotUrl(), { timeoutMs: COMPANIES_HTTP_TIMEOUT_MS });
          setCompaniesPanel(normalizeCompaniesPanelResponse(snap, 0));
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
          const afterLabel = String(rowAfter?.name ?? rowAfter?.company ?? "—").trim() || "—";
          appendActivityLog(
            `Companies: Retry all — row done collect_index=${collectIndex} "${afterLabel}" → contact_status=${rowAfter?.contact_status ?? "—"}, new_contacts_merged=${merged}`,
            { runId, collectIndex },
          );
        } catch (e) {
          const msg = detailFromApiErrorMessage(e?.message || e) || String(e);
          appendActivityLog(`Companies: Retry all — error (collect_index=${collectIndex}) — ${msg}`, {
            runId,
            collectIndex,
          });
          setUiError(setError, e);
          retryAllAbortedByError = true;
          break;
        } finally {
          setCompanyRetryLoading((prev) => {
            const next = { ...prev };
            delete next[collectIndex];
            return next;
          });
        }
      }
      refreshRunMetricsOnly(runId);
      if (retryAllAbortedByError) {
        appendActivityLog(`Companies: Retry all — stopped on error (run_id=${runId}).`);
      } else {
        appendActivityLog(`Companies: Retry all — finished (run_id=${runId}).`);
      }
    } finally {
      setCompanyBulkFindProgress(null);
      setCompanyRetryAllLoading(false);
    }
  };

  const confirmRemoveCompanyFromRun = async () => {
    if (!removeCompanyDialog || !selectedRun?.id) return;
    const { collectIndex, name } = removeCompanyDialog;
    setRemoveCompanyInFlight(true);
    setError("");
    appendActivityLog(`Companies: DELETE /runs/${selectedRun.id}/companies/${collectIndex} (${name})`);
    try {
      await api(`/runs/${selectedRun.id}/companies/${collectIndex}`, { method: "DELETE" });
      const ps = new URLSearchParams();
      ps.set("limit", String(COMPANIES_FETCH_MAX));
      ps.set("offset", "0");
      const data = await api(`/runs/${selectedRun.id}/companies?${ps}`, {
        timeoutMs: COMPANIES_HTTP_TIMEOUT_MS,
      });
      setCompaniesPanel(normalizeCompaniesPanelResponse(data, 0));
      setCompanyFindUnavailable((prev) => {
        if (!(collectIndex in prev)) return prev;
        const next = { ...prev };
        delete next[collectIndex];
        return next;
      });
      refreshRunMetricsOnly(selectedRun.id);
      appendActivityLog(`Companies: removed «${name}» (collect_index=${collectIndex}).`);
      setRemoveCompanyDialog(null);
    } catch (e) {
      appendActivityLog(`Companies: remove error — ${detailFromApiErrorMessage(e?.message || e) || String(e)}`);
      setUiError(setError, e);
    } finally {
      setRemoveCompanyInFlight(false);
    }
  };

  /** POST …/companies/analyze-fit-pending — LLM labels rows without ``ai_fit_checked_at`` (not repeated). */
  const runCompaniesAiFitPending = async (runId) => {
    if (!runId) return;
    setError("");
    setCompanyAiFitBatchLoading(true);
    appendActivityLog(`Companies: AI analysis — starting… (run_id=${runId})`);
    try {
      const ps0 = new URLSearchParams();
      ps0.set("limit", String(COMPANIES_FETCH_MAX));
      ps0.set("offset", "0");
      const companiesPath = `/runs/${runId}/companies?${ps0}`;
      const data = await logTimedApi(
        "Companies AI analysis",
        `/runs/${runId}/companies/analyze-fit-pending`,
        {
          method: "POST",
          body: { max_rows: 200, force: false },
          timeoutMs: COMPANY_AI_FIT_BATCH_TIMEOUT_MS,
        },
      );
      const n = typeof data?.analyzed === "number" ? data.analyzed : 0;
      const errN = Array.isArray(data?.errors) ? data.errors.length : 0;
      appendActivityLog(`Companies: AI analysis — done — analyzed=${n}, row_errors=${errN}`);
      const snap = await logTimedApi("Companies table (after AI analysis)", companiesPath, {
        timeoutMs: COMPANIES_HTTP_TIMEOUT_MS,
      });
      setCompaniesPanel(normalizeCompaniesPanelResponse(snap, 0));
      refreshRunMetricsOnly(runId);
    } catch (e) {
      setUiError(setError, e);
    } finally {
      setCompanyAiFitBatchLoading(false);
    }
  };

  /**
   * Workspace-lite + optional section lists + global performance. Never GET /runs/:id here — use
   * GET /runs/:id/edit-form or GET /runs/:id/tracking-strip when a dialog/tab needs more.
   * @param {object} [options]
   * @param {boolean} [options.includeLists] — legacy: both contacts + drafts lists.
   * @param {boolean} [options.includeContacts] — GET /contacts/run (Review contacts / analyzer).
   * @param {boolean} [options.includeDrafts] — GET /email-drafts/run (compact list, no full body).
   */
  const loadRunDetails = async (runId, runRowHint, options = {}) => {
    const rid = Number(runId);
    if (!Number.isFinite(rid) || rid <= 0) return null;
    /** Core-only and bundle both hit the same backend; 25s was too tight when POST /restart queues other GETs. */
    const requestTimeoutMs = options?.requestTimeoutMs ?? LOAD_RUN_DETAILS_BUNDLE_TIMEOUT_MS;
    /** `includeLists: true` = fetch both section lists (legacy). Otherwise use explicit flags only. */
    const bundleLists = options.includeLists === true;
    const includeContacts = bundleLists || options.includeContacts === true;
    const includeDrafts = bundleLists || options.includeDrafts === true;
    const myGen = ++runDetailsLoadGenRef.current;
    setRunDetailsLoading(true);
    const listParts = [];
    if (includeContacts) listParts.push(`/contacts/run/${rid}`);
    if (includeDrafts) listParts.push(`/email-drafts/run/${rid} (list, compact)`);
    appendActivityLog(
      listParts.length
        ? `Run run_id=${rid}: GET /runs/${rid}/workspace-lite, ${listParts.join(", ")}`
        : `Run run_id=${rid}: GET /runs/${rid}/workspace-lite (no section lists; no GET /runs/:id)`,
    );
    const prevTarget = runLoadTargetRef.current;
    runLoadTargetRef.current = rid;
    /**
     * Only clear list state when switching to a *different* run (prevTarget known and ≠ rid).
     * Do NOT clear when prevTarget is null (first loadRunDetails for this session): the Contacts/Drafts
     * section effect can finish GET /contacts/run before this async function runs (after await runs list).
     * Clearing here would wipe that data; deps [selectedRun.id, mainNav] would not re-run the effect,
     * so the UI stayed on cached panel until the user changed section and back.
     * Same-run core-only reload is still handled by switchingRun being false when prevTarget === rid.
     */
    const switchingRun = prevTarget != null && Number(prevTarget) !== rid;
    if (switchingRun) {
      contactsListReadyRunIdRef.current = null;
      draftsListReadyRunIdRef.current = null;
      setContactsListReadyRunId(null);
      setContactsListFailedRunId(null);
      setCompaniesListFailedRunId(null);
      setDraftsListReadyRunId(null);
      setDraftsListFailedRunId(null);
      setContacts([]);
      setDrafts([]);
    }
    setRunDetailsHydratedId((prev) => (Number(prev) === rid ? prev : null));
    const rowGuess = runRowHint ?? runsList.find((r) => Number(r.id) === rid);
    if (rowGuess) {
      setSelectedRun(rowGuess);
      setWorkspace(snapshotMergeWorkspaceFromRunCards(snapshotReadRunCards(rid), rowGuess));
    } else {
      const pj = selectedProjectRef.current;
      const pid = pj != null ? projectPk(pj) : null;
      const minimal = { id: rid, project_id: pid };
      setSelectedRun(minimal);
      setWorkspace(snapshotMergeWorkspaceFromRunCards(snapshotReadRunCards(rid), minimal));
    }
    try {
      const wsLitePath = `/runs/${rid}/workspace-lite`;
      const pWsLite = logTimedApi(
        `loadRunDetails workspace-lite`,
        wsLitePath,
        { timeoutMs: requestTimeoutMs },
      );
      const pContacts = includeContacts
        ? (async () => {
          appendActivityLog(`[net START] loadRunDetails contacts (bundled) → /contacts/run/${rid}`);
          const t0 = typeof performance !== "undefined" ? performance.now() : Date.now();
          try {
            const data = await fetchAllPagedItems(
              (u) => api(u, { timeoutMs: requestTimeoutMs }),
              `/contacts/run/${rid}`,
            );
            const ms = Math.round(
              (typeof performance !== "undefined" ? performance.now() : Date.now()) - t0,
            );
            const n = Array.isArray(data) ? data.length : 0;
            appendActivityLog(`[net OK] loadRunDetails contacts ${ms}ms — ${n} rows ← /contacts/run/${rid}`);
            return data;
          } catch (e) {
            const ms = Math.round(
              (typeof performance !== "undefined" ? performance.now() : Date.now()) - t0,
            );
            appendActivityLog(
              `[net FAIL] loadRunDetails contacts ${ms}ms ← /contacts/run/${rid} — ${String(e?.message || e).slice(0, 400)}`,
            );
            throw e;
          }
        })()
        : null;
      const pDrafts = includeDrafts
        ? (async () => {
          const base = emailDraftsRunListPath(rid);
          appendActivityLog(`[net START] loadRunDetails drafts (bundled) → ${base}`);
          const t0 = typeof performance !== "undefined" ? performance.now() : Date.now();
          try {
            const data = await fetchAllPagedItems(
              (u) => api(u, { timeoutMs: requestTimeoutMs }),
              base,
            );
            const ms = Math.round(
              (typeof performance !== "undefined" ? performance.now() : Date.now()) - t0,
            );
            const n = Array.isArray(data) ? data.length : 0;
            appendActivityLog(`[net OK] loadRunDetails drafts ${ms}ms — ${n} rows ← ${base}`);
            return data;
          } catch (e) {
            const ms = Math.round(
              (typeof performance !== "undefined" ? performance.now() : Date.now()) - t0,
            );
            appendActivityLog(
              `[net FAIL] loadRunDetails drafts ${ms}ms ← ${base} — ${String(e?.message || e).slice(0, 400)}`,
            );
            throw e;
          }
        })()
        : null;

      let wsLiteData;
      let contactsData = null;
      let draftsData = null;
      if (includeContacts && includeDrafts) {
        [wsLiteData, contactsData, draftsData] = await Promise.all([pWsLite, pContacts, pDrafts]);
      } else if (includeContacts) {
        [wsLiteData, contactsData] = await Promise.all([pWsLite, pContacts]);
      } else if (includeDrafts) {
        [wsLiteData, draftsData] = await Promise.all([pWsLite, pDrafts]);
      } else {
        [wsLiteData] = await Promise.all([pWsLite]);
      }
      if (runLoadTargetRef.current !== rid) return null;
      appendHumanUiActivityInformers(wsLiteData, appendActivityLog);
      appendActivityLog(
        "→ loadRunDetails: workspace-lite applied (sidebar + metrics bundle; no full GET /runs/:id).",
      );
      setSelectedRun((prev) => {
        const base = rowGuess || prev || { id: rid };
        return { ...base, display_phase: wsLiteData.display_phase ?? base.display_phase };
      });

      if (includeContacts) {
        const cArr = Array.isArray(contactsData) ? contactsData : normalizeContactsRunPayload(contactsData);
        appendActivityLog(`→ Contacts: ${cArr.length}`);
        setContacts(cArr);
        contactsListReadyRunIdRef.current = rid;
        setContactsListReadyRunId(rid);
        setContactsListFailedRunId(null);
      }
      if (includeDrafts) {
        const dArr = Array.isArray(draftsData) ? draftsData : [];
        appendActivityLog(`→ Drafts: ${dArr.length}`);
        setDrafts(dArr);
        draftsListReadyRunIdRef.current = rid;
        setDraftsListReadyRunId(rid);
        setDraftsListFailedRunId(null);
      }
      if (includeContacts || includeDrafts) {
        try {
          const partial = {};
          if (includeContacts) {
            const cArr = Array.isArray(contactsData) ? contactsData : normalizeContactsRunPayload(contactsData);
            partial.contactsPreview = cArr
              .slice(0, MAX_CONTACTS_PANEL_LITE)
              .map(stripContactForPanelLite)
              .filter(Boolean);
          }
          if (includeDrafts) {
            const dArr = Array.isArray(draftsData) ? draftsData : [];
            partial.draftsPreview = draftsForRunPanelLitePreview(dArr)
              .map(stripDraftForPanelLite)
              .filter(Boolean);
          }
          snapshotMergeWriteRunPanelLite(rid, partial);
        } catch {
          /* panel lite is best-effort */
        }
      }
      const ws = workspaceFromLiteApi(wsLiteData, rid);
      setWorkspace(ws);
      if (ws) snapshotWriteRunCards(rid, ws);
      setRunDetailsHydratedId(rid);
      return ws;
    } catch (e) {
      if (runDetailsLoadGenRef.current !== myGen) return null;
      if (runLoadTargetRef.current === rid) {
        setRunDetailsHydratedId(null);
        if (includeContacts || includeDrafts) {
          if (includeContacts) setContactsListFailedRunId(rid);
          if (includeDrafts) setDraftsListFailedRunId(rid);
        } else {
          /**
           * Core-only load does not fetch /email-drafts — if it fails while section GETs are still
           * unresolved, we would otherwise spin forever on SnapshotCardsPlaceholder ("Draft data is loading…").
           * Defer: if a parallel refreshRun*Only later applies the list, refs match and we skip marking failed.
           */
          setTimeout(() => {
            if (runLoadTargetRef.current !== rid) return;
            if (draftsListReadyRunIdRef.current !== rid) {
              setDraftsListFailedRunId(rid);
            }
            if (contactsListReadyRunIdRef.current !== rid) {
              setContactsListFailedRunId(rid);
            }
          }, 0);
        }
        setUiError(setError, e);
        appendActivityLog(`Error: ${detailFromApiErrorMessage(e?.message || e) || String(e)}`);
      }
      return null;
    } finally {
      if (runDetailsLoadGenRef.current === myGen) {
        setRunDetailsLoading(false);
        appendActivityLog("Run load done.");
      }
    }
  };

  useEffect(() => {
    const rid = Number(selectedRun?.id);
    if (!Number.isFinite(rid) || rid <= 0) {
      setTrackingStrip(null);
      return;
    }
    if (!TRACKING_STRIP_NAV.has(mainNav)) {
      setTrackingStrip(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const d = await api(`/runs/${rid}/tracking-strip`, { timeoutMs: POLL_METRICS_TIMEOUT_MS });
        if (!cancelled) setTrackingStrip(d);
      } catch {
        if (!cancelled) setTrackingStrip(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedRun?.id, mainNav]);

  const moveRunToCurrentProject = async () => {
    if (!selectedRun?.id || !selectedProject || runProjectMoveInFlight) return;
    const pid = projectPk(selectedProject);
    if (pid == null || pid === "") return;
    if (selectedProject.is_archived) return;
    const rid = selectedRun.id;
    try {
      setRunProjectMoveInFlight(true);
      setError("");
      appendActivityLog(
        `Run ${rid}: PATCH /runs/${rid}/project { project_id: ${Number(pid)} } (move to current project)`,
      );
      const updated = await api(`/runs/${rid}/project`, {
        method: "PATCH",
        body: { project_id: Number(pid) },
      });
      appendActivityLog(`Run ${rid}: PATCH OK — GET /runs/project/${pid} (refresh sidebar list)`);
      setSelectedRun(updated);
      const runs = await api(`/runs/project/${pid}`);
      const ordered = orderRunsOpenFirst(runs);
      setRunsList(ordered);
      snapshotWriteRuns(pid, ordered);
      appendActivityLog(`Run ${rid} attached to project ${pid} (${selectedProject.name ?? "—"}).`);
      const rowHint = ordered.find((r) => r.id === rid);
      /** Merge card row + PATCH body so loadRunDetails’ first paint keeps correct project_id (avoids stale mismatch banner). */
      const hintForLoad =
        rowHint && updated && typeof updated === "object"
          ? { ...rowHint, ...updated, project_id: Number(updated.project_id ?? pid) }
          : updated ?? rowHint;
      void loadRunDetails(rid, hintForLoad);
    } catch (e) {
      const msg = detailFromApiErrorMessage(e?.message || e) || String(e);
      appendActivityLog(`Run ${rid}: move to project ${pid} failed — ${msg}`, {
        name: e?.name,
        message: String(e?.message || e).slice(0, 2000),
      });
      setUiError(setError, e);
    } finally {
      setRunProjectMoveInFlight(false);
    }
  };

  /**
   * Workspace-tick + Total performance — updates Run setup (summary + hourly chart), performance, sidebar cards.
   * Conversation/reminder rollups still refresh on loadRunDetails or full workspace-lite.
   * Returns a Promise so callers (e.g. bulk-send poll) can await and avoid stacking skipped refreshes.
   */
  const refreshRunMetricsOnly = useCallback((runId) => {
    if (!runId) return Promise.resolve();
    if (restartsInFlightRef.current[runId]) {
      appendActivityLog(
        `[metrics SKIPPED] run_id=${runId}: restart/background work in progress — not starting parallel GET /workspace-tick + /global-performance (worker/DB may be busy; avoids starving other tabs).`,
      );
      return Promise.resolve();
    }
    if (metricsPollInFlightRef.current) {
      appendActivityLog(
        `[metrics SKIPPED] run_id=${runId}: previous metrics poll still in flight — lightweight GETs can wait behind GET /runs/${runId}/workspace-tick + GET /sending/global-performance.`,
      );
      return Promise.resolve();
    }
    metricsPollAbortRef.current?.abort();
    const ac = new AbortController();
    metricsPollAbortRef.current = ac;
    metricsPollInFlightRef.current = true;
    appendActivityLog(
      `[metrics START] run_id=${runId}: parallel GET /runs/${runId}/workspace-tick (phase + setup_summary + performance + hourly chart) + GET /sending/global-performance`,
    );
    return (async () => {
      const bundleT0 = typeof performance !== "undefined" ? performance.now() : Date.now();
      try {
        const [wsLite, tp] = await Promise.all([
          logTimedApi(
            `metrics workspace-tick`,
            `/runs/${runId}/workspace-tick`,
            { timeoutMs: POLL_METRICS_TIMEOUT_MS, signal: ac.signal },
          ),
          logTimedApi(`metrics global-performance`, `/sending/global-performance`, {
            timeoutMs: POLL_METRICS_TIMEOUT_MS,
            signal: ac.signal,
          }),
        ]);
        const bundleMs = Math.round(
          (typeof performance !== "undefined" ? performance.now() : Date.now()) - bundleT0,
        );
        appendActivityLog(
          `[metrics BUNDLE OK] run_id=${runId} wall-clock ${bundleMs}ms (both requests finished; server may still have been busy before this tick).`,
        );
        appendHumanUiActivityInformers(wsLite, appendActivityLog);
        metricsSilentFailureLastLogAtRef.current = 0;
        setWorkspace((prev) => {
          if (!prev || Number(prev.id) !== Number(runId)) return prev;
          const merged = mergeWorkspaceLiteInto(prev, wsLite);
          if (merged) snapshotWriteRunCards(runId, merged);
          return merged;
        });
        setTotalPerformance({
          emails_sent: Number(tp?.emails_sent) || 0,
          emails_sent_24h: Number(tp?.emails_sent_24h) || 0,
          replies: Number(tp?.replies) || 0,
        });
        setRunsList((prev) => {
          if (!Array.isArray(prev)) return prev;
          return prev.map((r) =>
            r.id === runId
              ? {
                  ...r,
                  display_phase: wsLite.display_phase ?? r.display_phase,
                  companies_count: wsLite.setup_summary?.companies_collected ?? r.companies_count,
                  contacts_count: wsLite.setup_summary?.contacts_found ?? r.contacts_count,
                  emails_sent: wsLite.performance?.emails_sent ?? r.emails_sent,
                  replies: wsLite.performance?.replies ?? r.replies,
                  active_threads: wsLite.performance?.active_threads ?? r.active_threads,
                }
              : r,
          );
        });
        setSelectedRun((prev) => {
          if (!prev || prev.id !== runId) return prev;
          return {
            ...prev,
            display_phase: wsLite.display_phase ?? prev.display_phase,
            companies_count: wsLite.setup_summary?.companies_collected ?? prev.companies_count,
            contacts_count: wsLite.setup_summary?.contacts_found ?? prev.contacts_count,
            emails_sent: wsLite.performance?.emails_sent ?? prev.emails_sent,
            replies: wsLite.performance?.replies ?? prev.replies,
            active_threads: wsLite.performance?.active_threads ?? prev.active_threads,
          };
        });
      } catch (e) {
        const msg = String(e?.message || e);
        const aborted =
          ac.signal.aborted ||
          e?.name === "AbortError" ||
          /aborted|cancel/i.test(msg);
        if (aborted) {
          appendActivityLog(`[metrics CANCELLED] run_id=${runId} — poll aborted (e.g. switched to Companies tab or new poll replaced this one).`);
        } else if (isConsoleOnlyApiFailure(msg)) {
          const now = Date.now();
          if (now - metricsSilentFailureLastLogAtRef.current >= METRICS_SILENT_FAILURE_LOG_INTERVAL_MS) {
            metricsSilentFailureLastLogAtRef.current = now;
            appendActivityLog(`Run metrics: silent error — ${msg}`, {
              runId,
              source: "refreshRunMetricsOnly",
              note: "Same failure logged at most once per 45s; parallel polls disabled.",
            });
          }
        } else {
          setUiError(setError, e);
        }
      } finally {
        metricsPollInFlightRef.current = false;
        if (metricsPollAbortRef.current === ac) {
          metricsPollAbortRef.current = null;
        }
      }
    })();
  }, [setError, appendActivityLog, logTimedApi]);

  /** Both lists — used by poll during generation and after actions that touch contacts + drafts. */
  const refreshRunContactsAndDrafts = useCallback(
    async (runId) => {
      if (!runId) return;
      const c = ++contactsListFetchSeqRef.current;
      const d = ++draftsListFetchSeqRef.current;
      appendActivityLog(
        `[net START] poll refreshRunContactsAndDrafts [HEAVY: parallel paged] /contacts/run/${runId} + ${emailDraftsRunListPath(runId)}`,
      );
      const bundleT0 = typeof performance !== "undefined" ? performance.now() : Date.now();
      try {
        const [contactsData, draftsData] = await Promise.all([
          fetchAllPagedItems(
            (u) => api(u, { timeoutMs: LOAD_RUN_DETAILS_BUNDLE_TIMEOUT_MS }),
            `/contacts/run/${runId}`,
          ),
          fetchAllPagedItems(
            (u) => api(u, { timeoutMs: LOAD_RUN_DETAILS_BUNDLE_TIMEOUT_MS }),
            emailDraftsRunListPath(runId),
          ),
        ]);
        const bundleMs = Math.round(
          (typeof performance !== "undefined" ? performance.now() : Date.now()) - bundleT0,
        );
        const cn = normalizeContactsRunPayload(contactsData).length;
        const dn = Array.isArray(draftsData) ? draftsData.length : "?";
        appendActivityLog(
          `[net OK] refreshRunContactsAndDrafts ${bundleMs}ms contacts_rows=${cn} drafts_rows=${dn} run_id=${runId}`,
        );
        if (c !== contactsListFetchSeqRef.current || d !== draftsListFetchSeqRef.current) return;
        setContactsListFailedRunId(null);
        setContacts(Array.isArray(contactsData) ? contactsData : normalizeContactsRunPayload(contactsData));
        setDrafts(Array.isArray(draftsData) ? draftsData : []);
        const rid = Number(runId);
        if (Number.isFinite(rid) && rid > 0) {
          contactsListReadyRunIdRef.current = rid;
          draftsListReadyRunIdRef.current = rid;
          setContactsListReadyRunId(rid);
          setDraftsListReadyRunId(rid);
          setDraftsListFailedRunId(null);
        }
        try {
          const cp = (Array.isArray(contactsData) ? contactsData : normalizeContactsRunPayload(contactsData))
            .slice(0, MAX_CONTACTS_PANEL_LITE)
            .map(stripContactForPanelLite)
            .filter(Boolean);
          const dp = draftsForRunPanelLitePreview(draftsData)
            .map(stripDraftForPanelLite)
            .filter(Boolean);
          snapshotMergeWriteRunPanelLite(runId, { contactsPreview: cp, draftsPreview: dp });
        } catch {
          /* best-effort */
        }
      } catch (e) {
        if (c !== contactsListFetchSeqRef.current || d !== draftsListFetchSeqRef.current) return;
        const msg = String(e?.message || e);
        setContactsListFailedRunId(Number(runId));
        setDraftsListFailedRunId(Number(runId));
        if (isConsoleOnlyApiFailure(msg)) {
          appendActivityLog(`Contacts+drafts (poll): error — ${msg}`, {
            runId,
            source: "refreshRunContactsAndDrafts",
          });
        } else {
          setUiError(setError, e);
        }
      }
    },
    [setError, appendActivityLog],
  );

  /** Contacts tab / contact-analyzer — full GET /contacts/run (deduped list); search is client-side. */
  const refreshRunContactsOnly = useCallback(
    async (runId) => {
      if (!runId) return;
      const seq = ++contactsListFetchSeqRef.current;
      setContactsListFailedRunId(null);
      contactsSectionFetchDepthRef.current += 1;
      setContactsSectionFetchBusy(true);
      try {
        contactsRunListAbortRef.current?.abort();
      } catch {
        /* ignore */
      }
      const ac = new AbortController();
      contactsRunListAbortRef.current = ac;
      appendActivityLog(`Contacts: GET /contacts/run/${runId} (paged; section-only load)`);
      const t0 = typeof performance !== "undefined" ? performance.now() : 0;
      try {
        const contactsData = await fetchAllPagedItems(
          (u) => api(u, { timeoutMs: LOAD_RUN_DETAILS_BUNDLE_TIMEOUT_MS, signal: ac.signal }),
          `/contacts/run/${runId}`,
        );
        if (seq !== contactsListFetchSeqRef.current) return;
        const arr = Array.isArray(contactsData) ? contactsData : normalizeContactsRunPayload(contactsData);
        const clientMs =
          typeof performance !== "undefined" ? Math.round(performance.now() - t0) : null;
        appendActivityLog(`Contacts: received ${arr.length} rows.`, {
          runId,
          clientMs,
          rows: arr.length,
          source: "refreshRunContactsOnly",
        });
        setContacts(arr);
        const rid = Number(runId);
        if (Number.isFinite(rid) && rid > 0) {
          contactsListReadyRunIdRef.current = rid;
          setContactsListReadyRunId(rid);
        }
        try {
          const cp = arr
            .slice(0, MAX_CONTACTS_PANEL_LITE)
            .map(stripContactForPanelLite)
            .filter(Boolean);
          snapshotMergeWriteRunPanelLite(runId, { contactsPreview: cp });
        } catch {
          /* best-effort */
        }
      } catch (e) {
        if (seq !== contactsListFetchSeqRef.current) return;
        const msg = String(e?.message || e);
        if (/aborted|cancel/i.test(msg)) {
          appendActivityLog(`Contacts: cancelled (tab switch or newer refresh).`, {
            runId,
            source: "refreshRunContactsOnly",
          });
          return;
        }
        const clientMs =
          typeof performance !== "undefined" ? Math.round(performance.now() - t0) : null;
        appendActivityLog(`Contacts: error — ${detailFromApiErrorMessage(msg) || msg}`, {
          runId,
          clientMs,
          source: "refreshRunContactsOnly",
        });
        setContactsListFailedRunId(Number(runId));
        if (isConsoleOnlyApiFailure(msg)) {
          /* already logged above */
        } else {
          setUiError(setError, e);
        }
      } finally {
        if (contactsRunListAbortRef.current === ac) {
          contactsRunListAbortRef.current = null;
        }
        contactsSectionFetchDepthRef.current = Math.max(0, contactsSectionFetchDepthRef.current - 1);
        setContactsSectionFetchBusy(contactsSectionFetchDepthRef.current > 0);
      }
    },
    [setError, appendActivityLog],
  );

  /** Drafts tab — DB read for this section only. */
  const refreshRunDraftsOnly = useCallback(
    async (runId) => {
      if (!runId) return;
      const seq = ++draftsListFetchSeqRef.current;
      draftsSectionFetchDepthRef.current += 1;
      setDraftsSectionFetchBusy(true);
      try {
        draftsRunListAbortRef.current?.abort();
      } catch {
        /* ignore */
      }
      const dac = new AbortController();
      draftsRunListAbortRef.current = dac;
      appendActivityLog(`Drafts: GET ${emailDraftsRunListPath(runId)} (compact list, body_preview)`);
      const t0 = typeof performance !== "undefined" ? performance.now() : 0;
      try {
        const draftsData = await fetchAllPagedItems(
          (u) => api(u, { timeoutMs: LOAD_RUN_DETAILS_BUNDLE_TIMEOUT_MS, signal: dac.signal }),
          emailDraftsRunListPath(runId),
        );
        if (seq !== draftsListFetchSeqRef.current) return;
        const arr = Array.isArray(draftsData) ? draftsData : [];
        const clientMs =
          typeof performance !== "undefined" ? Math.round(performance.now() - t0) : null;
        const sent = arr.filter((d) => String(d?.status) === "sent").length;
        appendActivityLog(`Drafts: received ${arr.length} items.`, {
          runId,
          clientMs,
          rows: arr.length,
          sent,
          reviewVisibleApprox: arr.length - sent,
          source: "refreshRunDraftsOnly",
        });
        setDrafts(arr);
        const rid = Number(runId);
        if (Number.isFinite(rid) && rid > 0) {
          draftsListReadyRunIdRef.current = rid;
          setDraftsListReadyRunId(rid);
          setDraftsListFailedRunId(null);
        }
        try {
          const dp = draftsForRunPanelLitePreview(arr).map(stripDraftForPanelLite).filter(Boolean);
          snapshotMergeWriteRunPanelLite(runId, { draftsPreview: dp });
        } catch {
          /* best-effort */
        }
      } catch (e) {
        if (seq !== draftsListFetchSeqRef.current) return;
        const msg = String(e?.message || e);
        if (/aborted|cancel/i.test(msg)) {
          appendActivityLog(`Drafts: cancelled (tab switch or newer refresh).`, {
            runId,
            source: "refreshRunDraftsOnly",
          });
          return;
        }
        const clientMs =
          typeof performance !== "undefined" ? Math.round(performance.now() - t0) : null;
        appendActivityLog(`Drafts: error — ${detailFromApiErrorMessage(msg) || msg}`, {
          runId,
          clientMs,
          source: "refreshRunDraftsOnly",
        });
        setDraftsListFailedRunId(Number(runId));
        if (isConsoleOnlyApiFailure(msg)) {
          /* already logged */
        } else {
          setUiError(setError, e);
        }
      } finally {
        if (draftsRunListAbortRef.current === dac) {
          draftsRunListAbortRef.current = null;
        }
        draftsSectionFetchDepthRef.current = Math.max(0, draftsSectionFetchDepthRef.current - 1);
        setDraftsSectionFetchBusy(draftsSectionFetchDepthRef.current > 0);
      }
    },
    [setError, appendActivityLog],
  );

  useEffect(() => {
    if (mainNav !== "contacts" && mainNav !== "contact-analyzer") {
      try {
        contactsRunListAbortRef.current?.abort();
      } catch {
        /* ignore */
      }
    }
    if (mainNav !== "drafts") {
      try {
        draftsRunListAbortRef.current?.abort();
      } catch {
        /* ignore */
      }
    }
  }, [mainNav]);

  /**
   * After POST 202 queued: Gmail runs in a worker thread — poll until this draft is terminal (sent/failed).
   */
  const reconcileAfterSingleDraftSend = useCallback(
    async (runId, draftId) => {
      if (!runId || draftId == null) return;
      const did = Number(draftId);
      if (!Number.isFinite(did)) return;
      for (let i = 0; i < OUTBOUND_SEND_POLL_MAX; i++) {
        try {
          const d = await api(`/email-drafts/${did}`, { timeoutMs: POLL_METRICS_TIMEOUT_MS });
          if (d && ["sent", "failed"].includes(d.status)) {
            break;
          }
        } catch {
          break;
        }
        await new Promise((r) => setTimeout(r, OUTBOUND_SEND_POLL_MS));
      }
      await refreshRunContactsAndDrafts(runId);
      await refreshRunMetricsOnly(runId);
    },
    [refreshRunContactsAndDrafts, refreshRunMetricsOnly],
  );

  /** Bulk 202: poll draft list until nothing is still `sending` (sequential Gmail in worker). */
  const reconcileAfterBulkSend = useCallback(
    async (runId, options = {}) => {
      if (!runId) return;
      const initialSentIds =
        options.initialSentIds instanceof Set
          ? new Set(options.initialSentIds)
          : new Set();
      let prevSentRowCount = -1;
      await new Promise((r) => setTimeout(r, 250));
      for (let i = 0; i < BULK_SEND_DRAFTS_POLL_MAX_ITER; i++) {
        try {
          const draftsData = await fetchAllPagedItems(
            (u) => api(u, { timeoutMs: LOAD_RUN_DETAILS_BUNDLE_TIMEOUT_MS }),
            emailDraftsRunListPath(runId),
          );
          const arr = Array.isArray(draftsData) ? draftsData : [];
          const stillSending = arr.some((x) => x.status === "sending");
          if (Number(selectedRunIdRef.current) === Number(runId)) {
            setDrafts(arr);
            try {
              const dp = draftsForRunPanelLitePreview(arr)
                .map(stripDraftForPanelLite)
                .filter(Boolean);
              snapshotMergeWriteRunPanelLite(runId, { draftsPreview: dp });
            } catch {
              /* best-effort */
            }
          }
          const sentRowCount = arr.filter((x) => String(x?.status) === "sent").length;
          if (prevSentRowCount >= 0 && sentRowCount > prevSentRowCount) {
            await refreshRunMetricsOnly(runId);
          }
          prevSentRowCount = sentRowCount;
          for (const row of arr) {
            if (String(row?.status) !== "sent") continue;
            const did = Number(row.id);
            if (!Number.isFinite(did) || initialSentIds.has(did)) continue;
            initialSentIds.add(did);
            appendActivityLog(
              `→ Sent: draft_id=${did} · ${String(row.company || "—")} · ${String(row.to_email || "—")}`,
              {
                runId,
                draftId: did,
                company: row.company ?? null,
                to_email: row.to_email ?? null,
                source: "reconcileAfterBulkSend",
              },
            );
          }
          if (i >= 2 && !stillSending) break;
        } catch {
          break;
        }
        await new Promise((r) => setTimeout(r, BULK_SEND_DRAFTS_POLL_MS));
      }
      appendActivityLog(`Send all approved: draft poll finished (run_id=${runId}).`, {
        runId,
        source: "reconcileAfterBulkSend",
      });
      // Graph + Run setup strip first (light GETs); heavy contacts/drafts paged load must not block the chart.
      await refreshRunMetricsOnly(runId);
      await refreshRunContactsAndDrafts(runId);
    },
    [appendActivityLog, refreshRunContactsAndDrafts, refreshRunMetricsOnly],
  );

  const onStaticAssetsSynced = useCallback(({ assets, packets, runId: rid }) => {
    const current = selectedRunIdRef.current;
    const a = Array.isArray(assets) ? assets : [];
    const p = Array.isArray(packets) ? packets : [];
    if (rid != null && current != null && Number(rid) !== Number(current)) {
      appendRunTraceLog("onStaticAssetsSynced skipped (stale run)", {
        payloadRunId: rid,
        selectedRunId: current,
        assetsCount: a.length,
        packetsCount: p.length,
      });
      return;
    }
    appendRunTraceLog("onStaticAssetsSynced apply", {
      runId: rid ?? current,
      assetsCount: a.length,
      packetsCount: p.length,
      packetIds: p.slice(0, 8).map((x) => x?.id),
    });
    setAssetsLibrary(a);
    setRunAssetPackets(p);
    assetsLibraryFetchedRef.current = true;
    assetPacketsLoadedForRunIdRef.current = rid ?? null;
  }, [appendRunTraceLog]);

  const loadContactAnalyzer = useCallback(async () => {
    const rid = selectedRun?.id;
    if (!rid) {
      setAnalyzerRows([]);
      return;
    }
    setAnalyzerBulkNote("");
    setAnalyzerLoading(true);
    appendActivityLog(`Contact analyzer: GET /runs/${rid}/contact-analyzer`);
    try {
      const data = await api(`/runs/${rid}/contact-analyzer`);
      setAnalyzerRows(Array.isArray(data?.rows) ? data.rows : []);
      appendActivityLog(`Contact analyzer: ${Array.isArray(data?.rows) ? data.rows.length : 0} rows.`);
    } catch (e) {
      appendActivityLog(`Contact analyzer: ${detailFromApiErrorMessage(e?.message || e) || String(e)}`);
      setUiError(setError, e);
      setAnalyzerRows([]);
    } finally {
      setAnalyzerLoading(false);
    }
  }, [selectedRun?.id, appendActivityLog]);

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
    if (mainNav === "drafts") void loadSetupIntegration();
  }, [mainNav, loadSetupIntegration]);

  /** Header «LLMs · CDN» — one GET /setup/status when a project is selected (not tied to Drafts/Assets only). */
  useEffect(() => {
    if (!selectedProject) return;
    void loadSetupIntegration();
  }, [selectedProject?.id, loadSetupIntegration]);

  /** Drop section payloads when leaving that section — no hoarding lists for tabs you are not viewing. */
  useEffect(() => {
    if (mainNav !== "drafts") {
      setDrafts([]);
      setDraftsListReadyRunId(null);
      draftsListReadyRunIdRef.current = null;
    }
    /** Drafts UI joins drafts + contacts (e.g. «Generating…» placeholders) — keep contacts while on Drafts. */
    if (!["contacts", "contact-analyzer", "companies", "drafts"].includes(mainNav)) {
      setContacts([]);
      setContactsListReadyRunId(null);
      contactsListReadyRunIdRef.current = null;
    }
    if (mainNav !== "companies") {
      setCompaniesPanel(null);
    }
    if (mainNav !== "contact-analyzer") {
      setAnalyzerRows([]);
      setAnalyzerLoading(false);
    }
  }, [mainNav]);

  const prevRunIdDebugRef = useRef(null);
  useEffect(() => {
    const id = selectedRun?.id ?? null;
    const prev = prevRunIdDebugRef.current;
    if (prev === id) return;
    appendRunTraceLog("run switch (context)", {
      runIdFrom: prev,
      runIdTo: id,
      mainNav,
      section:
        mainNav === "runs"
          ? "Runs list"
          : mainNav === "contacts"
            ? "Review contacts"
            : mainNav === "drafts"
              ? "Review drafts"
              : mainNav === "companies"
                ? "Companies"
                : mainNav === "contact-analyzer"
                  ? "Contact analyzer"
                  : `Tracking / ${String(mainNav)}`,
    });
    prevRunIdDebugRef.current = id;
  }, [selectedRun?.id, mainNav, appendRunTraceLog]);

  /** Asset library + packets — refetch when selected run id changes. Do not clear lists before
   * the request finishes (avoids empty UI while in flight); drop stale responses via generation. */
  useEffect(() => {
    const rid = selectedRun?.id;
    if (!rid) {
      assetsFetchGenerationRef.current += 1;
      appendRunTraceLog("assets/packets effect: no run — clear library + packets state", {
        gen: assetsFetchGenerationRef.current,
      });
      setRunAssetPackets([]);
      setAssetsLibrary([]);
      assetPacketsLoadedForRunIdRef.current = null;
      return;
    }
    if (!mainNavNeedsParentAssetsFetch(mainNav)) {
      assetsFetchGenerationRef.current += 1;
      appendRunTraceLog("assets/packets effect: skipped (nav does not use parent assets — avoid starving /contacts)", {
        runId: rid,
        mainNav,
        gen: assetsFetchGenerationRef.current,
      });
      return;
    }
    const gen = ++assetsFetchGenerationRef.current;
    appendRunTraceLog("assets/packets effect: fetch start (parent)", {
      runId: rid,
      gen,
      requests: ["GET /assets", `GET /asset-packets/run/${rid}`],
    });
    void (async () => {
      try {
        const [assetsData, packetsData] = await Promise.all([
          api(`/assets`, { timeoutMs: LOAD_RUN_DETAILS_BUNDLE_TIMEOUT_MS }),
          api(`/asset-packets/run/${rid}`, { timeoutMs: LOAD_RUN_DETAILS_BUNDLE_TIMEOUT_MS }),
        ]);
        if (gen !== assetsFetchGenerationRef.current) {
          appendRunTraceLog("assets/packets effect: discard (stale gen after await)", {
            runId: rid,
            gen,
            currentGen: assetsFetchGenerationRef.current,
          });
          return;
        }
        const al = Array.isArray(assetsData) ? assetsData : [];
        const pk = Array.isArray(packetsData) ? packetsData : [];
        appendRunTraceLog("assets/packets effect: apply (parent)", {
          runId: rid,
          gen,
          assetsCount: al.length,
          packetsCount: pk.length,
          packetIds: pk.slice(0, 8).map((x) => x?.id),
        });
        setAssetsLibrary(al);
        setRunAssetPackets(pk);
        assetsLibraryFetchedRef.current = true;
        assetPacketsLoadedForRunIdRef.current = rid;
      } catch (e) {
        if (gen !== assetsFetchGenerationRef.current) {
          appendRunTraceLog("assets/packets effect: error ignored (stale gen)", {
            runId: rid,
            gen,
            err: String(e?.message || e),
          });
          return;
        }
        appendRunTraceLog("assets/packets effect: GET failed — keep previous lists (no clear)", {
          runId: rid,
          gen,
          err: String(e?.message || e),
        });
        const msg = detailFromApiErrorMessage(e?.message || e) || String(e?.message || e || "");
        activityLogAppendRef?.(`Assets/packets GET failed (run_id=${rid}): ${msg || "unknown error"}`, {
          runId: rid,
          source: "assetsPacketsFetch",
        });
      }
    })();
  }, [selectedRun?.id, mainNav, appendRunTraceLog]);

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

  /**
   * Single GET /runs/:id/companies (first page). Used by two sequenced triggers: (1) run id or main nav
   * changes — React effect cleanup aborts the previous request; (2) companiesRefreshNonce only — same
   * effect deps do NOT re-run, so workspace `companies_collected` updates cannot cancel an in-flight load
   * via effect cleanup (only an explicit follow-up fetch replaces it).
   */
  const startCompaniesSnapshotFetch = useCallback(() => {
    if (companiesListAbortRef.current) {
      try {
        companiesListAbortRef.current.abort();
      } catch {
        /* ignore */
      }
      companiesListAbortRef.current = null;
    }

    const runId = selectedRunIdRef.current;
    if (runId == null || mainNavRef.current !== "companies") {
      setCompaniesLoading(false);
      if (runId == null) {
        setCompaniesPanel(null);
        companiesFetchRunIdRef.current = null;
      }
      return;
    }
    const rid = Number(runId);
    companiesFetchRunIdRef.current = rid;

    const ac = new AbortController();
    companiesListAbortRef.current = ac;

    const seq = ++companiesListFetchSeqRef.current;
    setCompaniesListFailedRunId(null);
    setCompaniesLoading(true);
    (async () => {
      const t0 = typeof performance !== "undefined" ? performance.now() : 0;
      try {
        const ps = new URLSearchParams();
        ps.set("limit", String(COMPANIES_FETCH_MAX));
        ps.set("offset", "0");
        const path = `/runs/${rid}/companies?${ps}`;
        appendActivityLogRef.current(`Companies: requesting table snapshot (run_id=${rid})…`, {
          runId: rid,
          source: "companiesTab",
        });
        const data = await api(path, {
          timeoutMs: COMPANIES_HTTP_TIMEOUT_MS,
          signal: ac.signal,
        });
        if (seq !== companiesListFetchSeqRef.current) return;
        {
          const cur = selectedRunIdRef.current;
          if (cur != null && rid != null && Number(cur) !== Number(rid)) return;
        }
        const normalized = normalizeCompaniesPanelResponse(data, 0);
        const { companies, companies_total } = normalized;
        setCompaniesPanel(normalized);
        setCompaniesLoading(false);
        const clientMs =
          typeof performance !== "undefined" ? Math.round(performance.now() - t0) : null;
        appendActivityLogRef.current(
          `Companies: snapshot OK total=${companies_total} loaded_rows=${companies.length} client=${clientMs ?? "?"}ms collect=${data?.collect_step_status ?? "—"} find=${data?.find_step_status ?? "—"} (pages ${WORKSPACE_TABLE_PAGE_SIZE}/page)`,
          {
            runId: rid,
            companies_total,
            pageLen: companies.length,
            clientMs,
            collect_step_status: data?.collect_step_status,
            find_step_status: data?.find_step_status,
            limit: COMPANIES_FETCH_MAX,
            offset: 0,
            source: "companiesTab",
          },
        );
      } catch (e) {
        if (seq !== companiesListFetchSeqRef.current) return;
        {
          const cur = selectedRunIdRef.current;
          if (cur != null && rid != null && Number(cur) !== Number(rid)) return;
        }
        const msg = String(e?.message || e);
        const aborted =
          ac.signal.aborted || e?.name === "AbortError" || /aborted|cancel/i.test(msg);
        if (aborted) {
          return;
        }
        const clientMs =
          typeof performance !== "undefined" ? Math.round(performance.now() - t0) : null;
        appendActivityLogRef.current(
          `Companies: error — ${detailFromApiErrorMessage(msg) || msg} (client ${clientMs ?? "?"}ms, rid=${rid}, limit=${COMPANIES_FETCH_MAX}, offset=0)`,
          {
            runId: rid,
            message: msg,
            clientMs,
            errorName: e?.name,
            source: "companiesTab",
          },
        );
        setCompaniesPanel(null);
        setCompaniesListFailedRunId(rid);
        if (!isConsoleOnlyApiFailure(msg)) {
          setUiError(setError, e);
        }
      } finally {
        if (companiesListAbortRef.current === ac) {
          companiesListAbortRef.current = null;
        }
        if (seq === companiesListFetchSeqRef.current) {
          setCompaniesLoading(false);
        }
      }
    })();
  }, []);

  useEffect(() => {
    prevCompaniesCollectedRef.current = null;
  }, [selectedRun?.id]);

  /**
   * When collect finishes or grows the list, workspace-lite bumps companies_collected — refresh the table
   * via nonce. Do not put that number on the GET effect deps: every poll + pagination was racing (seq
   * cancelled in-flight page loads and made Next feel broken).
   */
  useEffect(() => {
    if (mainNav !== "companies" || !selectedRun?.id) return;
    const raw = workspace?.setup_summary?.companies_collected;
    const v = typeof raw === "number" && Number.isFinite(raw) ? raw : Number(raw);
    if (!Number.isFinite(v)) return;
    const prev = prevCompaniesCollectedRef.current;
    if (prev === null) {
      prevCompaniesCollectedRef.current = v;
      return;
    }
    if (prev === v) return;
    prevCompaniesCollectedRef.current = v;
    setCompaniesRefreshNonce((n) => n + 1);
  }, [mainNav, selectedRun?.id, workspace?.setup_summary?.companies_collected]);

  useEffect(() => {
    const rid = selectedRun?.id != null ? Number(selectedRun.id) : null;
    const prev = prevSelectedRunIdForCompaniesCacheRef.current;
    prevSelectedRunIdForCompaniesCacheRef.current =
      Number.isFinite(rid) && rid > 0 ? rid : null;
    if (!Number.isFinite(rid) || rid <= 0) {
      setCompaniesPanel(null);
      companiesFetchRunIdRef.current = null;
      return;
    }
    if (prev === rid) return;
    companiesFetchRunIdRef.current = null;
    setCompaniesPanel(null);
  }, [selectedRun?.id]);

  /** Stream A — switch run or main section: abort previous GET via effect cleanup only for these deps. */
  useEffect(() => {
    startCompaniesSnapshotFetch();
    return () => {
      try {
        companiesListAbortRef.current?.abort();
      } catch {
        /* ignore */
      }
    };
  }, [selectedRun?.id, mainNav, startCompaniesSnapshotFetch]);

  /**
   * Stream B — workspace “how many companies collected” changed while you stay on the same run and
   * Companies section: bump refresh counter only; does not re-run stream A, so metrics cannot cancel
   * the in-flight snapshot via React cleanup.
   */
  useEffect(() => {
    if (mainNav !== "companies" || selectedRun?.id == null) return;
    const prev = lastCompaniesRefreshNonceAppliedRef.current;
    if (prev === companiesRefreshNonce) return;
    if (prev === null) {
      lastCompaniesRefreshNonceAppliedRef.current = companiesRefreshNonce;
      return;
    }
    lastCompaniesRefreshNonceAppliedRef.current = companiesRefreshNonce;
    startCompaniesSnapshotFetch();
  }, [companiesRefreshNonce, mainNav, selectedRun?.id, startCompaniesSnapshotFetch]);

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
      setSelectedRun((prev) => {
        if (prev && Number(prev.project_id) !== Number(pid)) {
          return prev;
        }
        return null;
      });
      setWorkspace((ws) => {
        const sr = selectedRun;
        if (sr && Number(sr.project_id) !== Number(pid)) {
          return ws;
        }
        return null;
      });
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
          await loadRunDetails(targetId, runRow, {
            ...listInclusionsForMainNav(mainNavRef.current),
          });
        } else {
          const sr = selectedRunRef.current;
          const orphan = sr && Number(sr.project_id) !== Number(pid);
          if (orphan) {
            setSelectedRun(sr);
            setContacts([]);
            setDrafts([]);
            void loadRunDetails(sr.id, sr);
          } else {
            setSelectedRun(null);
            setContacts([]);
            setDrafts([]);
            setWorkspace(null);
          }
        }
      } catch (e) {
        if (ac.signal.aborted) return;
        const msg = String(e?.message || e);
        if (isConsoleOnlyApiFailure(msg)) {
          appendActivityLog(`Runs list: ${msg}`, { projectId: pid, source: "runsProjectList" });
        } else {
          setRunsList([]);
          setError(msg);
        }
      }
    })();
    return () => ac.abort();
    /**
     * `mainNav` intentionally omitted: including it aborted GET /runs/project on every tab switch
     * (“Timed out or cancelled” spam). Section lists use `mainNav` via effects + refreshRun*Only.
     */
  }, [selectedProject, appendActivityLog]);

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
    if (totalPerformance && typeof totalPerformance === "object") {
      snapshotWriteTotalPerformance(totalPerformance);
    }
  }, [totalPerformance]);

  /**
   * Per-section list load from DB. Depends on *ready run id* so we re-fetch when lists were cleared
   * (e.g. loadRunDetails with `includeDrafts` on the same run) while nav did not change.
   */
  useEffect(() => {
    const rid = Number(selectedRun?.id);
    if (!Number.isFinite(rid) || rid <= 0) return;
    if (mainNav !== "drafts") return;
    if (draftsListReadyRunId === rid) return;
    /** Avoid duplicating GETs while `loadRunDetails` already loads drafts for this run. */
    if (runDetailsLoading) return;
    void refreshRunDraftsOnly(rid);
  }, [selectedRun?.id, mainNav, draftsListReadyRunId, refreshRunDraftsOnly, runDetailsLoading]);

  useEffect(() => {
    const rid = Number(selectedRun?.id);
    if (!Number.isFinite(rid) || rid <= 0) return;
    if (mainNav !== "contacts" && mainNav !== "contact-analyzer") return;
    if (contactsListReadyRunId === rid) return;
    /** Avoid duplicating GETs while `loadRunDetails` already loads contacts for this run. */
    if (runDetailsLoading) return;
    void refreshRunContactsOnly(rid);
  }, [selectedRun?.id, mainNav, contactsListReadyRunId, refreshRunContactsOnly, runDetailsLoading]);

  /** Clear “generating draft” when a reviewable draft row appears for that contact (not `sent` — those are hidden from Review). */
  useEffect(() => {
    if (!Array.isArray(drafts)) return;
    setPendingOutboundDraftByContactId((prev) => {
      const next = { ...prev };
      let changed = false;
      for (const k of Object.keys(next)) {
        const cid = Number(k);
        const hasReviewableDraft = drafts.some(
          (d) => Number(d.contact_id) === cid && !isOutboundDraftClosedForReview(d),
        );
        if (hasReviewableDraft) {
          delete next[k];
          changed = true;
          if (outboundDraftGenTimeoutRef.current[cid]) {
            clearTimeout(outboundDraftGenTimeoutRef.current[cid]);
            delete outboundDraftGenTimeoutRef.current[cid];
          }
        }
      }
      return changed ? next : prev;
    });
  }, [drafts]);

  /** While LLM generates a draft — poll lists only on Drafts (not when you are in another section). */
  useEffect(() => {
    const busy = Object.keys(pendingOutboundDraftByContactId).some(
      (k) => pendingOutboundDraftByContactId[k],
    );
    if (!busy || !selectedRun?.id || mainNav !== "drafts") return;
    void refreshRunContactsAndDrafts(selectedRun.id);
    const t = setInterval(() => {
      void refreshRunContactsAndDrafts(selectedRun.id);
    }, 2500);
    return () => clearInterval(t);
  }, [pendingOutboundDraftByContactId, selectedRun?.id, mainNav, refreshRunContactsAndDrafts]);

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
    const styleA = normalizeProfessionalProfileFromApi(newRunForm.email_style_mode);
    const styleB = normalizeProfessionalProfileFromApi(b.email_style_mode);
    return (
      newRunForm.notes.trim() !== b.notes ||
      newRunForm.segment.trim() !== b.segment ||
      newRunForm.outreach_brief.trim() !== b.outreach_brief ||
      styleA !== styleB
    );
  }, [
    newRunForm.notes,
    newRunForm.segment,
    newRunForm.outreach_brief,
    newRunForm.email_style_mode,
    newRunBaseline,
  ]);

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
      editFormFetchSeqRef.current += 1;
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
      setError("Run name and Region / Country / State are required.");
      return;
    }
    if (!newRunForm.outreach_brief.trim()) {
      setError("Outreach brief (search description) is required.");
      return;
    }
    if (!outreachBriefHasOfferOrGoal(newRunForm.outreach_brief)) {
      setError(
        "Fill at least one search section (e.g. reason for search or field of activity). " +
          "Legacy Offer:/Goal: lines still count.",
      );
      return;
    }
    try {
      setNewRunCreateInFlight(true);
      setError("");
      const pid = projectPk(selectedProject);
      const styleToSave = normalizeProfessionalProfileFromApi(newRunForm.email_style_mode);
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
      try {
        await api(`/runs/${run.id}/email-style`, {
          method: "PATCH",
          timeoutMs: RUN_SETUP_PATCH_TIMEOUT_MS,
          body: { email_style_mode: styleToSave },
        });
      } catch (e) {
        setUiError(setError, e);
      }
      await loadRunDetails(run.id, undefined, { ...listInclusionsForMainNav(mainNav) });
      void refreshRunContactsAndDrafts(run.id);
      setNewRunForm({
        name: "",
        notes: "",
        segment: "",
        outreach_brief: DEFAULT_OUTREACH_BRIEF,
        email_style_mode: "auto",
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
      const rid = newRunBaseline.runId;
      const merged = await api(`/runs/${rid}/outreach`, {
        method: "PATCH",
        timeoutMs: RUN_SETUP_PATCH_TIMEOUT_MS,
        body: {
          notes: newRunForm.notes.trim() || undefined,
          segment: newRunForm.segment.trim(),
          outreach_brief: newRunForm.outreach_brief.trim(),
          email_style_mode: normalizeProfessionalProfileFromApi(newRunForm.email_style_mode),
        },
      });
      setNewRunOpen(false);
      setRunsList((prev) => {
        if (!Array.isArray(prev)) return prev;
        return prev.map((r) =>
          r.id === rid
            ? {
                ...r,
                name: merged.name != null && merged.name !== "" ? String(merged.name) : r.name,
                notes: merged.notes,
                segment: merged.segment,
              }
            : r,
        );
      });
      setSelectedRun((prev) =>
        prev && prev.id === rid ? { ...prev, ...merged } : prev,
      );
      setNewRunForm({
        name: "",
        notes: "",
        segment: "",
        outreach_brief: DEFAULT_OUTREACH_BRIEF,
        email_style_mode: "auto",
      });
    } catch (e) {
      setUiError(setError, e);
    } finally {
      setNewRunUpdateInFlight(false);
    }
  };

  const openRunEditDialog = (runRow) => {
    if (!runRow?.id || !selectedProject) return;
    setError("");
    const rid = Number(runRow.id);
    const seeded = seedNewRunFormFromRun(runRow);
    setNewRunForm(seeded);
    setNewRunBaseline({
      runId: rid,
      name: seeded.name.trim(),
      notes: seeded.notes.trim(),
      segment: seeded.segment.trim(),
      outreach_brief: seeded.outreach_brief.trim(),
      email_style_mode: normalizeProfessionalProfileFromApi(seeded.email_style_mode),
    });
    setNewRunOpen(true);
    const seq = ++editFormFetchSeqRef.current;
    appendActivityLog(`Edit run: opened — GET /runs/${rid}/edit-form (background)`);
    void (async () => {
      try {
        const run = await api(`/runs/${runRow.id}/edit-form`, { timeoutMs: EDIT_FORM_OPEN_TIMEOUT_MS });
        if (seq !== editFormFetchSeqRef.current) return;
        const next = seedNewRunFormFromEditFormRead(run);
        setNewRunForm(next);
        setNewRunBaseline({
          runId: run.id,
          name: next.name.trim(),
          notes: next.notes.trim(),
          segment: next.segment.trim(),
          outreach_brief: next.outreach_brief.trim(),
          email_style_mode: normalizeProfessionalProfileFromApi(next.email_style_mode),
        });
        appendActivityLog("Edit run: fields loaded from server.");
        queueMicrotask(() => {
          refreshRunMetricsOnly(run.id);
        });
      } catch (e) {
        if (seq !== editFormFetchSeqRef.current) return;
        appendActivityLog(`Edit run: load failed — ${detailFromApiErrorMessage(e?.message || e) || String(e)}`);
        setUiError(setError, e);
      }
    })();
  };

  /** @param {{ prefilledFromSelected?: boolean }} [options] — prefill from current run (e.g. Runs tab “Continue outreach”); bare “New run” opens an empty form. */
  const openNewRunDialog = useCallback((options = {}) => {
    editFormFetchSeqRef.current += 1;
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
        email_style_mode: normalizeProfessionalProfileFromApi(seeded.email_style_mode),
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
      await loadRunDetails(nextOpen ? nextOpen.id : closedId, undefined, { ...listInclusionsForMainNav(mainNav) });
    } catch (e) {
      setUiError(setError, e);
    }
  };

  const openRunById = async (runId, runRowHint) => {
    setSwitchRunOpen(false);
    await loadRunDetails(runId, runRowHint, { ...listInclusionsForMainNav(mainNav) });
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

  const startRestartRunPolling = (runId) => {
    if (restartPollIntervalsRef.current[runId]) return;
    const tick = async () => {
      try {
        const run = await api(`/runs/${runId}`, { timeoutMs: 20000 });
        const st = run?.status;
        if (st === "needs_review" || st === "failed") {
          clearInterval(restartPollIntervalsRef.current[runId]);
          delete restartPollIntervalsRef.current[runId];
          setRestartsInFlight((prev) => {
            const n = { ...prev };
            delete n[runId];
            return n;
          });
          appendActivityLog(`Continue outreach: finished for run_id=${runId} (status=${st}).`);
          const proj = selectedProjectRef.current;
          const pid = proj ? projectPk(proj) : null;
          if (pid) {
            try {
              setRunsList(
                orderRunsOpenFirst(
                  await api(`/runs/project/${pid}`, { timeoutMs: LOAD_RUN_DETAILS_BUNDLE_TIMEOUT_MS }),
                ),
              );
            } catch {
              /* ignore */
            }
          }
          if (selectedRunIdRef.current === runId) {
            void loadRunDetails(runId, undefined, {
              requestTimeoutMs: LOAD_RUN_DETAILS_BUNDLE_TIMEOUT_MS,
              ...listInclusionsForMainNav(mainNavRef.current),
            });
          }
          void loadSetupIntegration();
        }
      } catch {
        /* poll again */
      }
    };
    restartPollIntervalsRef.current[runId] = setInterval(() => void tick(), 2000);
    void tick();
  };

  const confirmRestartRun = async () => {
    if (!selectedProject || !restartDialogRun) return;
    const { id: runId, name: runName } = restartDialogRun;
    if (restartsInFlight[runId]) return;
    setError("");
    setRestartDialogOpen(false);
    setRestartDialogRun(null);
    /** Invalidate in-flight loadRunDetails so their catch does not log spurious timeouts while restart runs. */
    runDetailsLoadGenRef.current += 1;
    setRunDetailsLoading(false);
    try {
      appendActivityLog(
        `Continue outreach: POST /runs/${runId}/restart (background — you may switch to other runs)`,
      );
      const res = await api(`/runs/${runId}/restart`, { method: "POST", timeoutMs: 120000 });
      if (!res?.accepted) {
        appendActivityLog(`Continue outreach: unexpected API response for run_id=${runId}`);
        return;
      }
      setRestartsInFlight((prev) => ({ ...prev, [runId]: { name: runName } }));
      appendActivityLog(`Continue outreach: accepted (run_id=${runId}), waiting for background completion…`);
      startRestartRunPolling(runId);
    } catch (e) {
      const raw = String(e?.message || e);
      const msg = detailFromApiErrorMessage(raw) || raw;
      if (raw.includes("409") || /already running/i.test(msg)) {
        appendActivityLog(`Continue outreach: already in progress for run_id=${runId}`);
      } else {
        appendActivityLog(`Continue outreach: error — ${msg}`, { runId });
        setUiError(setError, e);
      }
    }
  };

  const continueRun = async () => {
    if (!selectedRun) return;
    try {
      setError("");
      const run = await api(`/runs/${selectedRun.id}/continue`, { method: "POST" });
      setSelectedRun((prev) => (prev && prev.id === run.id ? { ...prev, ...run } : prev));
      void loadRunDetails(run.id, undefined, {
        requestTimeoutMs: LOAD_RUN_DETAILS_BUNDLE_TIMEOUT_MS,
        ...listInclusionsForMainNav(mainNav),
      }).catch((err) => setUiError(setError, err));
    } catch (e) {
      setUiError(setError, e);
    }
  };

  const approveContact = async (contactId) => {
    setContactApproveBusyId(contactId);
    const cid = Number(contactId);
    const prevSnapshot = contacts.find((c) => Number(c.id) === cid);
    setContacts((prev) =>
      prev.map((c) =>
        Number(c.id) === cid
          ? { ...c, review_status: "approved", reviewed_at: new Date().toISOString() }
          : c,
      ),
    );
    setPendingOutboundDraftByContactId((prev) => ({ ...prev, [cid]: true }));
    if (outboundDraftGenTimeoutRef.current[cid]) {
      clearTimeout(outboundDraftGenTimeoutRef.current[cid]);
    }
    outboundDraftGenTimeoutRef.current[cid] = setTimeout(() => {
      setPendingOutboundDraftByContactId((p) => {
        if (!p[cid]) return p;
        const n = { ...p };
        delete n[cid];
        return n;
      });
      delete outboundDraftGenTimeoutRef.current[cid];
    }, 120000);
    try {
      setError("");
      const updated = await api(`/contacts/${contactId}/review`, {
        method: "PATCH",
        body: { review_status: "approved" },
      });
      setContacts((prev) =>
        prev.map((c) => (Number(c.id) === cid ? { ...c, ...updated } : c)),
      );
      if (selectedRun) {
        void refreshRunContactsAndDrafts(selectedRun.id);
        refreshRunMetricsOnly(selectedRun.id);
      }
    } catch (e) {
      setUiError(setError, e);
      if (prevSnapshot) {
        setContacts((prev) =>
          prev.map((c) => (Number(c.id) === cid ? { ...c, ...prevSnapshot } : c)),
        );
      }
      setPendingOutboundDraftByContactId((prev) => {
        const n = { ...prev };
        delete n[cid];
        return n;
      });
      if (outboundDraftGenTimeoutRef.current[cid]) {
        clearTimeout(outboundDraftGenTimeoutRef.current[cid]);
        delete outboundDraftGenTimeoutRef.current[cid];
      }
      if (selectedRun) {
        void refreshRunContactsAndDrafts(selectedRun.id);
        refreshRunMetricsOnly(selectedRun.id);
      }
    } finally {
      setContactApproveBusyId((id) => (id === contactId ? null : id));
    }
  };

  const reviewContact = async (id, review_status) => {
    try {
      setError("");
      const updated = await api(`/contacts/${id}/review`, {
        method: "PATCH",
        body: { review_status },
      });
      const rid = Number(id);
      setContacts((prev) => prev.map((c) => (Number(c.id) === rid ? { ...c, ...updated } : c)));
      if (review_status === "approved") {
        setPendingOutboundDraftByContactId((prev) => ({ ...prev, [rid]: true }));
        if (outboundDraftGenTimeoutRef.current[rid]) {
          clearTimeout(outboundDraftGenTimeoutRef.current[rid]);
        }
        outboundDraftGenTimeoutRef.current[rid] = setTimeout(() => {
          setPendingOutboundDraftByContactId((p) => {
            if (!p[rid]) return p;
            const n = { ...p };
            delete n[rid];
            return n;
          });
          delete outboundDraftGenTimeoutRef.current[rid];
        }, 120000);
      } else {
        setPendingOutboundDraftByContactId((prev) => {
          const n = { ...prev };
          delete n[rid];
          return n;
        });
        if (outboundDraftGenTimeoutRef.current[rid]) {
          clearTimeout(outboundDraftGenTimeoutRef.current[rid]);
          delete outboundDraftGenTimeoutRef.current[rid];
        }
      }
      if (selectedRun) {
        void refreshRunContactsAndDrafts(selectedRun.id);
        refreshRunMetricsOnly(selectedRun.id);
      }
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
      const cid = Number(contactId);
      setPendingOutboundDraftByContactId((prev) => {
        const n = { ...prev };
        delete n[cid];
        return n;
      });
      if (outboundDraftGenTimeoutRef.current[cid]) {
        clearTimeout(outboundDraftGenTimeoutRef.current[cid]);
        delete outboundDraftGenTimeoutRef.current[cid];
      }
      refreshRunMetricsOnly(selectedRun.id);
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
      const nid = Number(id);
      setDrafts((prev) =>
        prev.map((d) => (Number(d.id) === nid ? { ...d, ...updated } : d)),
      );
      if (selectedRun?.id) {
        void refreshRunContactsAndDrafts(selectedRun.id);
        refreshRunMetricsOnly(selectedRun.id);
      }
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
      const nid = Number(draftId);
      setDrafts((prev) =>
        prev.map((d) => (Number(d.id) === nid ? { ...d, ...updated } : d)),
      );
      if (selectedRun?.id) {
        void refreshRunContactsAndDrafts(selectedRun.id);
        refreshRunMetricsOnly(selectedRun.id);
      }
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
    const nid = Number(draftId);
    try {
      setError("");
      await api(`/email-drafts/${draftId}`, { method: "DELETE" });
      if (Number(editDraft?.id) === nid || editDraftOpenTargetIdRef.current === nid) {
        editDraftFetchSeqRef.current += 1;
        editDraftOpenTargetIdRef.current = null;
        setEditDraft(null);
        setEditDraftLoading(false);
      }
      setDrafts((prev) => prev.filter((d) => Number(d.id) !== nid));
      if (selectedRun?.id) {
        void refreshRunContactsAndDrafts(selectedRun.id);
        refreshRunMetricsOnly(selectedRun.id);
      }
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
    const runId = selectedRun.id;
    setSendingOutboundDraftIds((p) => ({ ...p, [idKey]: true }));
    try {
      setError("");
      await api(`/sending/drafts/${draftId}/send`, { method: "POST" });
    } catch (e) {
      setUiError(setError, e);
      void loadSetupIntegration();
      if (isGmailAuthReconnectErrorMessage(String(e?.message ?? e ?? ""))) {
        openGmailSetup();
      }
    } finally {
      setSendingOutboundDraftIds((p) => {
        const next = { ...p };
        delete next[idKey];
        return next;
      });
    }
    void reconcileAfterSingleDraftSend(runId, draftId);
  };

  const sendAllApproved = async () => {
    if (!selectedRun) return;
    if (!gmailSendReady) {
      openGmailSetup();
      return;
    }
    const runId = selectedRun.id;
    const sentIdsBeforeQueue = new Set(
      (Array.isArray(drafts) ? drafts : [])
        .filter((d) => String(d?.status) === "sent")
        .map((d) => Number(d.id))
        .filter((id) => Number.isFinite(id)),
    );
    setSendAllApprovedBusy(true);
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    try {
      setError("");
      appendActivityLog(`Send all approved: POST /sending/runs/${runId}/send`, { runId });
      const res = await api(`/sending/runs/${runId}/send`, {
        method: "POST",
        timeoutMs: LOAD_RUN_DETAILS_BUNDLE_TIMEOUT_MS,
      });
      const n = res && typeof res.draft_count === "number" ? res.draft_count : null;
      appendActivityLog(
        n != null
          ? `→ Queued for send: ${n} draft(s) (Gmail in background, HTTP 202).`
          : `→ Request accepted (HTTP 202), sending in background.`,
        { runId, draft_count: n, response: res, source: "sendAllApproved" },
      );
      await reconcileAfterBulkSend(runId, { initialSentIds: sentIdsBeforeQueue });
    } catch (e) {
      setUiError(setError, e);
      void loadSetupIntegration();
      if (isGmailAuthReconnectErrorMessage(String(e?.message ?? e ?? ""))) {
        openGmailSetup();
      }
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
      await api(`/sending/runs/${selectedRun.id}/mock-send-preview`, {
        method: "POST",
        timeoutMs: MOCK_SEND_PREVIEW_POST_TIMEOUT_MS,
      });
    } catch (e) {
      setUiError(setError, e);
      void loadSetupIntegration();
      if (isGmailAuthReconnectErrorMessage(String(e?.message ?? e ?? ""))) {
        openGmailSetup();
      }
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
        refreshRunMetricsOnly(runId);
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
        refreshRunMetricsOnly(runId);
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
        refreshRunMetricsOnly(runId);
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

  const closeEditDraftModal = () => {
    if (editDraftSaving) return;
    editDraftGetAbortRef.current?.abort();
    editDraftGetAbortRef.current = null;
    editDraftFetchSeqRef.current += 1;
    editDraftOpenTargetIdRef.current = null;
    setEditDraft(null);
    setEditDraftLoading(false);
  };

  const openEditDraft = (d) => {
    const nid = Number(d?.id);
    if (!Number.isFinite(nid)) {
      appendActivityLog("Edit draft: missing or invalid id", { raw: d?.id });
      return;
    }
    const seq = ++editDraftFetchSeqRef.current;
    editDraftGetAbortRef.current?.abort();
    editDraftGetAbortRef.current = null;
    setApplyAssetsEditScope("none");
    editDraftOpenTargetIdRef.current = nid;

    const rowWithBody =
      typeof d?.body === "string"
        ? d
        : Array.isArray(drafts)
          ? drafts.find((x) => Number(x.id) === nid)
          : null;
    if (rowWithBody && typeof rowWithBody.body === "string") {
      setEditDraftLoading(false);
      setEditDraft(rowWithBody);
      setDraftForm({
        subject: rowWithBody.subject ?? "",
        body: rowWithBody.body ?? "",
        attached_asset_ids: normalizeAttachedAssetIds(rowWithBody.attached_asset_ids),
      });
      appendActivityLog(`Edit draft: using list row (draft_id=${nid}) — no extra GET`, {
        source: "openEditDraft",
      });
      return;
    }

    const ac = new AbortController();
    editDraftGetAbortRef.current = ac;
    setEditDraft(null);
    setEditDraftLoading(true);
    setDraftForm({
      subject: d?.subject ?? "",
      body: "",
      attached_asset_ids: normalizeAttachedAssetIds(d?.attached_asset_ids),
    });
    appendActivityLog(
      `Edit draft: GET /email-drafts/${nid} (timeout ${Math.round(EMAIL_DRAFT_GET_FOR_EDIT_TIMEOUT_MS / 1000)}s, Cancel aborts)`,
    );
    void (async () => {
      try {
        setError("");
        const full = await api(`/email-drafts/${nid}`, {
          signal: ac.signal,
          timeoutMs: EMAIL_DRAFT_GET_FOR_EDIT_TIMEOUT_MS,
        });
        if (seq !== editDraftFetchSeqRef.current) return;
        setEditDraft(full);
        setDraftForm({
          subject: full.subject ?? "",
          body: full.body ?? "",
          attached_asset_ids: normalizeAttachedAssetIds(full.attached_asset_ids),
        });
      } catch (e) {
        if (seq !== editDraftFetchSeqRef.current) return;
        setUiError(setError, e);
        setEditDraft(null);
        editDraftOpenTargetIdRef.current = null;
      } finally {
        if (editDraftGetAbortRef.current === ac) editDraftGetAbortRef.current = null;
        if (seq !== editDraftFetchSeqRef.current) return;
        setEditDraftLoading(false);
      }
    })();
  };

  const saveEditDraft = async () => {
    if (!editDraft || !selectedRun || editDraftSaving || editDraftLoading) return;
    const runId = selectedRun.id;
    const draftId = editDraft.id;
    const applyPending = applyAssetsEditScope === "pending";
    const applyApproved = applyAssetsEditScope === "approved";
    const applyAll = applyPending || applyApproved;
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
          apply_assets_to_pending_drafts: applyPending,
          apply_assets_to_approved_drafts: applyApproved,
        },
        timeoutMs: applyAll ? 120000 : 60000,
      });
    } catch (e) {
      setUiError(setError, e);
      return;
    } finally {
      setEditDraftSaving(false);
    }
    editDraftOpenTargetIdRef.current = null;
    setEditDraft(null);
    setEditDraftLoading(false);
    if (updatedDraft && !applyAll) {
      const nid = Number(draftId);
      setDrafts((prev) =>
        prev.map((d) => (Number(d.id) === nid ? { ...d, ...updatedDraft } : d)),
      );
    }
    if (applyAll && selectedRun?.id) {
      void refreshRunContactsAndDrafts(selectedRun.id);
    }
    refreshRunMetricsOnly(runId);
  };

  const mountSignatureEditorDeferred = () => {
    setSignatureEditorMount(false);
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        setSignatureEditorMount(true);
      });
    });
  };

  /**
   * Prefer GET /runs/:id/review-setup-fields (tiny JSON). If the server has not been restarted
   * and returns 404, fall back to GET /runs/:id so the dialogs still work.
   */
  const fetchReviewSetupFieldsLite = useCallback(async (runId) => {
    const timeoutCtl = new AbortController();
    const tid = setTimeout(() => timeoutCtl.abort(), RUN_REVIEW_SETUP_LITE_TIMEOUT_MS);
    try {
      const res = await fetch(`${API_BASE}/runs/${runId}/review-setup-fields`, {
        cache: "no-store",
        headers: { Accept: "application/json" },
        signal: timeoutCtl.signal,
      });
      if (res.ok) {
        const d = await res.json();
        snapshotWriteRunSetupPrefs(runId, {
          prompt_setup_text: d.prompt_setup_editor_text,
          signature_html: d.sender_signature_html,
          prompt_setup_saved: Boolean(d.prompt_setup_saved),
          sender_signature_configured: Boolean(d.sender_signature_configured),
        });
        return d;
      }
      const errBody = await res.text();
      if (res.status === 404) {
        try {
          const run = await api(`/runs/${runId}`, { timeoutMs: POLL_METRICS_TIMEOUT_MS });
          setSelectedRun((prev) =>
            prev && Number(prev.id) === Number(run.id) ? { ...prev, ...run } : prev,
          );
          snapshotMergeRunSetupBodiesFromRun(runId, run);
          return {
            prompt_setup_editor_text: getPromptSetupEditorInitialText(run),
            sender_signature_html: String(run.sender_signature_html ?? ""),
            prompt_setup_saved: undefined,
            sender_signature_configured: undefined,
          };
        } catch {
          throw new Error(errBody || "Not found");
        }
      }
      throw new Error(errBody || `Request failed: ${res.status}`);
    } finally {
      clearTimeout(tid);
    }
  }, []);

  /** Warm setup_prefs bodies before user opens Prompt/Signature dialogs (no 404 fallback here). */
  useEffect(() => {
    const rid = selectedRun?.id;
    if (!rid) return;
    let cancelled = false;
    const ctl = new AbortController();
    const tid = setTimeout(() => ctl.abort(), RUN_REVIEW_SETUP_LITE_TIMEOUT_MS);
    void (async () => {
      try {
        const res = await fetch(`${API_BASE}/runs/${rid}/review-setup-fields`, {
          cache: "no-store",
          headers: { Accept: "application/json" },
          signal: ctl.signal,
        });
        if (cancelled || !res.ok) return;
        const d = await res.json();
        snapshotWriteRunSetupPrefs(rid, {
          prompt_setup_text: d.prompt_setup_editor_text,
          signature_html: d.sender_signature_html,
          prompt_setup_saved: Boolean(d.prompt_setup_saved),
          sender_signature_configured: Boolean(d.sender_signature_configured),
        });
      } catch {
        /* ignore — open dialog will call fetchReviewSetupFieldsLite */
      }
    })();
    return () => {
      cancelled = true;
      clearTimeout(tid);
      ctl.abort();
    };
  }, [selectedRun?.id]);

  const openSignatureSetup = async () => {
    if (!selectedRun?.id) return;
    setSignatureFormHtml(getSignatureDialogSeed(selectedRun.id, selectedRun, workspace));
    setSignatureEditorKey((k) => k + 1);
    setSignatureSetupOpen(true);
    mountSignatureEditorDeferred();
    try {
      const d = await fetchReviewSetupFieldsLite(selectedRun.id);
      if (typeof d?.sender_signature_html === "string") {
        setSignatureFormHtml(d.sender_signature_html);
        setSignatureEditorKey((k) => k + 1);
      }
    } catch (e) {
      setUiError(setError, e);
    }
  };

  const openPromptSetup = async () => {
    if (!selectedRun?.id) return;
    setPromptSetupSaving(false);
    setPromptSetupText(getPromptSetupDialogSeed(selectedRun.id, selectedRun));
    setPromptSetupOpen(true);
    try {
      const d = await fetchReviewSetupFieldsLite(selectedRun.id);
      if (typeof d?.prompt_setup_editor_text === "string") {
        setPromptSetupText(d.prompt_setup_editor_text);
      }
    } catch (e) {
      setUiError(setError, e);
    }
  };

  const savePromptSetup = () => {
    if (!selectedRun?.id) return;
    const rid = selectedRun.id;
    const textSnapshot = promptSetupText;
    const prefsBefore = snapshotReadRunSetupPrefs(rid);
    const prevPromptSaved = selectedRun?.prompt_setup_saved;
    const prevPromptText = selectedRun?.prompt_setup_text;
    const prevRunRef = selectedRun;

    setError("");
    snapshotWriteRunSetupPrefs(rid, {
      prompt_setup_saved: textSnapshot.trim().length > 0,
      prompt_setup_text: textSnapshot,
    });
    setRunSetupPrefsRev((x) => x + 1);
    setSelectedRun((prev) => {
      if (!prev || prev.id !== rid) return prev;
      return {
        ...prev,
        prompt_setup_text: textSnapshot.trim().length > 0 ? textSnapshot : "",
        prompt_setup_saved: textSnapshot.trim().length > 0,
      };
    });
    setPromptSetupOpen(false);
    setPromptSetupSaving(false);

    void (async () => {
      try {
        const updated = await api(`/runs/${rid}/prompt-setup`, {
          method: "PATCH",
          body: { prompt_setup_text: textSnapshot },
          timeoutMs: RUN_SETUP_PATCH_TIMEOUT_MS,
        });
        setSelectedRun((prev) => {
          if (!prev || prev.id !== rid) return prev;
          return {
            ...prev,
            prompt_setup_saved: Boolean(updated?.prompt_setup_saved),
            prompt_setup_text: textSnapshot,
          };
        });
        refreshRunMetricsOnly(rid);
      } catch (e) {
        setSelectedRun((prev) => {
          if (!prev || prev.id !== rid) return prev;
          return {
            ...prev,
            prompt_setup_text: prevPromptText,
            prompt_setup_saved: prevPromptSaved,
          };
        });
        snapshotWriteRunSetupPrefs(rid, runSetupPrefsRollbackPartial(prefsBefore, prevRunRef));
        setRunSetupPrefsRev((x) => x + 1);
        setUiError(setError, e);
      }
    })();
  };

  const saveSignatureSetup = () => {
    if (!selectedRun?.id) return;
    const rid = selectedRun.id;
    const htmlSnapshot = signatureFormHtml;
    const prefsBefore = snapshotReadRunSetupPrefs(rid);
    const prevHtml = selectedRun?.sender_signature_html;
    const prevConfigured = selectedRun?.sender_signature_configured;
    const prevRunRef = selectedRun;

    setError("");
    snapshotWriteRunSetupPrefs(rid, {
      sender_signature_configured: runSignatureHasMeaningfulContent(htmlSnapshot),
      signature_html: htmlSnapshot,
    });
    setRunSetupPrefsRev((x) => x + 1);
    setSelectedRun((prev) => {
      if (!prev || prev.id !== rid) return prev;
      return {
        ...prev,
        sender_signature_html: htmlSnapshot,
        sender_signature_configured: runSignatureHasMeaningfulContent(htmlSnapshot),
      };
    });
    setSignatureSetupOpen(false);
    setSignatureSetupSaving(false);

    void (async () => {
      try {
        const updated = await api(`/runs/${rid}/signature`, {
          method: "PATCH",
          body: { signature_html: htmlSnapshot },
          timeoutMs: RUN_SETUP_PATCH_TIMEOUT_MS,
        });
        setSelectedRun((prev) => {
          if (!prev || prev.id !== rid) return prev;
          return {
            ...prev,
            sender_signature_configured: Boolean(updated?.sender_signature_configured),
          };
        });
        refreshRunMetricsOnly(rid);
      } catch (e) {
        setSelectedRun((prev) => {
          if (!prev || prev.id !== rid) return prev;
          return {
            ...prev,
            sender_signature_html: prevHtml,
            sender_signature_configured: prevConfigured,
          };
        });
        snapshotWriteRunSetupPrefs(rid, runSetupPrefsRollbackPartial(prefsBefore, prevRunRef));
        setRunSetupPrefsRev((x) => x + 1);
        setUiError(setError, e);
      }
    })();
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
        !q ||
          [d.company, d.to_email, d.subject, d.body ?? d.body_preview].some((v) =>
            (v || "").toLowerCase().includes(q),
          )
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

  /** True when email looks usable for sending — must match `contactReviewTabBucket` (contains `@`). */
  const contactHasEmail = (c) => {
    const em = String(c?.email ?? "").trim().toLowerCase();
    return em.includes("@");
  };

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
      if (d.contact_id == null) continue;
      const k = Number(d.contact_id);
      if (Number.isFinite(k)) m.set(k, d);
    }
    return m;
  }, [drafts]);

  /** Approved but no draft row yet — background LLM after Approve on contact. */
  const contactsAwaitingOutboundDraftPlaceholder = useMemo(() => {
    if (!Array.isArray(contacts) || !Array.isArray(drafts)) return [];
    const reviewableDraftContactIds = new Set(
      drafts
        .filter((d) => !isOutboundDraftClosedForReview(d))
        .map((d) => d.contact_id)
        .filter((id) => id != null)
        .map((id) => Number(id)),
    );
    return contacts.filter((c) => {
      const cid = Number(c.id);
      if (!Number.isFinite(cid) || !pendingOutboundDraftByContactId[cid]) return false;
      if (!["approved", "edited"].includes(c.review_status)) return false;
      if (c.status !== "valid") return false;
      if (!String(c.email || "").trim()) return false;
      if (reviewableDraftContactIds.has(Number(c.id))) return false;
      return true;
    });
  }, [contacts, drafts, pendingOutboundDraftByContactId]);

  const approvedContactsReachable = contactsVisible.filter(
    (c) =>
      ["approved", "edited"].includes(c.review_status) &&
      !contactHasBadEmailHealth(c) &&
      contactHasEmail(c),
  ).length;
  const approvedDrafts = draftsVisibleInReview.filter((d) =>
    ["approved", "edited"].includes(d.review_status),
  ).length;
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

  /**
   * Read inner-tab counts from localStorage inside the memos below (do not cache a single
   * snapshotReadInnerTabCounts() in useMemo([selectedRun.id]) only): that pattern never
   * re-reads after snapshotMergeWriteInnerTabs updates storage for the same run, so tab badges
   * stayed stale until the run changed.
   */
  const displayContactReviewCounts = useMemo(() => {
    const live = liveContactReviewCounts;
    if (contactsListReadyRunId === Number(selectedRun?.id)) return live;
    const snap = selectedRun?.id ? snapshotReadInnerTabCounts(selectedRun.id)?.contacts : null;
    return mergeContactReviewSnap(snap, live);
  }, [liveContactReviewCounts, contactsListReadyRunId, selectedRun?.id]);

  const displayDraftReviewCounts = useMemo(() => {
    const live = liveDraftReviewCounts;
    if (draftsListReadyRunId === Number(selectedRun?.id)) return live;
    const rid = selectedRun?.id;
    const snap = rid ? snapshotReadInnerTabCounts(rid)?.drafts : null;
    const merged = mergeDraftReviewSnap(snap, live);
    /**
     * While GET /email-drafts/run has not hydrated `drafts`, live counts are 0 and merge falls back to
     * inner-tab snapshot — which can say Approved (0) even though panel lite preview rows still show
     * approved/edited. Align tab badges with the same preview list used for cached cards.
     */
    if (rid != null && (!Array.isArray(drafts) || drafts.length === 0)) {
      const previewList = draftsForRunPanelLitePreview(snapshotReadRunPanelLite(rid)?.draftsPreview);
      if (previewList.length > 0) {
        const pendingReview = previewList.filter(
          (d) => d.review_status === "pending" || d.review_status === "rejected",
        ).length;
        const approved = previewList.filter((d) =>
          ["approved", "edited"].includes(d.review_status),
        ).length;
        return { pendingReview, approved };
      }
    }
    return merged;
  }, [liveDraftReviewCounts, draftsListReadyRunId, selectedRun?.id, drafts]);

  /** Pending count for hero line — from tab strip counts, not from filtered `contacts` (avoids 0 when another tab is selected). */
  const pendingContactsLeft = displayContactReviewCounts.pending;
  const totalContactsReviewRollup = useMemo(() => {
    const c = displayContactReviewCounts;
    return (
      c.pending +
      c.approved +
      c.rejected +
      c.bounced +
      c.dead_mailbox +
      c.no_email
    );
  }, [displayContactReviewCounts]);

  /**
   * Full GET /contacts/run not applied yet. Tab counts can still come from snapshot — misleading if we
   * block the whole table; `contactsVisible` falls back to panel-lite preview rows when `contacts` is empty.
   */
  const contactsReviewListLoading =
    mainNav === "contacts" &&
    selectedRun?.id != null &&
    contactsListReadyRunId !== Number(selectedRun.id) &&
    contactsListFailedRunId !== Number(selectedRun.id) &&
    contactsVisible.length === 0;

  const contactsActionsReady = contactsListReadyRunId === Number(selectedRun?.id);

  /** Tab strip was gated on contactsVisible.length only, so snapshot counts could not show the row until fetch finished. */
  const showContactReviewTabStrip =
    contactsVisible.length > 0 || totalContactsReviewRollup > 0 || contactsReviewListLoading;

  const draftsReviewHydrated =
    mainNav !== "drafts" ||
    draftsListReadyRunId === Number(selectedRun?.id) ||
    draftsListFailedRunId === Number(selectedRun?.id);
  const reviewDraftsSnapModeVal = useMemo(() => {
    const draftsSnap = selectedRun?.id ? snapshotReadInnerTabCounts(selectedRun.id)?.drafts : null;
    return reviewDraftsSnapMode(draftsSnap);
  }, [draftsListReadyRunId, draftsListFailedRunId, selectedRun?.id]);

  const runPanelLiteHuman = useMemo(
    () => (selectedRun?.id ? snapshotReadRunPanelLite(selectedRun.id) : null),
    [selectedRun?.id, runDetailsHydratedId, contactsListReadyRunId, draftsListReadyRunId, draftsListFailedRunId],
  );

  const draftsPanelLiteFiltered = useMemo(() => {
    const list = draftsForRunPanelLitePreview(runPanelLiteHuman?.draftsPreview);
    if (!list.length) return [];
    if (draftReviewTab === "pending") {
      return list.filter((d) => d.review_status === "pending" || d.review_status === "rejected");
    }
    return list.filter((d) => ["approved", "edited"].includes(d.review_status));
  }, [runPanelLiteHuman?.draftsPreview, draftReviewTab]);

  useEffect(() => {
    if (!selectedRun?.id || contactsListReadyRunId !== Number(selectedRun.id)) return;
    snapshotMergeWriteInnerTabs(selectedRun.id, {
      contacts: liveContactReviewCounts,
    });
  }, [selectedRun?.id, contactsListReadyRunId, liveContactReviewCounts]);

  useEffect(() => {
    if (!selectedRun?.id || draftsListReadyRunId !== Number(selectedRun.id)) return;
    snapshotMergeWriteInnerTabs(selectedRun.id, {
      drafts: liveDraftReviewCounts,
    });
  }, [selectedRun?.id, draftsListReadyRunId, liveDraftReviewCounts]);

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

  const companiesListFull = companiesPanel?.companies ?? [];
  const companiesLoadedCount = companiesListFull.length;
  const companiesTotalRaw = Number(companiesPanel?.companies_total);
  const companiesTotalFromField =
    Number.isFinite(companiesTotalRaw) && companiesTotalRaw >= 0
      ? companiesTotalRaw
      : companiesLoadedCount;
  const companiesTotalForUi = Math.max(companiesTotalFromField, companiesLoadedCount);
  const maxPageFromLoaded = Math.max(1, Math.ceil(companiesLoadedCount / WORKSPACE_TABLE_PAGE_SIZE) || 1);
  const maxPageFromTotal = Math.max(1, Math.ceil(companiesTotalForUi / WORKSPACE_TABLE_PAGE_SIZE) || 1);
  const companiesPageCount = Math.min(maxPageFromLoaded, maxPageFromTotal);
  const companiesRows = useMemo(() => {
    const start = (companiesPage - 1) * WORKSPACE_TABLE_PAGE_SIZE;
    return companiesListFull.slice(start, start + WORKSPACE_TABLE_PAGE_SIZE);
  }, [companiesListFull, companiesPage]);
  const companiesRangeStart =
    companiesLoadedCount === 0 ? 0 : (companiesPage - 1) * WORKSPACE_TABLE_PAGE_SIZE + 1;
  const companiesRangeEnd = Math.min(companiesPage * WORKSPACE_TABLE_PAGE_SIZE, companiesLoadedCount);
  const companiesListTruncated =
    companiesLoadedCount === COMPANIES_FETCH_MAX && companiesTotalForUi > companiesLoadedCount;

  const contactsReviewPageCount = Math.max(
    1,
    Math.ceil(contactReviewTabGroups.length / WORKSPACE_TABLE_PAGE_SIZE),
  );

  const contactReviewGroupsPage = useMemo(() => {
    const start = (contactsReviewPage - 1) * WORKSPACE_TABLE_PAGE_SIZE;
    return contactReviewTabGroups.slice(start, start + WORKSPACE_TABLE_PAGE_SIZE);
  }, [contactReviewTabGroups, contactsReviewPage]);

  useEffect(() => {
    setContactsReviewPage((p) => Math.min(Math.max(1, p), contactsReviewPageCount));
  }, [contactsReviewPageCount, contactReviewTabGroups]);

  useEffect(() => {
    setCompaniesPage((p) => Math.min(Math.max(1, p), companiesPageCount));
  }, [companiesPageCount]);

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
    if (typeof selectedRun?.prompt_setup_text === "string" && selectedRun.prompt_setup_text.trim().length > 0) {
      return true;
    }
    return false;
  }, [
    selectedRun?.id,
    selectedRun?.prompt_setup_saved,
    selectedRun?.prompt_setup_text,
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
      return null;
    }
    return null;
  }, [selectedRun?.id, workspace?.display_phase]);

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
              {!hasEmail ? <Badge variant="destructive">No email</Badge> : null}
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
                disabled={contactApproveBusyId === contact.id || !contactsActionsReady}
                title={!contactsActionsReady ? "Loading full contact list from server…" : undefined}
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
                  <Button
                    size="sm"
                    disabled={contactApproveBusyId === contact.id || !contactsActionsReady}
                    aria-busy={contactApproveBusyId === contact.id}
                    title={!contactsActionsReady ? "Loading full contact list from server…" : undefined}
                    onClick={() => void approveContact(contact.id)}
                  >
                    {contactApproveBusyId === contact.id ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                    ) : null}
                    Approve
                  </Button>
                ) : null}
                {!isDeadMailbox ? (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={contactApproveBusyId === contact.id || !contactsActionsReady}
                    title={!contactsActionsReady ? "Loading full contact list from server…" : undefined}
                    onClick={() => reviewContact(contact.id, "rejected")}
                  >
                    Reject
                  </Button>
                ) : null}
              </>
            ) : null}
            {!isPending && !isRejected && !isDeadMailbox ? (
              <Button
                size="sm"
                variant="outline"
                disabled={contactApproveBusyId === contact.id || !contactsActionsReady}
                title={!contactsActionsReady ? "Loading full contact list from server…" : undefined}
                onClick={() => reviewContact(contact.id, "rejected")}
              >
                Reject
              </Button>
            ) : null}
            {isRejected && hasEmail ? (
              <Button
                size="sm"
                disabled={contactApproveBusyId === contact.id || !contactsActionsReady}
                aria-busy={contactApproveBusyId === contact.id}
                title={!contactsActionsReady ? "Loading full contact list from server…" : undefined}
                onClick={() => void approveContact(contact.id)}
              >
                {contactApproveBusyId === contact.id ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                ) : null}
                Approve
              </Button>
            ) : null}
            {!isPending &&
            !isRejected &&
            ["approved", "edited"].includes(rs) &&
            !draftByContactId.has(Number(contact.id)) &&
            createDraftContactId !== contact.id ? (
              <Button
                size="sm"
                variant="outline"
                disabled={!((contact.email || "").trim()) || !contactsActionsReady}
                title={
                  !contactsActionsReady
                    ? "Loading full contact list from server…"
                    : !(contact.email || "").trim()
                      ? "Add an email to this contact first"
                      : undefined
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
                disabled={contactEditSavingId === contact.id}
                aria-busy={contactEditSavingId === contact.id}
                onClick={async () => {
                  setContactEditSavingId(contact.id);
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
                    if (selectedRun) refreshRunMetricsOnly(selectedRun.id);
                  } catch (e) {
                    setUiError(setError, e);
                  } finally {
                    setContactEditSavingId((id) => (id === contact.id ? null : id));
                  }
                }}
              >
                {contactEditSavingId === contact.id ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                ) : null}
                Save
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={contactEditSavingId === contact.id}
                onClick={() => setEditingContact(null)}
              >
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
    const companyAiFit = group[0]?.company_ai_fit_status;
    return (
      <Card key={cardKey} className={cardClass}>
        <CardContent className="p-5">
          <div className="mb-4 border-b border-border pb-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-lg font-semibold">{group[0].company || "Unnamed company"}</span>
              {companyAiFit === "correct" ? (
                <Badge
                  variant="outline"
                  className="border-emerald-300 bg-emerald-100 font-normal text-emerald-950 dark:border-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-100"
                >
                  AI OK
                </Badge>
              ) : companyAiFit === "incorrect" ? (
                <Badge
                  variant="outline"
                  className="border-red-300 bg-red-100 font-normal text-red-950 dark:border-red-800 dark:bg-red-950/45 dark:text-red-100"
                >
                  AI Incorrect
                </Badge>
              ) : null}
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

  const renderGeneratingOutboundDraftPlaceholder = (contact) => (
    <Card key={`outreach-gen-${contact.id}`} className="border-2 border-dashed border-muted-foreground/35">
      <CardContent className="p-5">
        <div className="flex flex-col gap-2">
          <div className="break-words text-lg font-semibold">{contact.company || "—"}</div>
          <div className="text-sm text-muted-foreground">
            {contact.name || "—"} · {contact.email || "—"}
          </div>
          <div
            className="flex items-center gap-2 text-sm text-muted-foreground"
            role="status"
            aria-live="polite"
          >
            <Loader2 className="h-4 w-4 shrink-0 animate-spin" aria-hidden />
            Generating email…
          </div>
        </div>
      </CardContent>
    </Card>
  );

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
    const contactPers =
      draftContact?.personalization_json && typeof draftContact.personalization_json === "object"
        ? draftContact.personalization_json
        : null;
    const genMeta =
      draft.generation_meta_json && typeof draft.generation_meta_json === "object"
        ? draft.generation_meta_json
        : null;
    const promptUsedForDraft =
      (typeof draft.prompt_setup_text_used === "string" && draft.prompt_setup_text_used.trim()) ||
      (genMeta && typeof genMeta.prompt_setup_text_used === "string" && genMeta.prompt_setup_text_used.trim()) ||
      null;
    const genMetaDetailsJson =
      genMeta && typeof genMeta === "object"
        ? Object.fromEntries(Object.entries(genMeta).filter(([k]) => k !== "prompt_setup_text_used"))
        : null;
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
                          type="button"
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
                          type="button"
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
                      type="button"
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
            <div className="min-w-0 space-y-3 text-sm lg:col-span-2">
              <div>
                <span className="font-medium">To:</span> {draft.to_email || "No recipient"}
              </div>
              <div>
                <span className="font-medium">Subject:</span> {draft.subject}
              </div>
              {promptUsedForDraft ? (
                <DraftCollapsibleSection title="Prompt used for this email">
                  <div className="whitespace-pre-wrap break-words text-sm text-foreground">{promptUsedForDraft}</div>
                </DraftCollapsibleSection>
              ) : null}
              {contactPers &&
              (contactPers.why_this_company || contactPers.offer_fit || contactPers.role_angle) ? (
                <DraftCollapsibleSection title="Why this company" className="bg-muted/25">
                  <dl className="space-y-2 text-sm">
                    {contactPers.why_this_company ? (
                      <div>
                        <dt className="text-xs text-muted-foreground">Context</dt>
                        <dd className="whitespace-pre-wrap break-words">{contactPers.why_this_company}</dd>
                      </div>
                    ) : null}
                    {contactPers.offer_fit ? (
                      <div>
                        <dt className="text-xs text-muted-foreground">Offer fit</dt>
                        <dd className="whitespace-pre-wrap break-words">{contactPers.offer_fit}</dd>
                      </div>
                    ) : null}
                    {contactPers.role_angle ? (
                      <div>
                        <dt className="text-xs text-muted-foreground">Role angle</dt>
                        <dd className="whitespace-pre-wrap break-words">{contactPers.role_angle}</dd>
                      </div>
                    ) : null}
                  </dl>
                </DraftCollapsibleSection>
              ) : null}
              {genMeta ? (
                <div className="rounded-lg border border-border p-3">
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      Generation
                    </span>
                    {genMeta.validation_score != null && Number.isFinite(Number(genMeta.validation_score)) ? (
                      <span
                        className={cn(
                          "inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium tabular-nums",
                          validationScoreToneClass(genMeta.validation_score),
                        )}
                        title="Validation score (0–100)"
                      >
                        Score {Math.round(Number(genMeta.validation_score))}
                      </span>
                    ) : null}
                    {genMeta.style_mode ? (
                      <Badge variant="outline" className="font-normal">
                        {String(genMeta.style_mode)}
                      </Badge>
                    ) : null}
                    {genMeta.pipeline_source ? (
                      <Badge variant="secondary" className="font-normal">
                        {String(genMeta.pipeline_source)}
                      </Badge>
                    ) : null}
                    {genMeta.is_valid === false ? (
                      <Badge variant="destructive" className="font-normal">
                        Needs review
                      </Badge>
                    ) : null}
                  </div>
                  <details className="text-xs text-muted-foreground">
                    <summary className="cursor-pointer select-none text-foreground hover:underline">
                      Details (reasoning, issues)
                    </summary>
                    <pre className="mt-2 max-h-48 overflow-auto rounded-md bg-muted/50 p-2 text-[11px] leading-relaxed">
                      {JSON.stringify(genMetaDetailsJson, null, 2)}
                    </pre>
                  </details>
                </div>
              ) : null}
            </div>
          </div>
          {draft.error_message &&
          !isStaleOutboundDraftErrorMessage(draft.error_message) &&
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
            body={draft.body ?? draft.body_preview}
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

  /** Do not tie Activity spinner to routine GETs (run/contacts/drafts) — it only distracts; use inline placeholders. */
  const activityLogBusy =
    loading ||
    analyzerLoading ||
    continueCompanyFindLoading ||
    Object.keys(restartsInFlight).length > 0;
  const showActivityLogPanel = activityLogPinnedOpen;

  return (
    <div className="min-h-screen bg-background text-foreground">
      {showActivityLogPanel ? (
        <div
          className="fixed top-4 right-4 z-[100] flex max-h-[min(840px,110vh)] w-[min(100vw-2rem,22rem)] flex-col overflow-hidden rounded-2xl border-2 border-border bg-card shadow-lg"
          role="log"
          aria-live="polite"
          aria-label="Activity log"
        >
          <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border bg-muted/40 px-3 py-2">
            <div className="flex min-w-0 flex-1 items-center gap-2">
              {activityLogBusy ? (
                <Loader2 className="h-4 w-4 shrink-0 animate-spin text-primary" aria-hidden />
              ) : null}
              <span className="min-w-0 break-words text-sm font-semibold">Activity</span>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-8 px-2 text-xs"
                onClick={() => {
                  setActivityLogLines([]);
                  setActivityLogPinnedOpen(false);
                }}
              >
                Clear
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-8 w-8 shrink-0"
                aria-label="Close activity log"
                onClick={() => setActivityLogPinnedOpen(false)}
              >
                <X className="h-4 w-4" aria-hidden />
              </Button>
            </div>
          </div>
          <ScrollArea className="min-h-0 min-w-0 flex-1 overflow-x-auto">
            <ol className="list-none space-y-1.5 p-3 font-mono text-[11px] leading-relaxed text-foreground [overflow-wrap:anywhere]">
              {activityLogLines.map((line) => (
                <li key={line.id} className="max-w-full whitespace-pre-wrap break-words">
                  <span className="tabular-nums text-muted-foreground">
                    {formatDateTimeYmdHms(line.t)}
                  </span>{" "}
                  {line.text}
                </li>
              ))}
              <div ref={activityLogEndRef} className="h-0 w-full" aria-hidden />
            </ol>
          </ScrollArea>
        </div>
      ) : null}
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
              <Button
                type="button"
                variant="outline"
                className="h-10 w-10 shrink-0 p-0"
                aria-label={showActivityLogPanel ? "Hide activity log" : "Show activity log"}
                aria-pressed={showActivityLogPanel}
                title="Activity log"
                onClick={() => setActivityLogPinnedOpen((p) => !p)}
              >
                <Notebook className="h-4 w-4" aria-hidden />
              </Button>
            </div>
          </div>

          {Object.keys(restartsInFlight).length > 0 ? (
            <div
              role="status"
              className="flex items-start gap-3 rounded-2xl border-2 border-border bg-muted/30 px-4 py-3 text-sm"
            >
              <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-primary" aria-hidden />
              <p className="text-muted-foreground">
                <span className="font-medium text-foreground">Continue outreach in background</span>
                {": "}
                {Object.entries(restartsInFlight)
                  .map(([, x]) => x.name)
                  .join(" · ")}
                {" — "}
                you can switch runs; only these runs have Continue outreach disabled until finished.
              </p>
            </div>
          ) : null}

          {runProjectMismatch && selectedProject && selectedProject.is_archived ? (
            <div
              role="status"
              className="flex items-start gap-3 rounded-2xl border-2 border-border bg-muted/30 px-4 py-3 text-sm"
            >
              <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
              <p className="text-muted-foreground">
                This run belongs to another project. Restore this project from the archive, then use{" "}
                <span className="font-medium text-foreground">Move run to this project</span> in an active project.
              </p>
            </div>
          ) : null}

          {runProjectMismatch && selectedProject && !selectedProject.is_archived ? (
            <div
              role="status"
              className="flex flex-col gap-3 rounded-2xl border-2 border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="flex items-start gap-3">
                <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-700 dark:text-amber-400" aria-hidden />
                <p className="text-muted-foreground">
                  <span className="font-medium text-foreground">This run is stored under another project</span>
                  {runOtherProjectLabel ? (
                    <>
                      {" "}
                      (<span className="text-foreground">{runOtherProjectLabel}</span>)
                    </>
                  ) : null}
                  . Move it to <span className="font-medium text-foreground">{selectedProject.name}</span> so it
                  appears in the sidebar list.
                </p>
              </div>
              <Button
                type="button"
                variant="secondary"
                className="shrink-0 border-amber-600/30 bg-background hover:bg-amber-500/15"
                disabled={runProjectMoveInFlight}
                onClick={() => void moveRunToCurrentProject()}
              >
                {runProjectMoveInFlight ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                    Moving…
                  </>
                ) : (
                  "Move run to this project"
                )}
              </Button>
            </div>
          ) : null}

          <div className="flex flex-col gap-3 lg:flex-row lg:items-stretch">
            <div className="flex min-w-0 flex-1 flex-col gap-3 rounded-2xl border-2 border-border bg-card p-4 md:flex-row md:items-center md:justify-between">
              <div className="space-y-2">
                <div className="text-lg font-medium leading-snug md:text-xl">
                  <span className="text-muted-foreground font-normal">Project</span>{" "}
                  <span>{selectedProject?.name ?? "—"}</span>
                </div>
                <div className="text-lg font-medium leading-snug md:text-xl">
                  <span className="text-muted-foreground font-normal">Run</span>{" "}
                  <span>
                    {selectedRun
                      ? selectedRun.name?.trim() || `Run #${selectedRun.id}`
                      : "Select a run"}
                  </span>
                </div>
                <div className="space-y-1 pt-1 text-sm">
                  <div>
                    <span className="text-muted-foreground">Status</span>{" "}
                    <span className="font-medium">{workspace?.display_phase ?? "—"}</span>
                  </div>
                  <div className="text-foreground/90">
                    <span className="text-muted-foreground">LLMs</span>{" "}
                    <span className="font-medium">{integrationInformer.llmPart}</span>
                    <span className="px-1.5 text-muted-foreground">•</span>
                    <span className="text-muted-foreground">CDN</span>{" "}
                    <span className="font-medium">{integrationInformer.cdnPart}</span>
                    <span className="px-1.5 text-muted-foreground">•</span>
                    <span className="text-muted-foreground">Outreach</span>{" "}
                    <span className="font-medium">{integrationInformer.outreachPart}</span>
                  </div>
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
                  disabled={!selectedProject || (runsList.length === 0 && !selectedRun)}
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
                  <li>
                    Replies:{" "}
                    <span className="font-medium">{totalPerformance?.replies ?? 0}</span>
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
                                <div className="mt-0.5 text-muted-foreground">Other project</div>
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
                    <RunSetupHourlySendsChart counts={workspace.hourly_sends_24h} />
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
                  <Fragment key={item.value}>
                    {item.value === "assets" ? (
                      <div
                        className="h-0 w-full shrink-0 basis-full"
                        aria-hidden
                      />
                    ) : null}
                    <Button
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
                  </Fragment>
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
                            <div className="space-y-0.5 text-xs text-muted-foreground">
                              <div>
                                Companies {r.companies_count} · Contacts {r.contacts_count}
                              </div>
                              <div>
                                Sent {r.emails_sent} · Replies {r.replies} · Threads{" "}
                                {r.active_threads}
                              </div>
                            </div>
                          </div>
                          <div className="flex max-w-full flex-nowrap items-center gap-2 overflow-x-auto">
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              className="shrink-0 whitespace-nowrap"
                              onClick={() => openRunEditDialog(r)}
                            >
                              Open
                            </Button>
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              className="shrink-0 whitespace-nowrap"
                              disabled={r.display_phase === "Closed" || Boolean(restartsInFlight[r.id])}
                              onClick={() => openRestartDialog(r)}
                            >
                              Continue outreach
                            </Button>
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              className="shrink-0 whitespace-nowrap"
                              title="Switch to this run"
                              disabled={
                                selectedRun?.id === r.id
                              }
                              onClick={() => void openRunById(r.id, r)}
                            >
                              <RefreshCw className="mr-1 h-4 w-4 shrink-0" aria-hidden />
                              Switch
                            </Button>
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              className="shrink-0 whitespace-nowrap"
                              disabled={r.display_phase === "Closed"}
                              onClick={() => {
                                refreshRunMetricsOnly(r.id);
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
                        List from the collect step. Contact search status is stored on each company row after find /
                        retry runs (this screen does not load the contacts table).
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
                      {companyBulkFindProgress &&
                      (continueCompanyFindLoading || companyRetryAllLoading || Object.keys(companyRetryLoading).length > 0) ? (
                        <div
                          role="status"
                          className="flex items-start gap-2 rounded-lg border border-primary/25 bg-primary/5 px-3 py-2 text-sm text-foreground"
                        >
                          <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-primary" aria-hidden />
                          <span>
                            Searching{" "}
                            <span className="font-medium">«{companyBulkFindProgress.name}»</span>
                            {" — "}
                            {companyBulkFindProgress.engine === "apollo" ? "Apollo" : "LLM"}
                          </span>
                        </div>
                      ) : null}
                    </div>
                    <div className="flex shrink-0 flex-col gap-2 self-start sm:mt-0.5 sm:items-end">
                      {companiesPanel?.companies?.some((c) => c.contact_status === "pending") &&
                      selectedRun &&
                      !selectedRun.closed_at &&
                      !restartsInFlight[selectedRun.id] ? (
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
                      {companiesPanel?.companies?.some((c) => {
                        const idx = normalizeCompanyCollectIndex(c);
                        if (idx == null) return false;
                        if (c.ai_fit_status === "incorrect") return false;
                        return (
                          (c.contact_status === "none" ||
                            c.contact_status === "no_email" ||
                            c.contact_status === "unknown") &&
                          !companyFindUnavailable[idx]
                        );
                      }) &&
                      selectedRun &&
                      !selectedRun.closed_at &&
                      !restartsInFlight[selectedRun.id] ? (
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
                      {(companiesPanel?.companies?.length ?? 0) > 0 &&
                      selectedRun &&
                      !selectedRun.closed_at &&
                      !restartsInFlight[selectedRun.id] ? (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          title="Label companies that still need analysis (LLM vs your campaign brief). Already analyzed rows are skipped."
                          disabled={
                            companiesLoading ||
                            continueCompanyFindLoading ||
                            companyRetryAllLoading ||
                            companyAiFitBatchLoading ||
                            Object.keys(companyRetryLoading).length > 0
                          }
                          onClick={() => void runCompaniesAiFitPending(selectedRun.id)}
                        >
                          {companyAiFitBatchLoading ? (
                            <>
                              <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                              AI analysis…
                            </>
                          ) : (
                            "AI analysis"
                          )}
                        </Button>
                      ) : null}
                    </div>
                  </div>
                </CardHeader>
                <CardContent>
                  {!selectedRun ? (
                    <p className="text-sm text-muted-foreground">Select a run first.</p>
                  ) : companiesListFailedRunId === Number(selectedRun.id) ? (
                    <div className="flex flex-col gap-3 rounded-xl border border-destructive/35 bg-destructive/5 p-4 text-sm">
                      <p className="text-muted-foreground">
                        Could not load the companies table (network or server error). Run setup numbers may still show
                        from the last successful metrics refresh.
                      </p>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="w-fit"
                        onClick={() => setCompaniesRefreshNonce((n) => n + 1)}
                      >
                        Retry
                      </Button>
                    </div>
                  ) : (companiesPanel?.companies?.length ?? 0) > 0 ? (
                    <div className="space-y-4">
                      <details className="rounded-lg border border-border/70 bg-muted/25 px-3 py-2 text-xs text-muted-foreground">
                        <summary className="cursor-pointer select-none font-medium text-muted-foreground outline-none hover:text-foreground">
                          What status labels mean
                        </summary>
                        <div className="mt-3 flex flex-col gap-3">
                          <span className="inline-flex flex-wrap items-start gap-1.5">
                            <Badge
                              className="inline-flex shrink-0 items-center gap-1 border border-red-950 bg-red-950/95 font-normal text-red-50 dark:border-red-800 dark:bg-red-950/90"
                            >
                              <CircleAlert className="h-3 w-3 shrink-0" aria-hidden />
                              LLM error
                            </Badge>
                            <span>
                              Company/website failed validation (unreachable or invalid URL). No contact search — use a
                              real brand in a new collect round.
                            </span>
                          </span>
                          <span className="inline-flex flex-wrap items-start gap-1.5">
                            <Badge variant="default" className="shrink-0 whitespace-nowrap font-normal">
                              Contacts found
                            </Badge>
                            <span>
                              At least one matching person has a usable email in find-contacts output. If{" "}
                              <strong>all</strong> contacts for that company become bounced or dead mailbox, the row shows{" "}
                              <strong>Not available</strong> instead.
                            </span>
                          </span>
                          <span className="inline-flex flex-wrap items-start gap-1.5">
                            <Badge variant="secondary" className="font-normal">
                              Not found
                            </Badge>
                            <span>Find-contacts finished; no matching row for this company.</span>
                          </span>
                          <span className="inline-flex flex-wrap items-start gap-1.5">
                            <Badge variant="destructive" className="font-normal">
                              Not available
                            </Badge>
                            <span>
                              <strong>Not available</strong> here means no <strong>usable email</strong> for this company
                              in find-contacts output: Apollo may return people but often without an email in the API
                              response (plan/tier), or the site had no domain for contact search. Collecting a company
                              (org search) and finding a person with an email are separate steps. Use{" "}
                              <strong>Retry</strong> if the row is still open, or <strong>Remove</strong> if the company
                              is off-target.
                            </span>
                          </span>
                          <span className="inline-flex flex-wrap items-start gap-1.5">
                            <Badge variant="outline" className="border-amber-500/50 font-normal text-amber-950 dark:text-amber-100">
                              Not searched yet
                            </Badge>
                            <span>Find-contacts still running or not completed — more results may arrive.</span>
                          </span>
                          <span className="inline-flex flex-wrap items-start gap-1.5">
                            <Badge variant="destructive" className="font-normal">
                              Incorrect
                            </Badge>
                            <span className="inline-flex flex-wrap gap-1">
                              <span className="font-medium text-foreground">Campaign fit</span> (AI analysis): one
                              LLM pass per company vs your campaign brief.{" "}
                              <strong>OK</strong> = plausible target; <strong>Incorrect</strong> = off-target. Analyzed
                              rows are stored and are not analyzed again when you use <strong>AI analysis</strong>{" "}
                              (only rows without a label yet).
                            </span>
                          </span>
                        </div>
                      </details>
                      <div className="overflow-x-auto rounded-xl border-2 border-border pb-4">
                        <table className="w-full min-w-[760px] text-left text-sm">
                          <thead className="border-b border-border bg-muted/40 text-xs font-semibold text-muted-foreground">
                            <tr>
                              <th className="px-3 py-2">Company</th>
                              <th className="px-3 py-2">Website</th>
                              <th className="whitespace-nowrap px-3 py-2 align-bottom">Contact search</th>
                              <th className="whitespace-nowrap px-3 py-2 align-bottom">Campaign fit</th>
                              <th className="whitespace-nowrap px-3 py-2 align-bottom">Actions</th>
                            </tr>
                          </thead>
                          <tbody>
                            {companiesRows.map((row) => {
                              const st = row.contact_status;
                              const ci = normalizeCompanyCollectIndex(row);
                              const unavailable = ci != null && !!companyFindUnavailable[ci];
                              const onlyBouncedOrDead =
                                st === "found" && companyHasOnlyBouncedOrDeadContacts(contacts, row);
                              const badge =
                                st === "llm_error" ? (
                                  <Badge
                                    className="inline-flex items-center gap-1 border border-red-950 bg-red-950/95 font-normal text-red-50 dark:border-red-800 dark:bg-red-950/90"
                                    title="Invalid or unreachable website — marked as LLM hallucination"
                                  >
                                    <CircleAlert className="h-3 w-3 shrink-0" aria-hidden />
                                    LLM error
                                  </Badge>
                                ) : st === "unknown" ? (
                                  <Badge
                                    variant="outline"
                                    className="border-muted-foreground/40 font-normal text-muted-foreground"
                                    title="Status not synced yet — run find/retry, or open Contacts after the next workflow step"
                                  >
                                    Not synced
                                  </Badge>
                                ) : onlyBouncedOrDead ? (
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
                                ) : st === "pending" ? (
                                  <Badge
                                    variant="outline"
                                    className="border-amber-500/50 font-normal text-amber-950 dark:text-amber-100"
                                  >
                                    Not searched yet
                                  </Badge>
                                ) : (
                                  <Badge
                                    variant="outline"
                                    className="border-amber-500/50 font-normal text-amber-950 dark:text-amber-100"
                                  >
                                    Not searched yet
                                  </Badge>
                                );
                              const canRetryCompanyFind =
                                (st === "none" || st === "no_email" || st === "unknown") &&
                                st !== "llm_error" &&
                                row.ai_fit_status !== "incorrect" &&
                                !unavailable &&
                                selectedRun &&
                                !selectedRun.closed_at &&
                                !restartsInFlight[selectedRun.id];
                              const retryingRow = ci != null && !!companyRetryLoading[ci];
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
                                  <td className="align-middle whitespace-nowrap px-3 py-2.5">
                                    <div className="inline-flex min-w-max max-w-none flex-nowrap items-center gap-2">
                                      <span className="inline-flex shrink-0 whitespace-nowrap">{badge}</span>
                                      {canRetryCompanyFind ? (
                                        <Button
                                          type="button"
                                          size="sm"
                                          variant="outline"
                                          className="h-6 shrink-0 whitespace-nowrap rounded-full px-2.5 text-xs font-medium"
                                          disabled={retryingRow}
                                          onClick={() => void retryCompanyFind(selectedRun.id, ci ?? row.collect_index)}
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
                                  <td className="max-w-[14rem] px-3 py-2 align-middle text-xs">
                                    {row.ai_fit_status === "incorrect" ? (
                                      <Badge
                                        variant="destructive"
                                        className="font-normal"
                                        title={
                                          typeof row.ai_fit_reason === "string" && row.ai_fit_reason.trim()
                                            ? row.ai_fit_reason.trim()
                                            : "Does not match your campaign brief"
                                        }
                                      >
                                        Incorrect
                                      </Badge>
                                    ) : row.ai_fit_status === "correct" ? (
                                      <Badge
                                        variant="outline"
                                        className="border-emerald-600/40 font-normal text-emerald-950 dark:text-emerald-100"
                                        title={
                                          typeof row.ai_fit_reason === "string" && row.ai_fit_reason.trim()
                                            ? row.ai_fit_reason.trim()
                                            : "Plausible fit for this campaign"
                                        }
                                      >
                                        OK
                                      </Badge>
                                    ) : (
                                      <span className="text-muted-foreground">—</span>
                                    )}
                                  </td>
                                  <td className="whitespace-nowrap px-3 py-2 align-middle">
                                    {selectedRun &&
                                    !selectedRun.closed_at &&
                                    !restartsInFlight[selectedRun.id] &&
                                    ci != null ? (
                                      <Button
                                        type="button"
                                        size="sm"
                                        variant="outline"
                                        className="h-6 shrink-0 whitespace-nowrap rounded-full px-2.5 text-xs font-medium"
                                        disabled={removeCompanyInFlight}
                                        onClick={() =>
                                          setRemoveCompanyDialog({
                                            collectIndex: ci,
                                            name: String(row?.name ?? "—").trim() || "—",
                                          })
                                        }
                                      >
                                        Remove
                                      </Button>
                                    ) : (
                                      "—"
                                    )}
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                    {companiesTotalForUi > WORKSPACE_TABLE_PAGE_SIZE ? (
                        <div className="mt-4 w-full border-t border-border px-3 pt-4">
                          <div className="flex w-full flex-wrap items-center justify-center gap-x-4 gap-y-2 text-sm text-muted-foreground">
                            {companiesRangeStart > 0 && companiesRangeEnd > 0 ? (
                              <span className="text-center">
                                {companiesRangeStart}–{companiesRangeEnd} of {companiesTotalForUi}
                                {companiesListTruncated ? (
                                  <span className="text-foreground">
                                    {" "}
                                    (showing first {companiesLoadedCount} loaded)
                                  </span>
                                ) : null}
                              </span>
                            ) : null}
                            <div className="flex flex-wrap items-center justify-center gap-2">
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                disabled={companiesPage <= 1 || companiesLoading}
                                onClick={() => setCompaniesPage((p) => Math.max(1, p - 1))}
                              >
                                Previous
                              </Button>
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                disabled={companiesPage >= companiesPageCount || companiesLoading}
                                onClick={() => setCompaniesPage((p) => Math.min(companiesPageCount, p + 1))}
                              >
                                Next
                              </Button>
                            </div>
                          </div>
                        </div>
                      ) : companiesTotalForUi > 0 ? (
                        <p className="text-xs text-muted-foreground">
                          {companiesTotalForUi}{" "}
                          {companiesTotalForUi === 1 ? "company" : "companies"} total.
                        </p>
                      ) : null}
                      </div>
                    </div>
                  ) : companiesLoading && !companiesPanel ? (
                    <p className="text-sm text-muted-foreground">Loading companies...</p>
                  ) : companiesPanel &&
                    !companiesPanel.companies?.length &&
                    Number(companiesPanel.companies_total) === 0 &&
                    Number(workspace?.setup_summary?.companies_collected) > 0 ? (
                    <div className="space-y-2 text-sm text-muted-foreground">
                      <p>
                        Run setup reports{" "}
                        <span className="font-medium text-foreground">
                          {workspace.setup_summary.companies_collected}
                        </span>{" "}
                        companies in setup metrics, but the{" "}
                        <span className="font-medium text-foreground">run_companies</span> table is empty for this run.
                        Try Refresh metrics, reopen this run, or run the one-off legacy migration script if you upgraded
                        from an older DB.
                      </p>
                    </div>
                  ) : !companiesPanel?.companies?.length ? (
                    <p className="text-sm text-muted-foreground">
                      No companies stored for this run yet. They appear after search adds them (or restart the run).
                    </p>
                  ) : null}
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
                        <>
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            className="gap-1.5"
                            title="Reconnect Google — refresh OAuth token or fix client credentials in the running API."
                            onClick={() => openGmailSetup()}
                            disabled={!selectedRun}
                          >
                            {!gmailSendReady ? (
                              <CircleX className="h-4 w-4 shrink-0 text-red-600 dark:text-red-500" aria-hidden />
                            ) : (
                              <Mail className="h-4 w-4 shrink-0 opacity-70" aria-hidden />
                            )}
                            Connect Gmail
                          </Button>
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
                        </>
                      ) : null}
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="gap-1.5"
                        onClick={() => void openPromptSetup()}
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
                        onClick={() => void openSignatureSetup()}
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
                      {pendingContactsLeft} contacts left to review
                      {approvedContactsReachable > 0 ? (
                        <span className="text-muted-foreground">
                          {" "}
                          · {approvedContactsReachable} approved (reachable)
                        </span>
                      ) : null}
                    </div>

                    {pendingContactsLeft === 0 &&
                    totalContactsReviewRollup > 0 &&
                    contactsVisible.length > 0 &&
                    !search.trim() ? (
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

                    {showContactReviewTabStrip ? (
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

                        {!contactsActionsReady && contactsVisible.length > 0 ? (
                          <p className="text-xs text-muted-foreground" role="status">
                            Syncing full list from server — review actions stay off until the request finishes.
                          </p>
                        ) : null}

                        {contactsListFailedRunId === Number(selectedRun?.id) ? (
                          <div
                            className="flex flex-col items-center justify-center gap-4 rounded-2xl border-2 border-dashed border-destructive/40 bg-destructive/5 py-12 text-center text-sm"
                            role="alert"
                          >
                            <p className="max-w-md text-muted-foreground">
                              Could not load contacts (network or server error). Tab counts may still show cached
                              numbers from a previous session.
                            </p>
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              onClick={() => void refreshRunContactsOnly(selectedRun.id)}
                            >
                              Retry
                            </Button>
                          </div>
                        ) : contactsReviewListLoading ? (
                          <p className="rounded-2xl border border-dashed border-muted-foreground/30 py-8 text-center text-sm text-muted-foreground" role="status">
                            Loading contacts…
                          </p>
                        ) : contactReviewTabGroups.length === 0 ? (
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

                    {totalContactsReviewRollup === 0 &&
                    selectedRun?.id &&
                    contactsListReadyRunId === Number(selectedRun.id) ? (
                      <div className="text-center text-sm text-muted-foreground">
                        No contacts for this run yet.
                      </div>
                    ) : null}
                    {totalContactsReviewRollup > 0 &&
                    contactsVisible.length === 0 &&
                    selectedRun?.id &&
                    contactsListReadyRunId === Number(selectedRun.id) ? (
                      <div className="text-center text-sm text-muted-foreground">
                        No contacts in this tab — try another tab or clear search.
                      </div>
                    ) : null}
                    </>
                  </div>
                ) : (
                  <div className="space-y-6">
                    {draftsReviewHydrated ? (
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
                    {draftsListFailedRunId === Number(selectedRun?.id) ? (
                      <div
                        className="flex flex-col items-center justify-center gap-4 rounded-2xl border-2 border-dashed border-destructive/40 bg-destructive/5 py-12 text-center text-sm"
                        role="alert"
                      >
                        <p className="max-w-md text-muted-foreground">
                          Could not load email drafts (network, timeout, or server error). Cached counts in the
                          header may still reflect an earlier load.
                        </p>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          disabled={draftsSectionFetchBusy}
                          aria-busy={draftsSectionFetchBusy}
                          onClick={() => void refreshRunDraftsOnly(selectedRun.id)}
                        >
                          Retry
                        </Button>
                      </div>
                    ) : drafts.length > 0 || contactsAwaitingOutboundDraftPlaceholder.length > 0 ? (
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
                            {contactsAwaitingOutboundDraftPlaceholder.length > 0 ? (
                              <div className="space-y-3">
                                <div className="text-sm font-medium">
                                  Generating ({contactsAwaitingOutboundDraftPlaceholder.length})
                                </div>
                                <div className="grid gap-3">
                                  {contactsAwaitingOutboundDraftPlaceholder.map((c) =>
                                    renderGeneratingOutboundDraftPlaceholder(c),
                                  )}
                                </div>
                              </div>
                            ) : null}
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
                            {draftsPending.length === 0 &&
                            draftsRejectedList.length === 0 &&
                            contactsAwaitingOutboundDraftPlaceholder.length === 0 ? (
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
                            {draftsSectionFetchBusy ? (
                              <p className="text-xs text-muted-foreground" role="status">
                                Showing cached preview — loading full list…
                              </p>
                            ) : (
                              <div
                                className="flex flex-wrap items-center gap-2"
                                role="status"
                              >
                                <p className="text-xs text-amber-600 dark:text-amber-400">
                                  Couldn&apos;t load full drafts — cached preview only (timeouts or network).
                                </p>
                                <Button
                                  type="button"
                                  size="sm"
                                  variant="outline"
                                  disabled={draftsSectionFetchBusy}
                                  onClick={() => void refreshRunDraftsOnly(selectedRun.id)}
                                >
                                  Retry
                                </Button>
                              </div>
                            )}
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
                                  <div className="mt-2 flex flex-wrap gap-1.5">
                                    <Button
                                      type="button"
                                      size="sm"
                                      variant="outline"
                                      className="h-7 gap-1 text-xs"
                                      title="Loads full draft from the server if the list is not hydrated yet."
                                      onClick={() => openEditDraft(d)}
                                    >
                                      <Pencil className="h-3 w-3 shrink-0" aria-hidden />
                                      Edit
                                    </Button>
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
                runSignatureHtml={trackingStrip?.sender_signature_html ?? ""}
                contextJson={trackingStrip?.context_json ?? {}}
                activeTab={mainNavToTrackingTab(mainNav)}
                singleTabMode
                onActiveTabChange={(tab) => setMainNav(trackingTabToMainNav(tab))}
                onRunWorkspaceRefresh={() => refreshRunMetricsOnly(selectedRun.id)}
                onStaticAssetsSynced={onStaticAssetsSynced}
                onRunTraceLog={appendTrackingRunTraceLog}
                workspaceDisplayPhase={workspace?.display_phase ?? selectedRun?.display_phase}
                cdnR2UploadReady={setupIntegration?.cdn_r2_upload_ready === true}
                pollLiveEnabled={mainNav === "events" || mainNav === "threads"}
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
              Search description and geography drive company discovery; the same context feeds the master email for this
              run.
              {newRunBaseline
                ? " Keep the same run name and use Update run for notes, region, or brief. Change the run name to use Create run (new wave)."
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
                Region / Country / State <span className="text-destructive">*</span>
              </div>
              <Input
                value={newRunForm.segment}
                onChange={(e) => setNewRunForm((f) => ({ ...f, segment: e.target.value }))}
                placeholder="Geography for this search (e.g. United States — California)"
                aria-required
              />
            </div>
            <div>
              <div className="mb-1 text-xs text-muted-foreground">Professional profile</div>
              <NativeFilterSelect
                className="w-full"
                value={newRunForm.email_style_mode ?? "auto"}
                onValueChange={(v) => setNewRunForm((f) => ({ ...f, email_style_mode: v }))}
                options={PROFESSIONAL_PROFILE_OPTIONS}
              />
              <p className="mt-1 text-xs text-muted-foreground">
                Target decision-maker profile for outbound tone. <strong>Auto</strong> infers style from each
                contact&apos;s role when possible.
              </p>
            </div>
            <div>
              <div className="mb-1 text-xs text-muted-foreground">
                Outreach brief (search description) <span className="text-destructive">*</span>
              </div>
              <Textarea
                value={newRunForm.outreach_brief}
                onChange={(e) => setNewRunForm((f) => ({ ...f, outreach_brief: e.target.value }))}
                placeholder={
                  "Respondent's field of activity:\n\n" +
                  "Narrowly focused areas of activity:\n\n" +
                  "Reason for search (licensing, sales, partnership):\n\n" +
                  "How long has the respondent company been in the market:\n\n" +
                  "Additional information:\n"
                }
                rows={14}
                className="font-mono text-sm"
                aria-required
              />
              <p className="mt-1 text-xs text-muted-foreground">
                Use the section labels shown in the placeholder (each block may continue on the following lines until
                the next label). Fill at least one substantive section — typically reason for search and/or field of
                activity.
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
              {switchRunOpenList.map((r) => (
                <SwitchRunListRow key={r.id} run={r} selectedRun={selectedRun} onSelect={openRunById} />
              ))}
              {switchRunClosedList.length > 0 ? (
                <div className="space-y-2 pt-2">
                  <div
                    className="rounded-xl border border-border/80 bg-muted/30 px-3 py-2.5"
                    role="group"
                    aria-label="Closed runs"
                  >
                    <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      Closed runs
                    </p>
                    <p className="mt-1 text-sm text-muted-foreground leading-snug">
                      These runs are closed — no new outreach sending. Threads, replies, and history stay available.
                    </p>
                  </div>
                  {switchRunClosedList.map((r) => (
                    <SwitchRunListRow key={r.id} run={r} selectedRun={selectedRun} onSelect={openRunById} />
                  ))}
                </div>
              ) : null}
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

      <Dialog
        open={removeCompanyDialog != null}
        onOpenChange={(open) => {
          if (!open && !removeCompanyInFlight) setRemoveCompanyDialog(null);
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Remove this company?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            {removeCompanyDialog ? (
              <>
                Are you sure you want to remove{" "}
                <span className="font-medium text-foreground">«{removeCompanyDialog.name}»</span> from this run? Matching
                contacts stored for this company will be removed. This does not affect other runs.
              </>
            ) : (
              "—"
            )}
          </p>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button
              type="button"
              variant="outline"
              disabled={removeCompanyInFlight}
              onClick={() => setRemoveCompanyDialog(null)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={removeCompanyInFlight}
              onClick={() => void confirmRemoveCompanyFromRun()}
            >
              {removeCompanyInFlight ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                  Removing…
                </>
              ) : (
                "Yes, remove"
              )}
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

      {editDraft || editDraftLoading ? (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
          <button
            type="button"
            className="fixed inset-0 bg-black/50"
            aria-label="Close"
            disabled={editDraftSaving}
            onClick={() => {
              if (!editDraftSaving) closeEditDraftModal();
            }}
          />
          <div
            className="relative z-50 flex h-[80vh] max-h-[80vh] w-full max-w-[63rem] flex-col overflow-hidden rounded-xl border-2 border-border bg-card shadow-lg"
            role="dialog"
            aria-labelledby="edit-email-draft-title"
            aria-busy={editDraftLoading}
          >
            <h2 id="edit-email-draft-title" className="shrink-0 px-6 pt-6 text-lg font-semibold">
              Edit email draft
            </h2>
            <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-6 py-4">
              {editDraftLoading && !editDraft ? (
                <div
                  className="flex min-h-[min(40vh,320px)] flex-col items-center justify-center gap-3 py-12 text-center"
                  role="status"
                  aria-live="polite"
                >
                  <Loader2 className="h-10 w-10 shrink-0 animate-spin text-primary" aria-hidden />
                  <p className="text-sm text-muted-foreground">Loading draft from server…</p>
                  <p className="max-w-sm text-xs text-muted-foreground">
                    Usually under a few seconds. If it hangs, click Cancel — or wait; the request stops
                    automatically after about {Math.round(EMAIL_DRAFT_GET_FOR_EDIT_TIMEOUT_MS / 1000)}s.
                  </p>
                </div>
              ) : editDraft ? (
                <div className="grid gap-3">
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
              ) : null}
            </div>
            <div className="shrink-0 border-t border-border px-6 py-4">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
                <label className="flex max-w-[min(100%,20rem)] cursor-pointer items-start gap-2.5 text-sm leading-snug text-muted-foreground">
                  <input
                    type="checkbox"
                    className="mt-0.5 h-4 w-4 shrink-0 rounded border-2 border-border accent-primary"
                    checked={
                      draftReviewTab === "approved"
                        ? applyAssetsEditScope === "approved"
                        : applyAssetsEditScope === "pending"
                    }
                    disabled={editDraftSaving || editDraftLoading || !editDraft}
                    onChange={(e) => {
                      if (!e.target.checked) setApplyAssetsEditScope("none");
                      else
                        setApplyAssetsEditScope(draftReviewTab === "approved" ? "approved" : "pending");
                    }}
                  />
                  <span>
                    <span className="font-medium text-foreground">Apply assets to all drafts</span>
                    <span className="mt-0.5 block text-xs">
                      {draftReviewTab === "approved"
                        ? "Approved only — same attachments as here after Save."
                        : "Pending review only — same attachments as here after Save."}
                    </span>
                  </span>
                </label>
                <div className="flex shrink-0 justify-end gap-2">
                  <Button variant="outline" disabled={editDraftSaving} onClick={() => closeEditDraftModal()}>
                    Cancel
                  </Button>
                  <Button
                    type="button"
                    disabled={editDraftSaving || editDraftLoading || !editDraft}
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
              company search and contact validation run in the <strong>background</strong> on the server — you can switch
              to other runs and start Continue outreach there too; only runs with an active job keep this button
              disabled. Same brief, extra rounds to grow the list. Existing contacts, drafts, and tracking stay in place;
              new rows are merged in. After you confirm, this window closes; a banner under the title lists in-flight
              runs.
            </p>
            <div className="mt-6 flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={closeRestartDialog}>
                Cancel
              </Button>
              <Button
                type="button"
                onClick={() => void confirmRestartRun()}
                disabled={Boolean(restartDialogRun && restartsInFlight[restartDialogRun.id])}
              >
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
