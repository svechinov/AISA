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
  Users,
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

const BRIEF_LABEL_PREFIXES = [
  ["offer:", "offer"],
  ["target entities:", "target_entities"],
  ["target:", "target_entities"],
  ["target roles:", "target_roles"],
  ["roles:", "target_roles"],
  ["role:", "target_roles"],
  ["goal:", "goal"],
  ["tone:", "tone"],
  ["notes:", "notes"],
];

function briefLineLabelAndRest(line) {
  const s = line.trim();
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

/** Prefill dialog from the current run — same name/brief as that run until the user edits (then UI adds “ · next”). */
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
/** Single-company find retry calls the LLM again; allow longer than default API timeout. */
const COMPANY_RETRY_FIND_TIMEOUT_MS = 120000;
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

const DRAFT_FILTER_OPTS = [
  { value: "all", label: "All drafts" },
  { value: "pending", label: "Pending review" },
  { value: "approved", label: "Approved" },
  { value: "edited", label: "Edited" },
  { value: "rejected", label: "Rejected" },
  { value: "draft", label: "Draft status" },
  { value: "sending", label: "Sending" },
  { value: "sent", label: "Sent" },
  { value: "failed", label: "Failed" },
];

export default function AiBizOsHumanUI() {
  const [projects, setProjects] = useState([]);
  const [selectedProject, setSelectedProject] = useState(null);
  const [selectedRun, setSelectedRun] = useState(null);
  const [steps, setSteps] = useState([]);
  const [contacts, setContacts] = useState([]);
  const [drafts, setDrafts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [projectName, setProjectName] = useState("New campaign");
  const [search, setSearch] = useState("");
  const [draftFilter, setDraftFilter] = useState("all");
  const [projectView, setProjectView] = useState("active");
  const [mainNav, setMainNav] = useState("runs");
  const [runsList, setRunsList] = useState([]);
  const [workspace, setWorkspace] = useState(null);
  const [newRunOpen, setNewRunOpen] = useState(false);
  /** Snapshot when the dialog opened from a selected run (trimmed fields) — used to detect “same outreach” vs new wave. */
  const [newRunBaseline, setNewRunBaseline] = useState(null);
  const [switchRunOpen, setSwitchRunOpen] = useState(false);
  const [closeRunOpen, setCloseRunOpen] = useState(false);
  const [newRunForm, setNewRunForm] = useState({
    name: "",
    notes: "",
    segment: "",
    outreach_brief: DEFAULT_OUTREACH_BRIEF,
  });

  /** Inline edit: { id, email } */
  const [editingContact, setEditingContact] = useState(null);
  const [createDraftContactId, setCreateDraftContactId] = useState(null);
  /** Keys: draft id string — outbound draft body regeneration in progress. */
  const [regeneratingOutboundDraftIds, setRegeneratingOutboundDraftIds] = useState(() => ({}));
  const [editDraft, setEditDraft] = useState(null);
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
  const [promptSetupOpen, setPromptSetupOpen] = useState(false);
  const [promptSetupText, setPromptSetupText] = useState("");
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
  const [contactsPendingPage, setContactsPendingPage] = useState(1);
  const [contactsApprovedPage, setContactsApprovedPage] = useState(1);
  const [contactsRejectedPage, setContactsRejectedPage] = useState(1);
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
    setLoading(true);
    setError("");
    try {
      const qs = v === "archived" ? "?archived=true" : "?archived=false";
      const data = await api(`/projects${qs}`, { signal });
      if (signal?.aborted) return;
      setProjects(data);
      setSelectedProject((prev) => {
        if (!data.length) return null;
        if (prev && data.some((p) => p.id === prev.id)) return prev;
        return data[0];
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
      await loadRunDetails(runId);
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
      await loadRunDetails(runId);
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
      await loadRunDetails(runId);
    } finally {
      setCompanyRetryAllLoading(false);
    }
  };

  const loadRunDetails = async (runId) => {
    if (!runId) return null;
    try {
      const [run, stepsData, contactsData, draftsData, ws, assetsData, packetsData] = await Promise.all([
        api(`/runs/${runId}`),
        api(`/steps/run/${runId}`),
        api(`/contacts/run/${runId}`),
        api(`/email-drafts/run/${runId}`),
        api(`/runs/${runId}/workspace`),
        api(`/assets`),
        api(`/asset-packets/run/${runId}`),
      ]);
      setSelectedRun(run);
      setSteps(stepsData);
      setContacts(contactsData);
      setDrafts(draftsData);
      setWorkspace(ws);
      setAssetsLibrary(Array.isArray(assetsData) ? assetsData : []);
      setRunAssetPackets(Array.isArray(packetsData) ? packetsData : []);
      return ws;
    } catch (e) {
      setUiError(setError, e);
      return null;
    }
  };

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
    const ac = new AbortController();
    void loadProjects(undefined, { signal: ac.signal });
    return () => ac.abort();
  }, [projectView, loadProjects]);

  useEffect(() => {
    void loadSetupIntegration();
  }, [loadSetupIntegration]);

  useEffect(() => {
    if (mainNav === "drafts") void loadSetupIntegration();
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
    (async () => {
      try {
        const runs = await api(`/runs/project/${pid}`);
        const ordered = orderRunsOpenFirst(runs);
        setRunsList(ordered);
        if (ordered.length > 0) {
          await loadRunDetails(ordered[0].id);
        } else {
          setSelectedRun(null);
          setSteps([]);
          setContacts([]);
          setDrafts([]);
          setWorkspace(null);
        }
      } catch (e) {
        const msg = String(e?.message || e);
        if (isConsoleOnlyApiFailure(msg)) {
          console.warn("[AiBizOsHumanUI] runs list", msg, e);
        } else {
          setRunsList([]);
          setError(msg);
        }
      }
    })();
  }, [selectedProject]);

  useEffect(() => {
    if (!selectedRun?.id) return;
    const id = selectedRun.id;
    const interval = setInterval(() => {
      loadRunDetails(id);
    }, 4000);
    return () => clearInterval(interval);
  }, [selectedRun?.id]);

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

  const canSubmitNewRun =
    !!selectedProject &&
    newRunForm.name.trim().length > 0 &&
    newRunForm.segment.trim().length > 0 &&
    newRunForm.outreach_brief.trim().length > 0 &&
    outreachBriefHasOfferOrGoal(newRunForm.outreach_brief);

  const newRunMatchesBaseline = useMemo(() => {
    if (!newRunBaseline) return false;
    const b = newRunBaseline;
    return (
      newRunForm.name.trim() === b.name &&
      newRunForm.notes.trim() === b.notes &&
      newRunForm.segment.trim() === b.segment &&
      newRunForm.outreach_brief.trim() === b.outreach_brief
    );
  }, [newRunForm, newRunBaseline]);

  const integrationInformer = useMemo(
    () => formatSetupIntegrationInformer(setupIntegration),
    [setupIntegration],
  );

  useEffect(() => {
    if (!newRunOpen) setNewRunBaseline(null);
  }, [newRunOpen]);

  /** Opening from an existing run: once any field diverges, suggest a new wave name with “ · next” unless the user already edited the name. */
  useEffect(() => {
    if (!newRunOpen || !newRunBaseline) return;
    const b = newRunBaseline;
    const name = newRunForm.name.trim();
    const notes = newRunForm.notes.trim();
    const segment = newRunForm.segment.trim();
    const brief = newRunForm.outreach_brief.trim();
    const dirty =
      name !== b.name || notes !== b.notes || segment !== b.segment || brief !== b.outreach_brief;
    if (!dirty || name !== b.name || !b.name) return;
    const withNext = `${b.name} · next`;
    if (newRunForm.name !== withNext) {
      setNewRunForm((f) => ({ ...f, name: withNext }));
    }
  }, [newRunOpen, newRunBaseline, newRunForm.name, newRunForm.notes, newRunForm.segment, newRunForm.outreach_brief]);

  const createNewRun = async () => {
    if (!canSubmitNewRun) return;
    try {
      setError("");
      const pid = projectPk(selectedProject);
      const run = await api("/runs/start", {
        method: "POST",
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
      setMainNav("contacts");
      setNewRunForm({
        name: "",
        notes: "",
        segment: "",
        outreach_brief: DEFAULT_OUTREACH_BRIEF,
      });
    } catch (e) {
      setUiError(setError, e);
    }
  };

  const submitNewRunDialog = async () => {
    if (!canSubmitNewRun) return;
    if (newRunBaseline && newRunMatchesBaseline) {
      setNewRunOpen(false);
      return;
    }
    await createNewRun();
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
    setMainNav("contacts");
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
      await loadRunDetails(run.id);
    } catch (e) {
      setUiError(setError, e);
    }
  };

  const approveContact = async (contactId) => {
    try {
      setError("");
      const current = contacts.find((c) => c.id === contactId);
      if (current?.review_status === "pending") {
        setContacts((prev) => prev.filter((c) => c.id !== contactId));
      }
      await api(`/contacts/${contactId}/review`, {
        method: "PATCH",
        body: { review_status: "approved" },
      });
      if (selectedRun) await loadRunDetails(selectedRun.id);
    } catch (e) {
      setUiError(setError, e);
      if (selectedRun) await loadRunDetails(selectedRun.id);
    }
  };

  const reviewContact = async (id, review_status) => {
    try {
      setError("");
      await api(`/contacts/${id}/review`, {
        method: "PATCH",
        body: { review_status },
      });
      await loadRunDetails(selectedRun.id);
    } catch (e) {
      setUiError(setError, e);
    }
  };

  const createDraftForContact = async (contactId) => {
    if (!selectedRun?.id) return;
    setCreateDraftContactId(contactId);
    try {
      setError("");
      await api(`/contacts/${contactId}/create-draft`, { method: "POST" });
      await loadRunDetails(selectedRun.id);
    } catch (e) {
      setUiError(setError, e);
    } finally {
      setCreateDraftContactId(null);
    }
  };

  const reviewDraft = async (id, review_status, review_notes) => {
    try {
      setError("");
      const body = { review_status };
      if (review_notes !== undefined) body.review_notes = review_notes;
      await api(`/email-drafts/${id}/review`, {
        method: "PATCH",
        body,
      });
      await loadRunDetails(selectedRun.id);
    } catch (e) {
      setUiError(setError, e);
    }
  };

  const regenerateOutboundDraft = async (draftId) => {
    if (!selectedRun) return;
    const idKey = String(draftId);
    setRegeneratingOutboundDraftIds((p) => ({ ...p, [idKey]: true }));
    try {
      setError("");
      await api(`/email-drafts/${draftId}/regenerate`, { method: "POST" });
      await loadRunDetails(selectedRun.id);
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
      await loadRunDetails(selectedRun.id);
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
    try {
      setError("");
      await api(`/sending/drafts/${draftId}/send`, { method: "POST" });
      await loadRunDetails(selectedRun.id);
    } catch (e) {
      setUiError(setError, e);
      void loadSetupIntegration();
    }
  };

  const sendAllApproved = async () => {
    if (!selectedRun) return;
    if (!gmailSendReady) {
      openGmailSetup();
      return;
    }
    try {
      setError("");
      await api(`/sending/runs/${selectedRun.id}/send`, { method: "POST" });
      await loadRunDetails(selectedRun.id);
    } catch (e) {
      setUiError(setError, e);
      void loadSetupIntegration();
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
        await loadRunDetails(runId);
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
        await loadRunDetails(runId);
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
        await loadRunDetails(runId);
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
    setEditDraft(d);
    setDraftForm({
      subject: d.subject ?? "",
      body: d.body ?? "",
      attached_asset_ids: normalizeAttachedAssetIds(d.attached_asset_ids),
    });
    void (async () => {
      try {
        const [assetsData, packetsData] = await Promise.all([
          api(`/assets`),
          api(`/asset-packets/run/${selectedRun.id}`),
        ]);
        setAssetsLibrary(Array.isArray(assetsData) ? assetsData : []);
        setRunAssetPackets(Array.isArray(packetsData) ? packetsData : []);
      } catch {
        /* keep previous library if request fails */
      }
    })();
  };

  const saveEditDraft = async () => {
    if (!editDraft || !selectedRun) return;
    try {
      setError("");
      await api(`/email-drafts/${editDraft.id}/edit`, {
        method: "PATCH",
        body: {
          subject: draftForm.subject,
          body: draftForm.body,
          attached_asset_ids: draftForm.attached_asset_ids,
        },
      });
      setEditDraft(null);
      await loadRunDetails(selectedRun.id);
    } catch (e) {
      setUiError(setError, e);
    }
  };

  const openSignatureSetup = () => {
    setSignatureFormHtml(selectedRun?.sender_signature_html ?? "");
    setSignatureEditorKey((k) => k + 1);
    setSignatureSetupOpen(true);
  };

  const openPromptSetup = () => {
    setPromptSetupText(getPromptSetupEditorInitialText(selectedRun));
    setPromptSetupOpen(true);
  };

  const savePromptSetup = async () => {
    if (!selectedRun?.id) return;
    try {
      setError("");
      await api(`/runs/${selectedRun.id}/prompt-setup`, {
        method: "PATCH",
        body: { prompt_setup_text: promptSetupText },
      });
      setPromptSetupOpen(false);
      await loadRunDetails(selectedRun.id);
    } catch (e) {
      setUiError(setError, e);
    }
  };

  const saveSignatureSetup = async () => {
    if (!selectedRun?.id) return;
    try {
      setError("");
      await api(`/runs/${selectedRun.id}/signature`, {
        method: "PATCH",
        body: { signature_html: signatureFormHtml },
      });
      await loadRunDetails(selectedRun.id);
      setSignatureSetupOpen(false);
    } catch (e) {
      setUiError(setError, e);
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

  const filteredDrafts = useMemo(() => {
    return drafts.filter((d) => {
      const q = search.trim().toLowerCase();
      const matchesSearch =
        !q || [d.company, d.to_email, d.subject, d.body].some((v) => (v || "").toLowerCase().includes(q));
      const matchesFilter =
        draftFilter === "all" || d.review_status === draftFilter || d.status === draftFilter;
      return matchesSearch && matchesFilter;
    });
  }, [drafts, search, draftFilter]);

  const contactHasBadEmailHealth = (c) =>
    c.email_health === "dead_mailbox" || c.email_health === "bounced";

  const contactHasEmail = (c) => Boolean((c?.email || "").trim());

  /** Stable key to group review cards by company (no backend merge). */
  const contactCompanyGroupKey = (c) => {
    const co = (c.company || "")
      .trim()
      .toLowerCase()
      .replace(/\s+/g, " ");
    let w = (c.website || "").trim().toLowerCase();
    w = w.replace(/^https?:\/\//, "").replace(/^www\./, "");
    w = w.replace(/\/+$/, "");
    if (!co && !w) return `__single_${c.id}`;
    return `${co}\x1f${w}`;
  };

  /** Preserve list order; each value is one or more contacts sharing the same company key. */
  const groupContactsByCompany = (list) => {
    const keyToContacts = new Map();
    for (const c of list) {
      const k = contactCompanyGroupKey(c);
      if (!keyToContacts.has(k)) keyToContacts.set(k, []);
      keyToContacts.get(k).push(c);
    }
    const seen = new Set();
    const groups = [];
    for (const c of list) {
      const k = contactCompanyGroupKey(c);
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
  const approvedDrafts = drafts.filter((d) => ["approved", "edited"].includes(d.review_status)).length;
  const pendingContacts = contactsVisible.filter((c) => c.review_status === "pending").length;

  const pending = contactsMatchingSearch.filter((c) => c.review_status === "pending");
  const approvedList = useMemo(() => {
    const raw = contactsMatchingSearch.filter((c) => ["approved", "edited"].includes(c.review_status));
    const deliveryOrder = (c) => {
      if (c.email_health === "dead_mailbox") return 2;
      if (c.email_health === "bounced") return 1;
      return 0;
    };
    return [...raw].sort((a, b) => deliveryOrder(a) - deliveryOrder(b) || a.id - b.id);
  }, [contactsMatchingSearch]);
  const rejectedList = contactsMatchingSearch.filter((c) => c.review_status === "rejected");

  const pendingGroups = useMemo(() => groupContactsByCompany(pending), [pending]);
  const approvedGroups = useMemo(() => groupContactsByCompany(approvedList), [approvedList]);
  const rejectedGroups = useMemo(() => groupContactsByCompany(rejectedList), [rejectedList]);

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

  const contactsPendingPageCount = Math.max(1, Math.ceil(pendingGroups.length / WORKSPACE_TABLE_PAGE_SIZE));
  const contactsApprovedPageCount = Math.max(1, Math.ceil(approvedGroups.length / WORKSPACE_TABLE_PAGE_SIZE));
  const contactsRejectedPageCount = Math.max(1, Math.ceil(rejectedGroups.length / WORKSPACE_TABLE_PAGE_SIZE));

  const pendingGroupsPage = useMemo(() => {
    const start = (contactsPendingPage - 1) * WORKSPACE_TABLE_PAGE_SIZE;
    return pendingGroups.slice(start, start + WORKSPACE_TABLE_PAGE_SIZE);
  }, [pendingGroups, contactsPendingPage]);

  const approvedGroupsPage = useMemo(() => {
    const start = (contactsApprovedPage - 1) * WORKSPACE_TABLE_PAGE_SIZE;
    return approvedGroups.slice(start, start + WORKSPACE_TABLE_PAGE_SIZE);
  }, [approvedGroups, contactsApprovedPage]);

  const rejectedGroupsPage = useMemo(() => {
    const start = (contactsRejectedPage - 1) * WORKSPACE_TABLE_PAGE_SIZE;
    return rejectedGroups.slice(start, start + WORKSPACE_TABLE_PAGE_SIZE);
  }, [rejectedGroups, contactsRejectedPage]);

  useEffect(() => {
    setCompaniesPage((p) => Math.min(Math.max(1, p), companiesPageCount));
  }, [companiesPageCount, companiesListForPage]);

  useEffect(() => {
    setContactsPendingPage((p) => Math.min(Math.max(1, p), contactsPendingPageCount));
  }, [contactsPendingPageCount, pendingGroups]);

  useEffect(() => {
    setContactsApprovedPage((p) => Math.min(Math.max(1, p), contactsApprovedPageCount));
  }, [contactsApprovedPageCount, approvedGroups]);

  useEffect(() => {
    setContactsRejectedPage((p) => Math.min(Math.max(1, p), contactsRejectedPageCount));
  }, [contactsRejectedPageCount, rejectedGroups]);

  useEffect(() => {
    setCompaniesPage(1);
    setContactsPendingPage(1);
    setContactsApprovedPage(1);
    setContactsRejectedPage(1);
  }, [selectedRun?.id, search]);

  const draftsPending = filteredDrafts.filter((d) => d.review_status === "pending");
  const draftsApprovedList = filteredDrafts.filter((d) =>
    ["approved", "edited"].includes(d.review_status),
  );
  const draftsRejectedList = filteredDrafts.filter((d) => d.review_status === "rejected");

  /** Hide empty review buckets when a narrow filter is active (e.g. Approved → no "Pending (0)"). */
  const showDraftsPendingSection =
    draftFilter === "all" || draftFilter === "pending" || draftsPending.length > 0;
  const showDraftsApprovedSection =
    draftFilter === "all" ||
    draftFilter === "approved" ||
    draftFilter === "edited" ||
    draftsApprovedList.length > 0;

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

  const promptSetupSavedFilled = useMemo(() => {
    const raw = selectedRun?.context_json?.[PROMPT_SETUP_STORAGE_KEY];
    return typeof raw === "string" && raw.trim().length > 0;
  }, [selectedRun?.id, selectedRun?.context_json]);

  const signatureSetupFilled = useMemo(() => {
    const html = selectedRun?.sender_signature_html ?? workspace?.sender_signature_html ?? "";
    return runSignatureHasMeaningfulContent(html);
  }, [selectedRun?.id, selectedRun?.sender_signature_html, workspace?.sender_signature_html]);

  const primaryCta = useMemo(() => {
    if (!selectedRun?.id) return null;
    const phase = workspace?.display_phase;
    if (phase === "Closed") return null;
    if (phase === "Preparing") {
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
  }, [
    selectedRun,
    workspace?.display_phase,
    approvedContactsReachable,
    outreachBatchProgress,
    openNewRunDialog,
  ]);

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
                    await api(`/contacts/${contact.id}/edit`, {
                      method: "PATCH",
                      body,
                    });
                    setEditingContact(null);
                    if (selectedRun) await loadRunDetails(selectedRun.id);
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

  const renderContactGroupCard = (group) => {
    const multi = group.length > 1;
    const cardClass = multi ? pickGroupContactCardClass(group) : contactCardClass(group[0]);
    const cardKey = multi ? `grp-${group.map((c) => c.id).join("-")}` : group[0].id;
    return (
      <Card key={cardKey} className={cardClass}>
        <CardContent className="p-5">
          {multi ? (
            <div className="mb-4 border-b border-border pb-3">
              <div className="text-lg font-semibold">{group[0].company || "Unnamed company"}</div>
            </div>
          ) : null}
          {group.map((contact, idx) => (
            <div key={contact.id}>
              {idx > 0 ? <Separator className="my-4 bg-border/90" decorative /> : null}
              {renderContactBlock(contact, { grouped: multi })}
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
                      <Button size="sm" onClick={() => reviewDraft(draft.id, "approved")}>
                        Approve
                      </Button>
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => reviewDraft(draft.id, "approved", OUTBOUND_REVIEW_SEND_LATER)}
                        className="px-2.5"
                        aria-label="Send later"
                        title="Send later — approve without sending now"
                      >
                        <Clock className="h-4 w-4" aria-hidden />
                      </Button>
                      {canRegenerateOutboundDraft(draft) ? (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={isRegeneratingOutbound}
                          onClick={() => void regenerateOutboundDraft(draft.id)}
                        >
                          Regenerate
                        </Button>
                      ) : null}
                      <Button size="sm" variant="outline" onClick={() => reviewDraft(draft.id, "rejected")}>
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
                          disabled={isRegeneratingOutbound}
                          onClick={() => void regenerateOutboundDraft(draft.id)}
                        >
                          Regenerate
                        </Button>
                      ) : null}
                      <Button size="sm" variant="outline" onClick={() => reviewDraft(draft.id, "rejected")}>
                        Reject
                      </Button>
                    </>
                  ) : null}
                  {draft.review_status === "rejected" ? (
                    <Button size="sm" onClick={() => reviewDraft(draft.id, "approved")}>
                      Approve
                    </Button>
                  ) : null}
                  {canSendDraft(draft) ? (
                    <Button size="sm" className="gap-1.5" onClick={() => void sendDraft(draft.id)}>
                      {!gmailSendReady ? (
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
          {draft.error_message ? (
            <div className="rounded-xl border-2 border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
              {draft.error_message}
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

          <div className="flex flex-col gap-3 rounded-2xl border-2 border-border bg-card p-4 md:flex-row md:items-center md:justify-between">
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
        </div>

        {error ? (
          <Card className="mb-6 border-2 border-destructive/50">
            <CardContent className="p-4 text-sm text-destructive">{error}</CardContent>
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
                          <div className="flex items-center justify-between gap-3">
                            <div className="font-medium">{project.name}</div>
                            <Badge variant="secondary">#{project.id}</Badge>
                          </div>
                          <div className="mt-1 text-xs text-muted-foreground">{pretty(project.type)}</div>
                        </button>
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
                        Replies:{" "}
                        <span className="font-medium">{workspace.performance?.replies ?? 0}</span>
                      </li>
                      <li>
                        Active threads:{" "}
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
                        Reminders (active):{" "}
                        <span className="font-medium">{workspace.performance?.reminders_active ?? 0}</span>
                      </li>
                      <li>
                        Reminders due:{" "}
                        <span className="font-medium">{workspace.performance?.reminders_due ?? 0}</span>
                      </li>
                      <li>
                        Packets sent:{" "}
                        <span className="font-medium">{workspace.performance?.packets_sent ?? 0}</span>
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
              {visibleMainNavItems.map((item) => (
                <Button
                  key={item.value}
                  type="button"
                  size="sm"
                  variant={mainNav === item.value ? "secondary" : "ghost"}
                  className="rounded-xl"
                  onClick={() => setMainNav(item.value)}
                >
                  {item.label}
                </Button>
              ))}
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
                      <Card key={r.id} className="rounded-2xl border-2 border-border shadow-none">
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
                            <Button type="button" size="sm" variant="outline" onClick={() => void openRunById(r.id)}>
                              Open
                            </Button>
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              disabled={r.display_phase === "Closed" || pendingRestart != null}
                              onClick={() => openRestartDialog(r)}
                            >
                              <RefreshCw className="mr-1 h-4 w-4" aria-hidden />
                              Restart
                            </Button>
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              disabled={r.display_phase === "Closed"}
                              onClick={async () => {
                                await loadRunDetails(r.id);
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
                          <Badge variant="default" className="font-normal">
                            Contacts found
                          </Badge>
                          <span>At least one matching person has a usable email in find-contacts output.</span>
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
                              const badge =
                                st === "found" ? (
                                  <Badge variant="default" className="font-normal">
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
                    <CardTitle>Review workspace</CardTitle>
                    <CardDescription>Switch between Contacts and Drafts using the bar above.</CardDescription>
                  </div>
                  <div className="flex w-full flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center md:max-w-none md:justify-end">
                    <div className="flex flex-wrap gap-2">
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
                    <div className="text-sm text-muted-foreground">
                      {pendingContacts} contacts left to review
                    </div>

                    {pendingContacts > 0 ? (
                      <div className="space-y-3">
                        <div className="text-sm font-medium">
                          Pending ({pending.length})
                        </div>
                        <div className="grid gap-3">
                          {pendingGroupsPage.map((g) => renderContactGroupCard(g))}
                        </div>
                        {pendingGroups.length > WORKSPACE_TABLE_PAGE_SIZE ? (
                          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between text-sm text-muted-foreground">
                            <span>
                              {(contactsPendingPage - 1) * WORKSPACE_TABLE_PAGE_SIZE + 1}–
                              {Math.min(
                                contactsPendingPage * WORKSPACE_TABLE_PAGE_SIZE,
                                pendingGroups.length,
                              )}{" "}
                              of {pendingGroups.length}
                            </span>
                            <div className="flex flex-wrap gap-2">
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                disabled={contactsPendingPage <= 1}
                                onClick={() => setContactsPendingPage((p) => Math.max(1, p - 1))}
                              >
                                Previous
                              </Button>
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                disabled={contactsPendingPage >= contactsPendingPageCount}
                                onClick={() =>
                                  setContactsPendingPage((p) =>
                                    Math.min(contactsPendingPageCount, p + 1),
                                  )
                                }
                              >
                                Next
                              </Button>
                            </div>
                          </div>
                        ) : pendingGroups.length > 0 ? (
                          <p className="text-xs text-muted-foreground">
                            {pendingGroups.length} group{pendingGroups.length === 1 ? "" : "s"} total.
                          </p>
                        ) : null}
                        {pending.length === 0 ? (
                          <div className="text-sm text-muted-foreground">
                            No pending contacts match your search — clear search or check Approved / Rejected.
                          </div>
                        ) : null}
                      </div>
                    ) : null}

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

                    <div className="space-y-3">
                      <div className="text-sm font-medium">Approved ({approvedContactsReachable})</div>
                      <div className="grid gap-3">
                        {approvedGroupsPage.map((g) => renderContactGroupCard(g))}
                      </div>
                      {approvedGroups.length > WORKSPACE_TABLE_PAGE_SIZE ? (
                        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between text-sm text-muted-foreground">
                          <span>
                            {(contactsApprovedPage - 1) * WORKSPACE_TABLE_PAGE_SIZE + 1}–
                            {Math.min(
                              contactsApprovedPage * WORKSPACE_TABLE_PAGE_SIZE,
                              approvedGroups.length,
                            )}{" "}
                            of {approvedGroups.length}
                          </span>
                          <div className="flex flex-wrap gap-2">
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              disabled={contactsApprovedPage <= 1}
                              onClick={() => setContactsApprovedPage((p) => Math.max(1, p - 1))}
                            >
                              Previous
                            </Button>
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              disabled={contactsApprovedPage >= contactsApprovedPageCount}
                              onClick={() =>
                                setContactsApprovedPage((p) =>
                                  Math.min(contactsApprovedPageCount, p + 1),
                                )
                              }
                            >
                              Next
                            </Button>
                          </div>
                        </div>
                      ) : approvedGroups.length > 0 ? (
                        <p className="text-xs text-muted-foreground">
                          {approvedGroups.length} group{approvedGroups.length === 1 ? "" : "s"} total.
                        </p>
                      ) : null}
                    </div>

                    {rejectedList.length > 0 ? (
                      <details className="group rounded-2xl border-2 border-border">
                        <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 text-sm font-medium [&::-webkit-details-marker]:hidden">
                          <ChevronRight className="h-4 w-4 shrink-0 transition group-open:rotate-90" />
                          Rejected ({rejectedList.length})
                        </summary>
                        <div className="grid gap-3 border-t border-border px-4 pb-4 pt-3">
                          {rejectedGroupsPage.map((g) => renderContactGroupCard(g))}
                        </div>
                        {rejectedGroups.length > WORKSPACE_TABLE_PAGE_SIZE ? (
                          <div className="flex flex-col gap-2 border-t border-border px-4 pb-4 pt-3 sm:flex-row sm:items-center sm:justify-between text-sm text-muted-foreground">
                            <span>
                              {(contactsRejectedPage - 1) * WORKSPACE_TABLE_PAGE_SIZE + 1}–
                              {Math.min(
                                contactsRejectedPage * WORKSPACE_TABLE_PAGE_SIZE,
                                rejectedGroups.length,
                              )}{" "}
                              of {rejectedGroups.length}
                            </span>
                            <div className="flex flex-wrap gap-2">
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                disabled={contactsRejectedPage <= 1}
                                onClick={() => setContactsRejectedPage((p) => Math.max(1, p - 1))}
                              >
                                Previous
                              </Button>
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                disabled={contactsRejectedPage >= contactsRejectedPageCount}
                                onClick={() =>
                                  setContactsRejectedPage((p) =>
                                    Math.min(contactsRejectedPageCount, p + 1),
                                  )
                                }
                              >
                                Next
                              </Button>
                            </div>
                          </div>
                        ) : rejectedGroups.length > 0 ? (
                          <p className="px-4 pb-4 text-xs text-muted-foreground">
                            {rejectedGroups.length} group{rejectedGroups.length === 1 ? "" : "s"} total.
                          </p>
                        ) : null}
                      </details>
                    ) : null}

                    {contactsVisible.length === 0 ? (
                      <div className="text-center text-sm text-muted-foreground">
                        No contacts for this run yet.
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <div className="space-y-6">
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                      <div className="flex flex-wrap items-center gap-2">
                        <Button
                          type="button"
                          className="gap-1.5"
                          onClick={() => void sendAllApproved()}
                          disabled={!selectedRun || approvedDrafts === 0}
                        >
                          {!gmailSendReady ? (
                            <CircleX
                              className="h-4 w-4 shrink-0 text-red-600 dark:text-red-500"
                              aria-hidden
                            />
                          ) : null}
                          Send all approved
                        </Button>
                      </div>
                      <NativeFilterSelect
                        className="w-full sm:w-[220px]"
                        value={draftFilter}
                        onValueChange={setDraftFilter}
                        options={DRAFT_FILTER_OPTS}
                      />
                    </div>
                    {drafts.length > 0 ? (
                      <>
                        {showDraftsPendingSection ? (
                          <div className="space-y-3">
                            <div className="text-sm font-medium">Pending ({draftsPending.length})</div>
                            <div className="grid gap-3">{draftsPending.map((d) => renderDraftCard(d))}</div>
                          </div>
                        ) : null}

                        {showDraftsApprovedSection ? (
                          <div className="space-y-3">
                            <div className="text-sm font-medium">Approved ({draftsApprovedList.length})</div>
                            <div className="grid gap-3">{draftsApprovedList.map((d) => renderDraftCard(d))}</div>
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
                      </>
                    ) : (
                      <div className="text-sm text-muted-foreground">No drafts yet.</div>
                    )}

                    {drafts.length > 0 && filteredDrafts.length === 0 ? (
                      <div className="text-sm text-muted-foreground">No drafts match the current filter.</div>
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
                activeTab={mainNavToTrackingTab(mainNav)}
                singleTabMode
                onRunWorkspaceRefresh={() => void loadRunDetails(selectedRun.id)}
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
            <DialogTitle>
              {newRunBaseline && newRunMatchesBaseline ? "Run" : "New run"}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <p className="text-xs text-muted-foreground">
              This brief drives company search, contact roles, and the master email for the whole run.
              {newRunBaseline && newRunMatchesBaseline
                ? " Same details as this run — continue here, or change something to start a new wave."
                : newRunBaseline
                  ? " Changes turn this into a new wave (name updates with “ · next” unless you edit it yourself)."
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
          <DialogFooter className="gap-2 sm:gap-0">
            <Button type="button" variant="outline" onClick={() => setNewRunOpen(false)}>
              Cancel
            </Button>
            <Button type="button" onClick={() => void submitNewRunDialog()} disabled={!canSubmitNewRun}>
              {newRunBaseline && newRunMatchesBaseline ? "Continue" : "Create run"}
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
                      isCurrent
                        ? "border-primary bg-primary/10 ring-2 ring-primary/25 dark:bg-primary/15"
                        : "border-border"
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
            onClick={() => setEditDraft(null)}
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
            <div className="mt-6 flex justify-end gap-2">
              <Button variant="outline" onClick={() => setEditDraft(null)}>
                Cancel
              </Button>
              <Button onClick={saveEditDraft}>Save</Button>
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
            <h2 className="text-lg font-semibold">Restart run</h2>
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
                <RefreshCw className="mr-2 h-4 w-4" aria-hidden />
                Restart
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
            onClick={() => setPromptSetupOpen(false)}
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
              <Button type="button" variant="outline" onClick={() => setPromptSetupOpen(false)}>
                Cancel
              </Button>
              <Button type="button" onClick={() => void savePromptSetup()}>
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
                className="mt-3 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
                role="alert"
              >
                {gmailSetupErr}
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
            onClick={() => setSignatureSetupOpen(false)}
          />
          <div className="relative z-50 w-full max-w-2xl rounded-xl border-2 border-border bg-card p-6 shadow-lg">
            <h2 className="text-lg font-semibold">Signature setup</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Rich-text signature for this run. It is appended when sending outreach and reply drafts. After you save, if
              a signature is set, outreach and reply draft previews add{" "}
              <span className="font-mono text-xs">[Signature]</span> on its own line at the end.
            </p>
            <div className="mt-4">
              <EmailDraftRichTextEditor
                key={signatureEditorKey}
                initialBody={signatureFormHtml}
                onChange={setSignatureFormHtml}
              />
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <Button variant="outline" onClick={() => setSignatureSetupOpen(false)}>
                Cancel
              </Button>
              <Button onClick={() => void saveSignatureSetup()}>Save</Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
