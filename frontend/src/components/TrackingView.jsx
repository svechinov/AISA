import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { EmailDraftBodyPreview } from "@/components/EmailDraftBodyPreview";
import { EmailDraftRichTextEditor } from "@/components/EmailDraftRichTextEditor";
import {
  DraftAssetAttachmentsField,
  normalizeAttachedAssetIds,
} from "@/components/DraftAssetAttachmentsField";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { NativeFilterSelect } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Input } from "@/components/ui/input";
import {
  AlertCircle,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  CircleAlert,
  Clock,
  Eye,
  EyeOff,
  FilePenLine,
  MailCheck,
  MailWarning,
  Mails,
  Pencil,
  Reply,
  RefreshCw,
  Send,
  Upload,
  Loader2,
  X,
} from "lucide-react";
import DOMPurify from "dompurify";
import { assetIsCdnUpload } from "@/lib/assetCdn";
import { cn } from "@/lib/utils";
import {
  snapshotMergeWriteInnerTabs,
  snapshotMergeWriteRunPanelLite,
  snapshotReadInnerTabCounts,
  snapshotReadRunPanelLite,
} from "@/lib/humanUiSnapshot";
import {
  buildEventsPanelLite,
  buildThreadPanelLiteRows,
  filterEventsPanelLiteByTab,
  filterThreadPanelLiteByTab,
  sortThreadPanelLiteRows,
} from "@/lib/runPanelLite";
import { fetchAllPagedItems } from "@/lib/paginatedApi";

/** Match backend `looks_like_html_fragment`: render as HTML when sanitizer applies. */
function threadMessageBodyLooksLikeHtml(s) {
  return /<\s*[a-zA-Z!/]/.test(String(s ?? "").trim());
}

const ENV_API = import.meta.env.VITE_API_BASE?.trim();
const API_BASE =
  ENV_API && ENV_API.length > 0
    ? ENV_API.replace(/\/$/, "")
    : import.meta.env.DEV
      ? "/api"
      : "http://127.0.0.1:8000";

/** Background refresh while Tracking is mounted — gentler than 3s to avoid piling up with Human UI polls. */
const TRACKING_POLL_MS_ACTIVE = 10_000;
const TRACKING_POLL_MS_DEFAULT = 15_000;

function trackingPollIntervalMs(displayPhase) {
  return displayPhase === "Active" ? TRACKING_POLL_MS_ACTIVE : TRACKING_POLL_MS_DEFAULT;
}

const THREAD_CLASS_LABELS = {
  interested: "Interested",
  not_interested: "Not interested",
  ask_later: "Ask later",
  need_more_info: "Need info",
  unclear: "Unclear",
};

const REMINDER_ACTIVE_STATUSES = ["scheduled", "triggered", "snoozed"];

function toDatetimeLocalValue(d) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const ASSET_LIBRARY_TYPE_OPTS = [
  { value: "deck", label: "Deck" },
  { value: "screener", label: "Screener" },
  { value: "one_pager", label: "One-pager" },
  { value: "catalog", label: "Catalog" },
  { value: "website", label: "Website" },
  { value: "other", label: "Other" },
];

function threadClassificationBadgeClass(label) {
  if (label === "interested") return "bg-green-600 hover:bg-green-600";
  if (label === "not_interested") return "bg-red-600 hover:bg-red-600";
  if (label === "ask_later") return "bg-amber-600 hover:bg-amber-600";
  if (label === "need_more_info") return "bg-blue-600 hover:bg-blue-600";
  if (label === "unclear") return "bg-slate-500 hover:bg-slate-500";
  return "";
}

/** Backend may leave `draft_id` null on import-first threads; `effective_draft_id` resolves the outreach draft. */
function threadOutboundDraftId(t) {
  if (t == null) return null;
  const id = t.effective_draft_id ?? t.draft_id;
  return id != null ? id : null;
}

function threadDeliveryLlmIssueLabel(issue) {
  const i = String(issue || "").toLowerCase();
  if (i === "bounce") return "Bounced (delivery failure)";
  if (i === "dead_mailbox") return "Dead mailbox";
  if (i === "none") return "No delivery issue";
  if (i === "unclear") return "Unclear";
  return issue || "—";
}

/** Maps LLM `delivery_issue` to manual mark kind for POST mark-bounced / mark-dead-mailbox. */
function llmDeliveryIssueToManualMarkKind(issue) {
  const i = String(issue || "").toLowerCase();
  if (i === "bounce" || i === "bounced" || i === "soft_bounce") return "bounced";
  if (i === "dead_mailbox" || i === "hard_bounce" || i === "invalid_mailbox" || i === "user_unknown") {
    return "dead_mailbox";
  }
  return null;
}

/** Snapshot-only for Events/Threads sub-tabs: all bucket counts zero → empty; no snapshot or any >0 → loading. */
function trackingAbdSnapMode(snap) {
  if (!snap || typeof snap !== "object") return "loading";
  const a = Number(snap.active) || 0;
  const b = Number(snap.bounced) || 0;
  const d = Number(snap.dead_mailbox) || 0;
  return a + b + d === 0 ? "empty" : "loading";
}

function TrackingCardsPlaceholder({ mode, kind }) {
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
      <p>{kind} data is loading…</p>
    </div>
  );
}

/** Cached thread row while full TrackingView load is in flight (open thread disabled until sync). */
function ThreadCardFromLite({ row }) {
  const isThreadDeadMailbox = row.is_dead_mailbox;
  const isThreadBounced = row.is_bounced && !isThreadDeadMailbox;
  const showInboundBadge = row.needs_inbound && !isThreadBounced && !isThreadDeadMailbox;
  const label = row.classification;
  const hasRem = row.has_reminder && row.remind_at;
  return (
    <div
      className={
        isThreadDeadMailbox
          ? "flex flex-col gap-3 rounded-2xl border-2 border-red-700/50 bg-red-950/10 p-5 dark:border-red-700/40 dark:bg-red-950/20 sm:flex-row sm:items-center sm:justify-between"
          : isThreadBounced
            ? "flex flex-col gap-3 rounded-2xl border-2 border-amber-600/45 bg-amber-950/15 p-5 dark:border-amber-600/40 dark:bg-amber-950/25 sm:flex-row sm:items-center sm:justify-between"
            : "flex flex-col gap-3 rounded-2xl border-2 border-border bg-muted/30 p-5 sm:flex-row sm:items-center sm:justify-between"
      }
    >
      <div>
        <div className="flex flex-wrap items-center gap-2">
          {isThreadDeadMailbox ? (
            <CircleAlert className="h-5 w-5 shrink-0 text-red-600 dark:text-red-400" aria-hidden />
          ) : isThreadBounced ? (
            <MailWarning className="h-5 w-5 shrink-0 text-amber-600 dark:text-amber-400" aria-hidden />
          ) : null}
          <div className="font-medium">{row.company || `Contact #${row.contact_id}`}</div>
          {isThreadBounced && !isThreadDeadMailbox ? (
            <Badge
              variant="outline"
              className="gap-1 border-amber-600/55 bg-amber-500/15 font-normal text-amber-950 dark:border-amber-500/50 dark:bg-amber-950/35 dark:text-amber-100"
              title="Outbound delivery failed (bounce)"
            >
              <MailWarning className="h-3.5 w-3.5 shrink-0 text-amber-700 dark:text-amber-300" aria-hidden />
              Bounced
            </Badge>
          ) : null}
          {showInboundBadge ? (
            <Badge
              variant="outline"
              className="gap-1 border-green-600/50 bg-green-600/15 font-normal text-green-800 dark:border-green-600/45 dark:bg-green-950/45 dark:text-green-300"
              title="Last message in this thread is inbound — needs your attention"
            >
              <AlertCircle className="h-3.5 w-3.5 shrink-0 text-green-600 dark:text-green-400" aria-hidden />
              Inbound
            </Badge>
          ) : null}
          {hasRem ? (
            <Badge
              variant="outline"
              className="gap-1 border-amber-600/60 bg-amber-500/15 font-normal text-amber-950 dark:border-amber-500/50 dark:bg-amber-950/40 dark:text-amber-100"
              title={`Reminder: ${new Date(row.remind_at).toLocaleString()}`}
            >
              <Clock className="h-3.5 w-3.5 shrink-0 text-amber-700 dark:text-amber-300" aria-hidden />
              Remind later
            </Badge>
          ) : null}
          {isThreadDeadMailbox ? (
            <Badge variant="destructive" className="font-normal text-xs">
              Dead mailbox
            </Badge>
          ) : null}
          {label ? (
            <Badge variant="default" className={`font-normal ${threadClassificationBadgeClass(label)}`}>
              {THREAD_CLASS_LABELS[label] || label}
            </Badge>
          ) : null}
        </div>
        <div className="mt-1 text-sm text-muted-foreground">
          {row.contact_name || "—"} · {row.subject || "No subject"}
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <Badge variant="secondary">{row.status}</Badge>
          <span>
            Out {row.msg_out} · In {row.msg_in}
          </span>
          {row.last_message_at ? (
            <span>Last: {new Date(row.last_message_at).toLocaleString()}</span>
          ) : null}
        </div>
      </div>
      <Button type="button" variant="outline" disabled title="Open thread after data sync completes">
        Open thread
      </Button>
    </div>
  );
}

export default function TrackingView({
  runId,
  runSignatureHtml = "",
  /** Run.context_json — persist UI flags under `_human_ui` */
  contextJson = {},
  activeTab,
  onActiveTabChange,
  singleTabMode = false,
  onRunWorkspaceRefresh,
  /** Sync Human UI draft chips / library when assets or run packets change (not polled with threads/events). */
  onStaticAssetsSynced,
  /** Optional: same Activity panel as Human UI — run switch / fetchStaticAssets trace. */
  onRunTraceLog,
  /** From workspace / run card: Preparing | Ready | Active | Closed — tighter poll only when Active. */
  workspaceDisplayPhase,
  /** From GET /setup/status — R2 env complete for POST /assets/upload */
  cdnR2UploadReady = false,
  /** Poll live threads/events/etc. only on Events / Threads — other tabs load once per visit. */
  pollLiveEnabled = false,
}) {
  const showSignaturePlaceholder = Boolean((runSignatureHtml ?? "").trim());
  const [events, setEvents] = useState([]);
  const [summary, setSummary] = useState(null);
  const [drafts, setDrafts] = useState([]);
  const [contacts, setContacts] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [threads, setThreads] = useState([]);
  const [runMessages, setRunMessages] = useState([]);
  /** Full bodies for thread modal — GET /email-threads/{id}/messages; run-wide list is preview-only. */
  const [threadModalMessagesFull, setThreadModalMessagesFull] = useState(null);
  const [threadModalId, setThreadModalId] = useState(null);
  /** "bounced" | "dead_mailbox" — second-step confirm for irreversible delivery marking */
  const [threadManualMarkConfirm, setThreadManualMarkConfirm] = useState(null);
  const [threadMarkBusy, setThreadMarkBusy] = useState(false);
  const [threadDeliveryLlmBusy, setThreadDeliveryLlmBusy] = useState(false);
  const [threadDeliveryLlmResult, setThreadDeliveryLlmResult] = useState(null);
  const [threadRemindAtLocal, setThreadRemindAtLocal] = useState("");
  const [threadBucketTab, setThreadBucketTab] = useState("active");
  const [eventBucketTab, setEventBucketTab] = useState("active");
  const [replyDrafts, setReplyDrafts] = useState([]);
  const [reminders, setReminders] = useState([]);
  const [assets, setAssets] = useState([]);
  const [assetPackets, setAssetPackets] = useState([]);
  const [newAssetName, setNewAssetName] = useState("");
  const [newAssetType, setNewAssetType] = useState("deck");
  const [newAssetUrl, setNewAssetUrl] = useState("");
  const [uploadAssetName, setUploadAssetName] = useState("");
  const [uploadAssetType, setUploadAssetType] = useState("deck");
  const [uploadPick, setUploadPick] = useState(null);
  const [uploadBusy, setUploadBusy] = useState(false);
  const uploadFileInputRef = useRef(null);
  /** packet assets edit session: draft list + library picker + title */
  const [packetEditState, setPacketEditState] = useState(null);
  const [packetToDelete, setPacketToDelete] = useState(null);
  const [newPacketForm, setNewPacketForm] = useState({
    title: "",
    draftAssets: [],
    addPick: "",
  });
  const [createPacketBusy, setCreatePacketBusy] = useState(false);
  /** reply draft id → send-preview fields + attachment summary */
  const [replySendPreviewByDraftId, setReplySendPreviewByDraftId] = useState({});
  /** When false, send-preview block is collapsed even if data is cached */
  const [replyPreviewExpanded, setReplyPreviewExpanded] = useState({});
  const [replyEditing, setReplyEditing] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  /** After first successful load for this run — thread/event sub-tab counts use live data, not snapshot. */
  const [trackingCountsReady, setTrackingCountsReady] = useState(false);
  const [innerTab, setInnerTab] = useState("events");
  /** Latest runId for stale guards after await in fetchStaticAssets / load. */
  const runIdRef = useRef(runId);
  runIdRef.current = runId;

  const trace = useCallback(
    (message, detail) => {
      onRunTraceLog?.(message, detail);
    },
    [onRunTraceLog],
  );

  useEffect(() => {
    setInnerTab(activeTab || "events");
  }, [runId, activeTab]);

  const eventChainCollapsedMap = useMemo(() => {
    const raw = contextJson?._human_ui?.event_chain_collapsed;
    const out = {};
    if (raw && typeof raw === "object" && !Array.isArray(raw)) {
      for (const [k, v] of Object.entries(raw)) {
        out[String(k)] = Boolean(v);
      }
    }
    return out;
  }, [runId, contextJson?._human_ui?.event_chain_collapsed]);

  const tabValue = activeTab || innerTab;
  const handleTabChange = (v) => {
    setInnerTab(v);
    onActiveTabChange?.(v);
  };

  const fetchLiveData = useCallback(async () => {
    if (!runId) return;
    const getJson = async (pathWithQuery) => {
      const r = await fetch(`${API_BASE}${pathWithQuery}`);
      return r.ok ? r.json() : [];
    };
    /** Paged lists must not take down the whole Tracking bundle if one endpoint errors or times out. */
    const safePaged = async (basePath) => {
      try {
        return await fetchAllPagedItems(getJson, basePath);
      } catch {
        return [];
      }
    };
    const [er, sr, rt, msg, rep, rem, c, d, threadsRows] = await Promise.all([
      fetch(`${API_BASE}/email-events/run/${runId}`).catch(() => null),
      fetch(`${API_BASE}/sending/runs/${runId}/summary`).catch(() => null),
      fetch(`${API_BASE}/research-tasks/run/${runId}`).catch(() => null),
      fetch(`${API_BASE}/email-threads/run/${runId}/messages`).catch(() => null),
      fetch(`${API_BASE}/reply-drafts/run/${runId}`).catch(() => null),
      fetch(`${API_BASE}/reminders/run/${runId}`).catch(() => null),
      safePaged(`/contacts/run/${runId}`),
      safePaged(`/email-drafts/run/${runId}`),
      safePaged(`/email-threads/run/${runId}`),
    ]);
    let e = [];
    try {
      e = er && er.ok ? await er.json() : [];
    } catch {
      e = [];
    }
    setEvents(Array.isArray(e) ? e : []);

    let s = null;
    try {
      s = sr && sr.ok ? await sr.json() : null;
    } catch {
      s = null;
    }
    setSummary(s || null);

    setDrafts(Array.isArray(d) ? d : []);

    setContacts(Array.isArray(c) ? c : []);

    let t = [];
    try {
      t = rt && rt.ok ? await rt.json() : [];
    } catch {
      t = [];
    }
    setTasks(Array.isArray(t) ? t : []);

    setThreads(Array.isArray(threadsRows) ? threadsRows : []);
    let msgData = [];
    try {
      msgData = msg && msg.ok ? await msg.json() : [];
    } catch {
      msgData = [];
    }
    setRunMessages(Array.isArray(msgData) ? msgData : []);
    let repData = [];
    try {
      repData = rep && rep.ok ? await rep.json() : [];
    } catch {
      repData = [];
    }
    setReplyDrafts(Array.isArray(repData) ? repData : []);
    let remData = [];
    try {
      remData = rem && rem.ok ? await rem.json() : [];
    } catch {
      remData = [];
    }
    setReminders(Array.isArray(remData) ? remData : []);
    try {
      const threadsLite = sortThreadPanelLiteRows(
        buildThreadPanelLiteRows(
          Array.isArray(threadsRows) ? threadsRows : [],
          Array.isArray(c) ? c : [],
          Array.isArray(d) ? d : [],
          Array.isArray(msgData) ? msgData : [],
          Array.isArray(remData) ? remData : [],
        ),
      );
      const eventsLite = buildEventsPanelLite(
        Array.isArray(e) ? e : [],
        Array.isArray(d) ? d : [],
        Array.isArray(c) ? c : [],
      );
      snapshotMergeWriteRunPanelLite(runId, {
        threads: threadsLite,
        eventsGroups: eventsLite,
      });
    } catch {
      /* lite snapshot is best-effort */
    }
  }, [runId]);

  const fetchStaticAssets = useCallback(async () => {
    if (!runId) return;
    const startedRun = runId;
    trace("fetchStaticAssets start", {
      startedRun,
      requests: ["GET /assets", `GET /asset-packets/run/${startedRun}`],
    });
    try {
      const [ast, apk] = await Promise.all([
        fetch(`${API_BASE}/assets`),
        fetch(`${API_BASE}/asset-packets/run/${startedRun}`),
      ]);
      if (runIdRef.current !== startedRun) {
        trace("fetchStaticAssets discard (run changed after fetch headers)", {
          startedRun,
          currentRun: runIdRef.current,
        });
        return;
      }
      if (!ast.ok || !apk.ok) {
        const parts = [];
        if (!ast.ok) {
          parts.push(`GET /assets ${ast.status}: ${(await ast.text()).slice(0, 240)}`);
        }
        if (!apk.ok) {
          parts.push(
            `GET /asset-packets/run/${startedRun} ${apk.status}: ${(await apk.text()).slice(0, 240)}`,
          );
        }
        if (ast.ok && !apk.ok) {
          try {
            await ast.json();
          } catch {
            /* discard body */
          }
        }
        if (apk.ok && !ast.ok) {
          try {
            await apk.json();
          } catch {
            /* discard body */
          }
        }
        if (runIdRef.current !== startedRun) {
          trace("fetchStaticAssets discard after HTTP error bodies", {
            startedRun,
            currentRun: runIdRef.current,
          });
          return;
        }
        trace("fetchStaticAssets HTTP error (local UI keeps prior rows until success)", {
          startedRun,
          message: parts.join(" · "),
        });
        setError(parts.join(" · "));
        return;
      }
      const astData = await ast.json();
      const apkData = await apk.json();
      if (runIdRef.current !== startedRun) {
        trace("fetchStaticAssets discard (run changed after JSON)", {
          startedRun,
          currentRun: runIdRef.current,
        });
        return;
      }
      const assets = Array.isArray(astData) ? astData : [];
      const packets = Array.isArray(apkData) ? apkData : [];
      trace("fetchStaticAssets apply", {
        startedRun,
        assetsCount: assets.length,
        packetsCount: packets.length,
        packetIds: packets.slice(0, 8).map((p) => p?.id),
      });
      setAssets(assets);
      setAssetPackets(packets);
      onStaticAssetsSynced?.({ assets, packets, runId: startedRun });
    } catch (e) {
      if (runIdRef.current !== startedRun) {
        trace("fetchStaticAssets catch ignored (stale run)", {
          startedRun,
          currentRun: runIdRef.current,
        });
        return;
      }
      trace("fetchStaticAssets catch", { startedRun, err: String(e?.message || e) });
      setError(String(e?.message || e || "Failed to load assets / packets"));
    }
  }, [runId, onStaticAssetsSynced, trace]);

  const load = useCallback(async () => {
    if (!runId) return;
    trace("load() start", { runId });
    setLoading(true);
    setError("");
    let ok = false;
    try {
      // Load assets/packets first so the Assets tab is not blocked by many parallel /run/* requests
      // (browser HTTP/1.1 connection limits can delay starting GET /assets otherwise).
      await fetchStaticAssets();
      await fetchLiveData();
      ok = true;
    } catch (err) {
      const msg = String(err?.message || err || "");
      const transient =
        /failed to fetch/i.test(msg) ||
        /load failed|networkerror|network request failed|aborted|abort$/i.test(msg);
      if (transient) {
        console.warn("[TrackingView] refresh skipped (transient):", msg);
      } else {
        setError(msg);
      }
    } finally {
      setLoading(false);
      if (ok) setTrackingCountsReady(true);
      if (ok) trace("load() finished OK", { runId });
    }
  }, [runId, fetchLiveData, fetchStaticAssets, trace]);

  /** Threads, events, drafts, reminders — polled; does not hit /assets or /asset-packets. */
  const loadLive = useCallback(async () => {
    if (!runId) return;
    setLoading(true);
    setError("");
    let ok = false;
    try {
      await fetchLiveData();
      if (threadModalId != null) {
        try {
          const tr = await fetch(`${API_BASE}/email-threads/${threadModalId}/messages`);
          const tm = tr.ok ? await tr.json() : [];
          setThreadModalMessagesFull(Array.isArray(tm) ? tm : []);
        } catch {
          /* keep modal list */
        }
      }
      ok = true;
    } catch (err) {
      const msg = String(err?.message || err || "");
      const transient =
        /failed to fetch/i.test(msg) ||
        /load failed|networkerror|network request failed|aborted|abort$/i.test(msg);
      if (transient) {
        console.warn("[TrackingView] refresh skipped (transient):", msg);
      } else {
        setError(msg);
      }
    } finally {
      setLoading(false);
      if (ok) setTrackingCountsReady(true);
    }
  }, [runId, fetchLiveData, threadModalId]);

  useEffect(() => {
    setTrackingCountsReady(false);
    if (!runId) {
      setEvents([]);
      setSummary(null);
      setDrafts([]);
      setContacts([]);
      setTasks([]);
      setThreads([]);
      setRunMessages([]);
      setThreadModalMessagesFull(null);
      setReplyDrafts([]);
      setReminders([]);
      setAssets([]);
      setAssetPackets([]);
      setNewAssetName("");
      setNewAssetType("deck");
      setNewAssetUrl("");
      setPacketEditState(null);
      setPacketToDelete(null);
      setNewPacketForm({ title: "", draftAssets: [], addPick: "" });
      setReplySendPreviewByDraftId({});
      setReplyEditing(null);
      setThreadModalId(null);
      setThreadBucketTab("active");
      setEventBucketTab("active");
      return;
    }
    trace("Tracking mount effect: runId changed — load() (do not clear assets/packets before fetch)", {
      runId,
    });
    void load();
    // Do not depend on activeTab: each inner-tab switch re-ran load(), overlapping requests and
    // fighting with the parent Human UI assets fetch. runId + load is enough.
  }, [runId, load, trace]);

  useEffect(() => {
    if (!runId || !pollLiveEnabled) return;
    const pollMs = trackingPollIntervalMs(workspaceDisplayPhase);
    const i = setInterval(() => {
      if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
      void loadLive();
    }, pollMs);
    return () => clearInterval(i);
  }, [runId, loadLive, workspaceDisplayPhase, pollLiveEnabled]);

  useEffect(() => {
    if (threadModalId == null) {
      setThreadModalMessagesFull(null);
      setThreadRemindAtLocal("");
      return;
    }
    const d = new Date();
    d.setDate(d.getDate() + 3);
    d.setHours(9, 0, 0, 0);
    setThreadRemindAtLocal(toDatetimeLocalValue(d));
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(`${API_BASE}/email-threads/${threadModalId}/messages`);
        if (!r.ok || cancelled) return;
        const rows = await r.json();
        if (!cancelled) setThreadModalMessagesFull(Array.isArray(rows) ? rows : []);
      } catch {
        if (!cancelled) setThreadModalMessagesFull(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [threadModalId]);

  useEffect(() => {
    setThreadDeliveryLlmResult(null);
  }, [threadModalId]);

  const eventTone = (type) => {
    if (type === "sent")
      return "border-2 border-green-200 bg-green-100 text-green-700 dark:border-green-800 dark:bg-green-950/40 dark:text-green-200";
    if (type === "queued")
      return "border-2 border-slate-200 bg-slate-100 text-slate-800 dark:border-slate-600 dark:bg-slate-900/50 dark:text-slate-200";
    if (type === "replied")
      return "border-2 border-blue-200 bg-blue-100 text-blue-700 dark:border-blue-800 dark:bg-blue-950/40 dark:text-blue-200";
    if (type === "bounced")
      return "border-2 border-yellow-200 bg-yellow-100 text-yellow-800 dark:border-yellow-700 dark:bg-yellow-950/40 dark:text-yellow-100";
    if (type === "dead_mailbox")
      return "border-2 border-red-700/50 bg-red-950/10 text-red-600 dark:border-red-700/40 dark:bg-red-950/20 dark:text-red-400";
    if (type === "failed")
      return "border-2 border-red-200 bg-red-100 text-red-700 dark:border-red-800 dark:bg-red-950/40 dark:text-red-200";
    if (type === "reply_sent")
      return "border-2 border-teal-200 bg-teal-100 text-teal-800 dark:border-teal-700 dark:bg-teal-950/40 dark:text-teal-200";
    return "border-2 border-border bg-muted text-muted-foreground";
  };

  const eventIcon = (type) => {
    if (type === "sent") return <Send className="h-4 w-4" />;
    if (type === "replied") return <Reply className="h-4 w-4" />;
    if (type === "bounced") return <MailWarning className="h-4 w-4" />;
    if (type === "dead_mailbox")
      return <CircleAlert className="h-4 w-4 text-red-600 dark:text-red-400" aria-hidden />;
    if (type === "failed") return <AlertTriangle className="h-4 w-4" />;
    if (type === "reply_sent") return <Reply className="h-4 w-4" />;
    return <MailCheck className="h-4 w-4" />;
  };

  const contactById = useMemo(() => new Map(contacts.map((c) => [c.id, c])), [contacts]);

  const draftById = useMemo(() => new Map(drafts.map((d) => [d.id, d])), [drafts]);

  /** Earliest active reminder per thread (from thread modal). */
  const activeThreadReminderByThreadId = useMemo(() => {
    const m = new Map();
    for (const r of reminders) {
      if (!r.thread_id || !REMINDER_ACTIVE_STATUSES.includes(r.status)) continue;
      const prev = m.get(r.thread_id);
      const t = new Date(r.remind_at).getTime();
      if (!prev || t < new Date(prev.remind_at).getTime()) {
        m.set(r.thread_id, r);
      }
    }
    return m;
  }, [reminders]);

  const isThreadDeadMailboxRow = useCallback(
    (t) => {
      const contact = contactById.get(t.contact_id);
      const did = threadOutboundDraftId(t);
      const linkedDraft = did != null ? draftById.get(did) : undefined;
      const draftLifecycle = linkedDraft
        ? linkedDraft.tracking_status ?? linkedDraft.status
        : null;
      return draftLifecycle === "dead_mailbox" || contact?.email_health === "dead_mailbox";
    },
    [contactById, draftById],
  );

  const isThreadBouncedRow = useCallback(
    (t) => {
      const contact = contactById.get(t.contact_id);
      const did = threadOutboundDraftId(t);
      const linkedDraft = did != null ? draftById.get(did) : undefined;
      const tracking = linkedDraft ? linkedDraft.tracking_status : null;
      return tracking === "bounced" || contact?.email_health === "bounced";
    },
    [contactById, draftById],
  );

  /** For sort: 0 = normal, 1 = bounced (near bottom), 2 = dead mailbox (bottom). */
  const threadListBottomTier = useCallback(
    (t) => {
      if (isThreadDeadMailboxRow(t)) return 2;
      if (isThreadBouncedRow(t)) return 1;
      return 0;
    },
    [isThreadDeadMailboxRow, isThreadBouncedRow],
  );

  const filteredThreads = useMemo(() => {
    if (threadBucketTab === "dead_mailbox") {
      return threads.filter((t) => isThreadDeadMailboxRow(t));
    }
    if (threadBucketTab === "bounced") {
      return threads.filter((t) => isThreadBouncedRow(t));
    }
    return threads.filter((t) => !isThreadBouncedRow(t) && !isThreadDeadMailboxRow(t));
  }, [threads, threadBucketTab, isThreadDeadMailboxRow, isThreadBouncedRow]);

  const threadBucketCounts = useMemo(
    () => ({
      active: threads.filter((t) => !isThreadBouncedRow(t) && !isThreadDeadMailboxRow(t)).length,
      bounced: threads.filter((t) => isThreadBouncedRow(t)).length,
      dead_mailbox: threads.filter((t) => isThreadDeadMailboxRow(t)).length,
    }),
    [threads, isThreadBouncedRow, isThreadDeadMailboxRow],
  );

  /** Last message in thread is inbound → “ball in our court”, show badge and pin to top. */
  const threadNeedsInboundAttention = useMemo(() => {
    const byThread = new Map();
    for (const msg of runMessages) {
      if (!byThread.has(msg.thread_id)) byThread.set(msg.thread_id, []);
      byThread.get(msg.thread_id).push(msg);
    }
    const need = new Map();
    for (const [tid, arr] of byThread) {
      arr.sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
      const last = arr[arr.length - 1];
      need.set(tid, last?.direction === "inbound");
    }
    return need;
  }, [runMessages]);

  const sortedFilteredThreads = useMemo(() => {
    const list = [...filteredThreads];
    list.sort((a, b) => {
      const aTier = threadListBottomTier(a);
      const bTier = threadListBottomTier(b);
      if (aTier !== bTier) return aTier - bTier;
      const aAtt = threadNeedsInboundAttention.get(a.id) ? 1 : 0;
      const bAtt = threadNeedsInboundAttention.get(b.id) ? 1 : 0;
      if (aAtt !== bAtt) return bAtt - aAtt;
      const aRm = activeThreadReminderByThreadId.has(a.id) ? 1 : 0;
      const bRm = activeThreadReminderByThreadId.has(b.id) ? 1 : 0;
      if (aRm !== bRm) return bRm - aRm;
      const ta = a.last_message_at ? new Date(a.last_message_at).getTime() : 0;
      const tb = b.last_message_at ? new Date(b.last_message_at).getTime() : 0;
      if (tb !== ta) return tb - ta;
      return b.id - a.id;
    });
    return list;
  }, [
    filteredThreads,
    threadListBottomTier,
    threadNeedsInboundAttention,
    activeThreadReminderByThreadId,
  ]);

  const messageCountsByThreadId = useMemo(() => {
    const m = new Map();
    for (const msg of runMessages) {
      if (!m.has(msg.thread_id)) {
        m.set(msg.thread_id, { in: 0, out: 0 });
      }
      const row = m.get(msg.thread_id);
      if (msg.direction === "inbound") row.in += 1;
      else row.out += 1;
    }
    return m;
  }, [runMessages]);

  const isReplacementDraft = useCallback(
    (d) => {
      if (!d?.contact_id) return false;
      const c = contactById.get(d.contact_id);
      return c?.source_json?.source === "replacement_search";
    },
    [contactById],
  );

  const groupedEvents = useMemo(() => {
    const map = new Map();
    for (const event of events) {
      if (!map.has(event.draft_id)) map.set(event.draft_id, []);
      map.get(event.draft_id).push(event);
    }
    for (const [, list] of map) {
      list.sort((a, b) => a.id - b.id);
    }
    const entries = Array.from(map.entries())
      .map(([draftId, draftEvents]) => {
        const draft = drafts.find((d) => d.id === draftId);
        return { draftId, draft, events: draftEvents };
      })
      .sort((a, b) => a.draftId - b.draftId);
    return entries;
  }, [events, drafts]);

  const eventGroupTabBucket = useCallback(
    (group) => {
      const { draft, events: draftEvents } = group;
      const contact =
        draft?.contact_id != null ? contactById.get(draft.contact_id) : undefined;
      const draftLifecycle = draft ? draft.tracking_status ?? draft.status : null;
      const last = draftEvents?.length ? draftEvents[draftEvents.length - 1] : null;
      const isDead =
        draftLifecycle === "dead_mailbox" ||
        contact?.email_health === "dead_mailbox" ||
        last?.event_type === "dead_mailbox";
      const isBounced =
        draft?.tracking_status === "bounced" ||
        contact?.email_health === "bounced" ||
        last?.event_type === "bounced";
      if (isDead) return "dead_mailbox";
      if (isBounced) return "bounced";
      return "active";
    },
    [contactById],
  );

  const eventBucketCounts = useMemo(() => {
    let active = 0;
    let bounced = 0;
    let dead_mailbox = 0;
    for (const g of groupedEvents) {
      const b = eventGroupTabBucket(g);
      if (b === "dead_mailbox") dead_mailbox += 1;
      else if (b === "bounced") bounced += 1;
      else active += 1;
    }
    return { active, bounced, dead_mailbox };
  }, [groupedEvents, eventGroupTabBucket]);

  const displayThreadBucketCounts = useMemo(() => {
    if (trackingCountsReady) return threadBucketCounts;
    const snap = runId ? snapshotReadInnerTabCounts(runId)?.threads : null;
    return snap ?? { active: 0, bounced: 0, dead_mailbox: 0 };
  }, [trackingCountsReady, threadBucketCounts, runId]);

  const displayEventBucketCounts = useMemo(() => {
    if (trackingCountsReady) return eventBucketCounts;
    const snap = runId ? snapshotReadInnerTabCounts(runId)?.events : null;
    return snap ?? { active: 0, bounced: 0, dead_mailbox: 0 };
  }, [trackingCountsReady, eventBucketCounts, runId]);

  useEffect(() => {
    if (!runId || !trackingCountsReady) return;
    snapshotMergeWriteInnerTabs(runId, { threads: threadBucketCounts, events: eventBucketCounts });
  }, [runId, trackingCountsReady, threadBucketCounts, eventBucketCounts]);

  const eventsTrackingListMode = useMemo(() => {
    const ev = runId ? snapshotReadInnerTabCounts(runId)?.events : null;
    return trackingAbdSnapMode(ev);
  }, [runId, trackingCountsReady, eventBucketCounts]);
  const threadsTrackingListMode = useMemo(() => {
    const th = runId ? snapshotReadInnerTabCounts(runId)?.threads : null;
    return trackingAbdSnapMode(th);
  }, [runId, trackingCountsReady, threadBucketCounts]);

  const runPanelLiteSnapshot = useMemo(
    () => (runId ? snapshotReadRunPanelLite(runId) : null),
    [runId, trackingCountsReady],
  );

  const filteredThreadPanelLiteRows = useMemo(
    () => filterThreadPanelLiteByTab(runPanelLiteSnapshot?.threads || [], threadBucketTab),
    [runPanelLiteSnapshot?.threads, threadBucketTab],
  );

  const filteredEventsPanelLiteRows = useMemo(
    () => filterEventsPanelLiteByTab(runPanelLiteSnapshot?.eventsGroups || [], eventBucketTab),
    [runPanelLiteSnapshot?.eventsGroups, eventBucketTab],
  );

  const filteredGroupedEvents = useMemo(() => {
    return groupedEvents.filter((g) => eventGroupTabBucket(g) === eventBucketTab);
  }, [groupedEvents, eventBucketTab, eventGroupTabBucket]);

  /** Align with Run performance «Dead mailboxes» (dead-mailbox delivery) — not «bounced» (separate Contacts tab). */
  const deadContacts = useMemo(() => {
    return contacts.filter((c) => c.email_health === "dead_mailbox");
  }, [contacts]);

  const replacementQueueTasks = useMemo(() => {
    return tasks.filter(
      (t) =>
        t.task_type === "find_replacement_email" &&
        ["open", "running", "failed", "no_result"].includes(t.status),
    );
  }, [tasks]);

  const replyRate = useMemo(() => {
    if (!summary?.drafts_sent) return 0;
    return Math.round(((summary.events_replied || 0) / summary.drafts_sent) * 100);
  }, [summary]);

  const pendingReplacementForContact = useCallback(
    (contactId) =>
      tasks.find(
        (t) =>
          t.contact_id === contactId &&
          t.task_type === "find_replacement_email" &&
          ["open", "running", "failed", "no_result"].includes(t.status),
      ),
    [tasks],
  );

  const replacementContactForSource = useCallback(
    (sourceContactId) =>
      contacts.find(
        (c) =>
          c.source_json?.source === "replacement_search" &&
          Number(c.source_json?.replaces_contact_id) === Number(sourceContactId),
      ),
    [contacts],
  );

  async function waitForDraftTerminalAfterQueuedSend(draftId) {
    await new Promise((r) => setTimeout(r, 400));
    for (let i = 0; i < 35; i++) {
      try {
        const res = await fetch(`${API_BASE}/email-drafts/${draftId}`, { cache: "no-store" });
        if (!res.ok) break;
        const d = await res.json();
        if (d && ["sent", "failed"].includes(d.status)) break;
      } catch {
        break;
      }
      await new Promise((r) => setTimeout(r, 2000));
    }
  }

  async function waitForBulkSendNoSending(runId) {
    await new Promise((r) => setTimeout(r, 500));
    for (let i = 0; i < 60; i++) {
      try {
        const res = await fetch(`${API_BASE}/email-drafts/run/${runId}?limit=500&offset=0`, {
          cache: "no-store",
        });
        if (!res.ok) break;
        const data = await res.json();
        const items = Array.isArray(data) ? data : data?.items ?? [];
        if (i >= 2 && !items.some((x) => x.status === "sending")) break;
      } catch {
        break;
      }
      await new Promise((r) => setTimeout(r, 2000));
    }
  }

  async function sendSingleDraft(draftId) {
    try {
      const res = await fetch(`${API_BASE}/sending/drafts/${draftId}/send`, { method: "POST" });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        setError(detail?.detail ? String(detail.detail) : `Send failed (${res.status})`);
        return;
      }
      await res.json();
      await waitForDraftTerminalAfterQueuedSend(draftId);
      await loadLive();
    } catch {
      setError("Send failed — check network / backend.");
    }
  }

  async function sendApprovedDrafts() {
    if (!runId) return;
    try {
      const res = await fetch(`${API_BASE}/sending/runs/${runId}/send`, { method: "POST" });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        setError(detail?.detail ? String(detail.detail) : `Batch send failed (${res.status})`);
        return;
      }
      await res.json();
      await waitForBulkSendNoSending(runId);
      await loadLive();
    } catch {
      setError("Batch send failed — check network / backend.");
    }
  }

  async function generateReplacementDrafts() {
    if (!runId) return;
    setError("");
    try {
      const res = await fetch(`${API_BASE}/runs/${runId}/generate-replacement-drafts`, { method: "POST" });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        setError(detail?.detail ? String(detail.detail) : `Generate drafts failed (${res.status})`);
        return;
      }
      await res.json();
      await loadLive();
    } catch {
      setError("Generate replacement drafts failed — check network / backend.");
    }
  }

  async function sendReplacementDrafts() {
    if (!runId) return;
    setError("");
    try {
      const res = await fetch(`${API_BASE}/runs/${runId}/send-replacement-drafts`, { method: "POST" });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        setError(detail?.detail ? String(detail.detail) : `Send replacement drafts failed (${res.status})`);
        return;
      }
      await res.json();
      await loadLive();
    } catch {
      setError("Send replacement drafts failed — check network / backend.");
    }
  }

  async function persistEventChainCollapsed(draftId, collapsed) {
    if (!runId || draftId == null) return;
    const id = String(draftId);
    setError("");
    try {
      const res = await fetch(`${API_BASE}/runs/${runId}/human-ui`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ event_chain_collapsed: { [id]: collapsed } }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        setError(detail?.detail ? String(detail.detail) : `Save UI state failed (${res.status})`);
        return;
      }
      onRunWorkspaceRefresh?.();
    } catch {
      setError("Could not save events panel state — check network.");
    }
  }

  async function confirmThreadManualMark() {
    if (!threadModalId || !threadManualMarkConfirm) return;
    const kind = threadManualMarkConfirm;
    setThreadMarkBusy(true);
    setError("");
    try {
      const path =
        kind === "bounced"
          ? `/email-threads/${threadModalId}/mark-bounced`
          : `/email-threads/${threadModalId}/mark-dead-mailbox`;
      const res = await fetch(`${API_BASE}${path}`, { method: "POST" });
      if (!res.ok) {
        const text = await res.text();
        let msg = text || `Request failed (${res.status})`;
        try {
          const j = JSON.parse(text);
          if (j.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
        } catch {
          /* plain */
        }
        throw new Error(msg);
      }
      setThreadManualMarkConfirm(null);
      setThreadDeliveryLlmResult(null);
      setThreadModalId(null);
      setThreadBucketTab(kind === "bounced" ? "bounced" : "dead_mailbox");
      await loadLive();
      onRunWorkspaceRefresh?.();
    } catch (e) {
      setError(String(e?.message || e));
      setThreadManualMarkConfirm(null);
    } finally {
      setThreadMarkBusy(false);
    }
  }

  async function analyzeThreadDeliveryWithLlm() {
    if (threadModalId == null) return;
    setThreadDeliveryLlmBusy(true);
    setThreadDeliveryLlmResult(null);
    setError("");
    try {
      const res = await fetch(`${API_BASE}/email-threads/${threadModalId}/analyze-delivery-llm`, {
        method: "POST",
        headers: { Accept: "application/json" },
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(
          data?.detail != null
            ? String(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail))
            : `Delivery analysis failed (${res.status})`,
        );
        return;
      }
      setThreadDeliveryLlmResult(data);
    } catch {
      setError("Delivery analysis failed — check network.");
    } finally {
      setThreadDeliveryLlmBusy(false);
    }
  }

  async function createReplacementTask(contact) {
    if (pendingReplacementForContact(contact.id) || replacementContactForSource(contact.id)) return;
    try {
      const res = await fetch(`${API_BASE}/research-tasks/run/${runId}/find-replacement`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ contact_id: contact.id }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        setError(detail?.detail ? String(detail.detail) : `Create task failed (${res.status})`);
        return;
      }
      const task = await res.json();
      setTasks((prev) => {
        if (prev.some((t) => t.id === task.id)) {
          return prev.map((t) => (t.id === task.id ? task : t));
        }
        return [...prev, task];
      });
    } catch {
      setError("Create replacement task failed — check network / backend.");
    }
  }

  async function rerunResearchTask(task) {
    const snapshot = { ...task };
    setError("");
    setTasks((prev) => prev.map((t) => (t.id === task.id ? { ...t, status: "running" } : t)));
    try {
      const res = await fetch(`${API_BASE}/research-tasks/${task.id}/rerun`, { method: "POST" });
      if (!res.ok) {
        setTasks((prev) => prev.map((t) => (t.id === task.id ? snapshot : t)));
        const detail = await res.json().catch(() => ({}));
        setError(detail?.detail ? String(detail.detail) : `Re-run failed (${res.status})`);
        return;
      }
      const data = await res.json();
      const taskPayload = data.task;
      if (taskPayload) {
        setTasks((prev) => prev.map((t) => (t.id === taskPayload.id ? taskPayload : t)));
      }
      await loadLive();
    } catch {
      setTasks((prev) => prev.map((t) => (t.id === task.id ? snapshot : t)));
      setError("Re-run failed — check network / backend.");
    }
  }

  const canShowSend = (draft) =>
    draft &&
    ["draft", "failed"].includes(draft.status) &&
    ["approved", "edited"].includes(draft.review_status) &&
    !!(draft.to_email || "").trim();

  const canSendReplyDraft = (rd) =>
    rd &&
    ["draft", "failed"].includes(rd.status) &&
    ["approved", "edited"].includes(rd.review_status) &&
    !!(rd.to_email || "").trim();

  async function generateReplyDraftForThread(threadId) {
    setError("");
    try {
      const res = await fetch(`${API_BASE}/reply-drafts/thread/${threadId}/generate`, { method: "POST" });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        setError(detail?.detail ? String(detail.detail) : `Generate failed (${res.status})`);
        return;
      }
      await res.json();
      await loadLive();
    } catch {
      setError("Generate reply draft failed — check network / backend.");
    }
  }

  async function patchReminderStatus(reminderId, status) {
    setError("");
    try {
      const res = await fetch(`${API_BASE}/reminders/${reminderId}/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        setError(detail?.detail ? String(detail.detail) : `Reminder update failed (${res.status})`);
        return;
      }
      await loadLive();
      onRunWorkspaceRefresh?.();
    } catch {
      setError("Reminder update failed.");
    }
  }

  async function snoozeReminderOneDay(reminder) {
    setError("");
    const d = new Date(reminder.remind_at);
    d.setDate(d.getDate() + 1);
    try {
      const res = await fetch(`${API_BASE}/reminders/${reminder.id}/snooze`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ remind_at: d.toISOString() }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        setError(detail?.detail ? String(detail.detail) : `Snooze failed (${res.status})`);
        return;
      }
      await loadLive();
      onRunWorkspaceRefresh?.();
    } catch {
      setError("Snooze failed.");
    }
  }

  async function submitNewAsset() {
    if (!(newAssetName || "").trim()) {
      setError("Asset name is required.");
      return;
    }
    setError("");
    try {
      const res = await fetch(`${API_BASE}/assets`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          asset_type: newAssetType,
          name: newAssetName.trim(),
          url: (newAssetUrl || "").trim() || null,
          description: null,
        }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        setError(detail?.detail ? String(detail.detail) : `Create asset failed (${res.status})`);
        return;
      }
      setNewAssetName("");
      setNewAssetUrl("");
      await fetchStaticAssets();
    } catch {
      setError("Create asset failed.");
    }
  }

  async function submitUploadAsset() {
    if (!(uploadAssetName || "").trim()) {
      setError("Asset name is required.");
      return;
    }
    if (!uploadPick) {
      setError("Choose a file to upload.");
      return;
    }
    setError("");
    setUploadBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", uploadPick);
      fd.append("name", uploadAssetName.trim());
      fd.append("asset_type", uploadAssetType);
      const res = await fetch(`${API_BASE}/assets/upload`, { method: "POST", body: fd });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        const msg = detail?.detail ? String(detail.detail) : `Upload failed (${res.status})`;
        setError(msg);
        return;
      }
      setUploadAssetName("");
      setUploadPick(null);
      if (uploadFileInputRef.current) {
        uploadFileInputRef.current.value = "";
      }
      await fetchStaticAssets();
    } catch {
      setError("Upload failed.");
    } finally {
      setUploadBusy(false);
    }
  }

  async function createReminderForThread(threadId) {
    if (!threadRemindAtLocal) {
      setError("Choose date and time for the reminder.");
      return;
    }
    const remindAt = new Date(threadRemindAtLocal);
    if (Number.isNaN(remindAt.getTime())) {
      setError("Invalid date/time.");
      return;
    }
    setError("");
    try {
      const res = await fetch(`${API_BASE}/reminders/thread/${threadId}/create`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ remind_at: remindAt.toISOString() }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(typeof data.detail === "string" ? data.detail : `Reminder failed (${res.status})`);
        return;
      }
      if (data.deduplicated) {
        setError("");
        await loadLive();
        onRunWorkspaceRefresh?.();
        return;
      }
      await loadLive();
      onRunWorkspaceRefresh?.();
    } catch {
      setError("Create reminder failed.");
    }
  }

  async function patchAssetPacket(packetId, body) {
    setError("");
    try {
      const res = await fetch(`${API_BASE}/asset-packets/${packetId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        setError(detail?.detail ? String(detail.detail) : `Update packet failed (${res.status})`);
        return;
      }
      await fetchStaticAssets();
    } catch {
      setError("Update asset packet failed.");
    }
  }

  function clonePacketAssetsForEdit(arr) {
    try {
      return structuredClone(arr);
    } catch {
      return JSON.parse(JSON.stringify(arr));
    }
  }

  function libraryRowToPacketSnapshot(a) {
    return {
      asset_id: a.id,
      title: a.name,
      name: a.name,
      description: a.description ?? null,
      asset_type: a.asset_type,
      url: a.url ?? null,
      file_path: a.file_path ?? null,
      download_url: a.download_url ?? null,
      storage_key: a.storage_key ?? null,
      filename: a.filename ?? null,
      mime_type: a.mime_type ?? null,
      file_size_bytes: a.file_size_bytes ?? null,
    };
  }

  function beginPacketAssetEdit(p) {
    const inner = Array.isArray(p?.assets)
      ? p.assets
      : Array.isArray(p?.packet_json?.assets)
        ? p.packet_json.assets
        : [];
    setPacketEditState({
      packetId: p.id,
      titleDraft: p.title ?? "",
      draftAssets: clonePacketAssetsForEdit(inner),
      addPick: "",
    });
  }

  function cancelPacketAssetEdit() {
    setPacketEditState(null);
  }

  async function savePacketAssets() {
    const st = packetEditState;
    if (!st) return;
    setError("");
    try {
      const title = (st.titleDraft ?? "").trim();
      if (title) {
        const tr = await fetch(`${API_BASE}/asset-packets/${st.packetId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title }),
        });
        if (!tr.ok) {
          const detail = await tr.json().catch(() => ({}));
          setError(detail?.detail ? String(detail.detail) : `Update title failed (${tr.status})`);
          return;
        }
      }
      const res = await fetch(`${API_BASE}/asset-packets/${st.packetId}/assets`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ assets: st.draftAssets }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        setError(detail?.detail ? String(detail.detail) : `Save packet failed (${res.status})`);
        return;
      }
      setPacketEditState(null);
      await fetchStaticAssets();
    } catch {
      setError("Save packet failed.");
    }
  }

  async function duplicatePacket(packetId) {
    setError("");
    try {
      const res = await fetch(`${API_BASE}/asset-packets/${packetId}/clone`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(typeof data.detail === "string" ? data.detail : `Duplicate failed (${res.status})`);
        return;
      }
      await fetchStaticAssets();
    } catch {
      setError("Duplicate packet failed.");
    }
  }

  async function createRunPacket() {
    if (!runId) return;
    const title = newPacketForm.title.trim();
    if (!title) {
      setError("Enter a packet title.");
      return;
    }
    setCreatePacketBusy(true);
    setError("");
    try {
      const res = await fetch(`${API_BASE}/asset-packets/run/${runId}/create`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, assets: newPacketForm.draftAssets }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(typeof data.detail === "string" ? data.detail : `Create packet failed (${res.status})`);
        return;
      }
      setNewPacketForm({ title: "", draftAssets: [], addPick: "" });
      await fetchStaticAssets();
    } catch {
      setError("Create packet failed.");
    } finally {
      setCreatePacketBusy(false);
    }
  }

  async function confirmDeletePacket() {
    const id = packetToDelete?.id;
    if (!id) return;
    setError("");
    try {
      const res = await fetch(`${API_BASE}/asset-packets/${id}`, { method: "DELETE" });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        setError(detail?.detail ? String(detail.detail) : `Delete failed (${res.status})`);
        return;
      }
      setPacketToDelete(null);
      setPacketEditState((st) => (st?.packetId === id ? null : st));
      await fetchStaticAssets();
    } catch {
      setError("Delete packet failed.");
    }
  }

  async function fetchReplySendPreview(draftId) {
    setReplySendPreviewByDraftId((p) => ({ ...p, [draftId]: { loading: true } }));
    try {
      const res = await fetch(`${API_BASE}/reply-drafts/${draftId}/send-preview`);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const msg = typeof data.detail === "string" ? data.detail : `Preview failed (${res.status})`;
        setReplySendPreviewByDraftId((p) => ({ ...p, [draftId]: { loading: false, error: msg } }));
        return;
      }
      setReplySendPreviewByDraftId((p) => ({
        ...p,
        [draftId]: {
          loading: false,
          base_body: data.base_body ?? "",
          packet_block: data.packet_block ?? "",
          final_body: data.final_body ?? "",
          attached_packet_id: data.attached_packet_id ?? null,
          attachment_candidates: Array.isArray(data.attachment_candidates) ? data.attachment_candidates : [],
          real_attachments: Array.isArray(data.real_attachments) ? data.real_attachments : [],
          link_only_assets: Array.isArray(data.link_only_assets) ? data.link_only_assets : [],
          skipped_attachments: Array.isArray(data.skipped_attachments) ? data.skipped_attachments : [],
          attached_asset_ids: Array.isArray(data.attached_asset_ids) ? data.attached_asset_ids : [],
          linked_asset_ids: Array.isArray(data.linked_asset_ids) ? data.linked_asset_ids : [],
          will_lock_packet: Boolean(data.will_lock_packet),
          attached_packet_status: data.attached_packet_status ?? null,
        },
      }));
    } catch {
      setReplySendPreviewByDraftId((p) => ({
        ...p,
        [draftId]: { loading: false, error: "Preview failed — check network / backend." },
      }));
    }
  }

  async function toggleReplySendPreview(draftId) {
    const pv = replySendPreviewByDraftId[draftId];
    const hasData =
      pv && !pv.loading && !pv.error && pv.final_body != null;
    if (hasData && replyPreviewExpanded[draftId]) {
      setReplyPreviewExpanded((e) => ({ ...e, [draftId]: false }));
      return;
    }
    if (hasData && !replyPreviewExpanded[draftId]) {
      setReplyPreviewExpanded((e) => ({ ...e, [draftId]: true }));
      return;
    }
    await fetchReplySendPreview(draftId);
    setReplyPreviewExpanded((e) => ({ ...e, [draftId]: true }));
  }

  async function regenerateReplyDraft(draftId) {
    setError("");
    try {
      const res = await fetch(`${API_BASE}/reply-drafts/${draftId}/regenerate`, { method: "POST" });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        setError(detail?.detail ? String(detail.detail) : `Regenerate failed (${res.status})`);
        return;
      }
      setReplyPreviewExpanded((e) => {
        const next = { ...e };
        delete next[draftId];
        return next;
      });
      setReplySendPreviewByDraftId((p) => {
        const next = { ...p };
        delete next[draftId];
        return next;
      });
      setReplyEditing(null);
      await loadLive();
    } catch {
      setError("Regenerate failed — check network / backend.");
    }
  }

  async function reviewReplyDraft(draftId, reviewStatus) {
    setError("");
    try {
      const res = await fetch(`${API_BASE}/reply-drafts/${draftId}/review`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ review_status: reviewStatus }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        setError(detail?.detail ? String(detail.detail) : `Review failed (${res.status})`);
        return;
      }
      await loadLive();
    } catch {
      setError("Review failed — check network / backend.");
    }
  }

  async function sendReplyDraft(draftId) {
    setError("");
    try {
      const res = await fetch(`${API_BASE}/reply-drafts/${draftId}/send`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(typeof data.detail === "string" ? data.detail : `Send failed (${res.status})`);
        return;
      }
      if (data.status === "failed") {
        setError(data.error || "Send failed");
      }
      await loadLive();
    } catch {
      setError("Send reply draft failed — check network / backend.");
    }
  }

  async function saveReplyDraftEdit() {
    if (!replyEditing) return;
    setError("");
    try {
      const res = await fetch(`${API_BASE}/reply-drafts/${replyEditing.id}/edit`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          subject: replyEditing.subject,
          body: replyEditing.body,
          attached_asset_ids: replyEditing.attached_asset_ids,
        }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        setError(detail?.detail ? String(detail.detail) : `Edit failed (${res.status})`);
        return;
      }
      setReplyEditing(null);
      await loadLive();
    } catch {
      setError("Save failed — check network / backend.");
    }
  }

  if (!runId) {
    return (
      <div className="text-sm text-muted-foreground">
        No active run — select a project with a loaded run.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {!singleTabMode ? (
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="text-2xl font-semibold tracking-tight">Tracking</h2>
            <p className="text-sm text-muted-foreground">
              Run #{runId} · sending, events, dead mailboxes, replacement-search queue · auto-refresh 3s
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="secondary" onClick={() => void generateReplacementDrafts()}>
              <FilePenLine className="mr-2 h-4 w-4" />
              Generate drafts for replacements
            </Button>
            <Button type="button" variant="secondary" onClick={() => void sendReplacementDrafts()}>
              <Mails className="mr-2 h-4 w-4" />
              Send approved replacement drafts
            </Button>
            <Button type="button" onClick={() => void sendApprovedDrafts()}>
              Send approved drafts
            </Button>
          </div>
        </div>
      ) : null}

      {error ? (
        <div className="flex items-start gap-2 rounded-xl border-2 border-destructive/40 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          <p className="min-w-0 flex-1">{error}</p>
          <button
            type="button"
            className="shrink-0 rounded-md p-1 opacity-80 hover:bg-destructive/10 hover:opacity-100"
            aria-label="Dismiss"
            onClick={() => setError("")}
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        </div>
      ) : null}

      {!singleTabMode && summary ? (
        <div className="grid gap-4 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6">
          <Card className="rounded-2xl border-2 border-border bg-card shadow-none">
            <CardContent className="p-4">
              <div className="text-xs text-muted-foreground">Sent</div>
              <div className="mt-1 text-2xl font-semibold">{summary.drafts_sent || 0}</div>
            </CardContent>
          </Card>
          <Card className="rounded-2xl border-2 border-border bg-card shadow-none">
            <CardContent className="p-4">
              <div className="text-xs text-muted-foreground">Replies</div>
              <div className="mt-1 text-2xl font-semibold">{summary.events_replied || 0}</div>
            </CardContent>
          </Card>
          <Card className="rounded-2xl border-2 border-border bg-card shadow-none">
            <CardContent className="p-4">
              <div className="text-xs text-muted-foreground">Failed</div>
              <div className="mt-1 text-2xl font-semibold">{summary.events_failed || 0}</div>
            </CardContent>
          </Card>
          <Card className="rounded-2xl border-2 border-border bg-card shadow-none">
            <CardContent className="p-4">
              <div className="text-xs text-muted-foreground">Bounced</div>
              <div className="mt-1 text-2xl font-semibold">{summary.events_bounced || 0}</div>
            </CardContent>
          </Card>
          <Card className="rounded-2xl border-2 border-border bg-card shadow-none">
            <CardContent className="p-4">
              <div className="text-xs text-muted-foreground">Dead mailboxes</div>
              <div className="mt-1 text-2xl font-semibold">{summary.events_dead_mailbox || 0}</div>
            </CardContent>
          </Card>
          <Card className="rounded-2xl border-2 border-border bg-card shadow-none">
            <CardContent className="p-4">
              <div className="text-xs text-muted-foreground">Replacement tasks</div>
              <div className="mt-1 text-2xl font-semibold">{summary.replacement_email_tasks_open || 0}</div>
            </CardContent>
          </Card>
          <Card className="rounded-2xl border-2 border-border bg-card shadow-none">
            <CardContent className="p-4">
              <div className="text-xs text-muted-foreground">Reply rate</div>
              <div className="mt-1 text-2xl font-semibold">{replyRate}%</div>
              <div className="mt-0.5 text-[11px] text-muted-foreground">Replies / sent</div>
            </CardContent>
          </Card>
          <Card className="rounded-2xl border-2 border-border bg-card shadow-none">
            <CardContent className="p-4">
              <div className="text-xs text-muted-foreground">Repl. drafts</div>
              <div className="mt-1 text-2xl font-semibold">{summary.replacement_drafts_generated ?? 0}</div>
              <div className="mt-0.5 text-[11px] text-muted-foreground">By replacement contacts</div>
            </CardContent>
          </Card>
          <Card className="rounded-2xl border-2 border-border bg-card shadow-none">
            <CardContent className="p-4">
              <div className="text-xs text-muted-foreground">Repl. sent</div>
              <div className="mt-1 text-2xl font-semibold">{summary.replacement_drafts_sent ?? 0}</div>
              <div className="mt-0.5 text-[11px] text-muted-foreground">Replacement drafts</div>
            </CardContent>
          </Card>
          <Card className="rounded-2xl border-2 border-border bg-card shadow-none">
            <CardContent className="p-4">
              <div className="text-xs text-muted-foreground">Threads</div>
              <div className="mt-1 text-2xl font-semibold">{summary.threads_total ?? 0}</div>
              <div className="mt-0.5 text-[11px] text-muted-foreground">
                Replied: {summary.threads_replied ?? 0}
              </div>
            </CardContent>
          </Card>
          <Card className="rounded-2xl border-2 border-border bg-card shadow-none">
            <CardContent className="p-4">
              <div className="text-xs text-muted-foreground">Inbox / Out</div>
              <div className="mt-1 text-2xl font-semibold">
                {summary.messages_inbound ?? 0} / {summary.messages_outbound ?? 0}
              </div>
              <div className="mt-0.5 text-[11px] text-muted-foreground">Messages</div>
            </CardContent>
          </Card>
          <Card className="rounded-2xl border-2 border-border bg-card shadow-none">
            <CardContent className="p-4">
              <div className="text-xs text-muted-foreground">Reply drafts</div>
              <div className="mt-1 text-2xl font-semibold">{summary.reply_drafts_generated ?? 0}</div>
              <div className="mt-0.5 text-[11px] text-muted-foreground">
                Appr. {summary.reply_drafts_approved ?? 0} · Edit {summary.reply_drafts_edited ?? 0} · Sent{" "}
                {summary.reply_drafts_sent ?? 0}
              </div>
            </CardContent>
          </Card>
          <Card className="rounded-2xl border-2 border-border bg-card shadow-none">
            <CardContent className="p-4">
              <div className="text-xs text-muted-foreground">Reminders</div>
              <div className="mt-1 text-2xl font-semibold">{summary.reminders_total ?? 0}</div>
              <div className="mt-0.5 text-[11px] text-muted-foreground">
                Sched. {summary.reminders_scheduled ?? 0} · Trig. {summary.reminders_triggered ?? 0} · Snooze{" "}
                {summary.reminders_snoozed ?? 0} · Done {summary.reminders_completed ?? 0}
              </div>
            </CardContent>
          </Card>
          <Card className="rounded-2xl border-2 border-border bg-card shadow-none">
            <CardContent className="p-4">
              <div className="text-xs text-muted-foreground">Asset packets</div>
              <div className="mt-1 text-2xl font-semibold">{summary.asset_packets_draft ?? 0}</div>
              <div className="mt-0.5 text-[11px] text-muted-foreground">
                Draft · Appr. {summary.asset_packets_approved ?? 0} · Sent {summary.asset_packets_sent ?? 0} · Total{" "}
                {summary.asset_packets_total ?? 0}
              </div>
            </CardContent>
          </Card>
        </div>
      ) : null}

      <Tabs
        value={singleTabMode ? activeTab ?? tabValue : tabValue}
        onValueChange={handleTabChange}
        className="w-full"
      >
        {!singleTabMode ? (
          <TabsList className="flex h-auto min-h-10 w-full flex-wrap gap-1 rounded-2xl border-2 border-border bg-muted/30 p-1">
            <TabsTrigger value="events">Events</TabsTrigger>
            <TabsTrigger value="threads">Threads</TabsTrigger>
            <TabsTrigger value="replies">Reply drafts</TabsTrigger>
            <TabsTrigger value="reminders">Reminders</TabsTrigger>
            <TabsTrigger value="assets-library">Assets</TabsTrigger>
            <TabsTrigger value="asset-packets">Packets</TabsTrigger>
            <TabsTrigger value="dead">Dead mailboxes</TabsTrigger>
            <TabsTrigger value="queue">Re-search queue</TabsTrigger>
          </TabsList>
        ) : null}

        <TabsContent value="events" className="mt-4">
          <Card className="rounded-2xl border-2 border-border bg-card shadow-none">
            <CardHeader>
              <CardTitle>Events</CardTitle>
              <CardDescription>
                Email history is grouped by draft. Use the tabs to match delivery state (same idea as Threads).
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div
                className="flex w-full min-w-0 flex-nowrap items-center justify-center gap-1.5 overflow-x-auto pb-0.5 [-ms-overflow-style:none] [scrollbar-width:thin] [&::-webkit-scrollbar]:h-1"
                role="tablist"
                aria-label="Event delivery category"
              >
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  role="tab"
                  aria-selected={eventBucketTab === "active"}
                  className={cn(
                    "h-8 shrink-0 rounded-lg border-2 px-2.5 text-xs font-semibold sm:h-9 sm:px-3 sm:text-sm",
                    eventBucketTab === "active"
                      ? "border-green-500 bg-green-600 text-white hover:bg-green-600 dark:border-green-400 dark:bg-green-600 dark:hover:bg-green-600"
                      : "border-green-600/50 bg-green-600/15 text-green-900 hover:bg-green-600/25 dark:border-green-600/45 dark:bg-green-950/40 dark:text-green-100 dark:hover:bg-green-950/55",
                  )}
                  onClick={() => setEventBucketTab("active")}
                >
                  Active ({displayEventBucketCounts.active})
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  role="tab"
                  aria-selected={eventBucketTab === "bounced"}
                  className={cn(
                    "h-8 shrink-0 rounded-lg border-2 px-2.5 text-xs font-semibold sm:h-9 sm:px-3 sm:text-sm",
                    eventBucketTab === "bounced"
                      ? "border-amber-500 bg-amber-600 text-white hover:bg-amber-600 dark:border-amber-400 dark:bg-amber-600 dark:hover:bg-amber-600"
                      : "border-amber-600/50 bg-amber-600/15 text-amber-950 hover:bg-amber-600/25 dark:border-amber-500/45 dark:bg-amber-950/40 dark:text-amber-100 dark:hover:bg-amber-950/55",
                  )}
                  onClick={() => setEventBucketTab("bounced")}
                >
                  Bounced ({displayEventBucketCounts.bounced})
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  role="tab"
                  aria-selected={eventBucketTab === "dead_mailbox"}
                  className={cn(
                    "h-8 shrink-0 rounded-lg border-2 px-2.5 text-xs font-semibold sm:h-9 sm:px-3 sm:text-sm",
                    eventBucketTab === "dead_mailbox"
                      ? "border-red-500 bg-red-600 text-white hover:bg-red-600 dark:border-red-400 dark:bg-red-600 dark:hover:bg-red-600"
                      : "border-red-700/50 bg-red-950/20 text-red-900 hover:bg-red-950/30 dark:border-red-700/45 dark:bg-red-950/35 dark:text-red-100 dark:hover:bg-red-950/50",
                  )}
                  onClick={() => setEventBucketTab("dead_mailbox")}
                >
                  Dead mailbox ({displayEventBucketCounts.dead_mailbox})
                </Button>
              </div>
              {trackingCountsReady ? (
              <div className="space-y-4">
                {filteredGroupedEvents.map(({ draftId, draft, events: draftEvents }) => {
                  const chainEndsDeadMailbox =
                    draftEvents.length > 0 &&
                    draftEvents[draftEvents.length - 1].event_type === "dead_mailbox";
                  const chainEndsBounced =
                    draftEvents.length > 0 &&
                    draftEvents[draftEvents.length - 1].event_type === "bounced";
                  const chainCollapsed = eventChainCollapsedMap[String(draftId)] === true;
                  return (
                    <div
                      key={draftId}
                      className={
                        chainEndsDeadMailbox
                          ? "rounded-2xl border-2 border-red-700/50 bg-red-950/10 p-4 dark:border-red-700/40 dark:bg-red-950/20"
                          : chainEndsBounced
                            ? "rounded-2xl border-2 border-amber-600/45 bg-amber-950/15 p-4 dark:border-amber-600/40 dark:bg-amber-950/25"
                            : "rounded-2xl border-2 border-border bg-muted/25 p-4"
                      }
                    >
                      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8 shrink-0"
                              aria-expanded={!chainCollapsed}
                              aria-label={
                                chainCollapsed ? "Expand events for this draft" : "Collapse events for this draft"
                              }
                              title={chainCollapsed ? "Expand events" : "Collapse events"}
                              onClick={() => void persistEventChainCollapsed(draftId, !chainCollapsed)}
                            >
                              {chainCollapsed ? (
                                <ChevronDown className="h-4 w-4" aria-hidden />
                              ) : (
                                <ChevronUp className="h-4 w-4" aria-hidden />
                              )}
                            </Button>
                            <div className="text-base font-semibold leading-tight">
                              {draft?.company || `Draft #${draftId}`}
                            </div>
                            {isReplacementDraft(draft) ? (
                              <Badge
                                variant="default"
                                className="bg-violet-600 font-normal hover:bg-violet-600"
                              >
                                Replacement draft
                              </Badge>
                            ) : null}
                          </div>
                          <div className="mt-1 text-sm text-muted-foreground">
                            {draft?.to_email || "No recipient"}
                          </div>
                          <div className="mt-1 text-sm">{draft?.subject || "No subject"}</div>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {canShowSend(draft) ? (
                            <Button type="button" size="sm" onClick={() => void sendSingleDraft(draftId)}>
                              Send
                            </Button>
                          ) : null}
                        </div>
                      </div>
                      {chainCollapsed ? null : (
                        <div
                          className={`mt-4 space-y-3 border-t pt-4 ${
                            chainEndsDeadMailbox
                              ? "border-red-700/30"
                              : chainEndsBounced
                                ? "border-amber-600/35 dark:border-amber-600/30"
                                : "border-border/50"
                          }`}
                        >
                          {draftEvents.map((event, index) => (
                            <div key={event.id}>
                              <div
                                className={`flex items-center justify-between gap-3 rounded-2xl border-2 p-3 ${
                                  chainEndsDeadMailbox
                                    ? "border-red-700/35 bg-red-950/15 dark:border-red-700/30 dark:bg-red-950/25"
                                    : chainEndsBounced
                                      ? "border-amber-600/40 bg-amber-950/20 dark:border-amber-600/35 dark:bg-amber-950/30"
                                      : "border-border bg-muted/40"
                                }`}
                              >
                                <div className="flex items-center gap-3">
                                  <div className={`rounded-xl p-2 ${eventTone(event.event_type)}`}>
                                    {eventIcon(event.event_type)}
                                  </div>
                                  <div>
                                    <div className="font-medium capitalize">
                                      {event.event_type.replaceAll("_", " ")}
                                    </div>
                                    <div className="text-xs text-muted-foreground">Event #{event.id}</div>
                                  </div>
                                </div>
                                <Badge variant="secondary">{new Date(event.created_at).toLocaleString()}</Badge>
                              </div>
                              {index < draftEvents.length - 1 ? <Separator className="my-2" /> : null}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
                {!groupedEvents.length ? (
                  <div className="text-sm text-muted-foreground">No events yet.</div>
                ) : filteredGroupedEvents.length === 0 ? (
                  <div className="text-sm text-muted-foreground">
                    {eventBucketTab === "active"
                      ? "No active event groups — check Bounced or Dead mailbox."
                      : eventBucketTab === "bounced"
                        ? "No bounced groups in this run."
                        : "No dead mailbox groups in this run."}
                  </div>
                ) : null}
              </div>
              ) : eventsTrackingListMode === "loading" && filteredEventsPanelLiteRows.length > 0 ? (
                <div className="space-y-4">
                  <p className="text-xs text-muted-foreground" role="status">
                    Showing cached events — refreshing from server…
                  </p>
                  {filteredEventsPanelLiteRows.map((g) => (
                    <div
                      key={g.draftId}
                      className={
                        g.chainEndsDeadMailbox
                          ? "rounded-2xl border-2 border-red-700/50 bg-red-950/10 p-4 dark:border-red-700/40 dark:bg-red-950/20"
                          : g.chainEndsBounced
                            ? "rounded-2xl border-2 border-amber-600/45 bg-amber-950/15 p-4 dark:border-amber-600/40 dark:bg-amber-950/25"
                            : "rounded-2xl border-2 border-border bg-muted/25 p-4"
                      }
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <div className="text-base font-semibold leading-tight">
                          {g.company || `Draft #${g.draftId}`}
                        </div>
                        {g.isReplacement ? (
                          <Badge
                            variant="default"
                            className="bg-violet-600 font-normal hover:bg-violet-600"
                          >
                            Replacement draft
                          </Badge>
                        ) : null}
                      </div>
                      <div className="mt-1 text-sm text-muted-foreground">{g.to_email || "No recipient"}</div>
                      <div className="mt-1 text-sm">{g.subject || "No subject"}</div>
                      <p className="mt-2 text-xs text-muted-foreground">
                        {g.eventCount} event{g.eventCount === 1 ? "" : "s"} — timeline loads after sync.
                      </p>
                    </div>
                  ))}
                  {runPanelLiteSnapshot?.eventsGroups?.length &&
                  filteredEventsPanelLiteRows.length === 0 ? (
                    <div className="text-sm text-muted-foreground">
                      {eventBucketTab === "active"
                        ? "No active event groups in this tab (cached) — check other tabs."
                        : eventBucketTab === "bounced"
                          ? "No bounced groups in this tab (cached)."
                          : "No dead mailbox groups in this tab (cached)."}
                    </div>
                  ) : null}
                </div>
              ) : (
                <TrackingCardsPlaceholder mode={eventsTrackingListMode} kind="Event" />
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="threads" className="mt-4">
          <Card className="rounded-2xl border-2 border-border bg-card shadow-none">
            <CardHeader>
              <CardTitle>Threads</CardTitle>
              <CardDescription>
                Threads appear after you send a draft. Use the tabs to switch between active correspondence,
                bounces, and dead mailboxes.
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3">
            <div
              className="flex w-full min-w-0 flex-nowrap items-center justify-center gap-1.5 overflow-x-auto pb-0.5 [-ms-overflow-style:none] [scrollbar-width:thin] [&::-webkit-scrollbar]:h-1"
              role="tablist"
              aria-label="Thread delivery category"
            >
              <Button
                type="button"
                size="sm"
                variant="ghost"
                role="tab"
                aria-selected={threadBucketTab === "active"}
                className={cn(
                  "h-8 shrink-0 rounded-lg border-2 px-2.5 text-xs font-semibold sm:h-9 sm:px-3 sm:text-sm",
                  threadBucketTab === "active"
                    ? "border-green-500 bg-green-600 text-white hover:bg-green-600 dark:border-green-400 dark:bg-green-600 dark:hover:bg-green-600"
                    : "border-green-600/50 bg-green-600/15 text-green-900 hover:bg-green-600/25 dark:border-green-600/45 dark:bg-green-950/40 dark:text-green-100 dark:hover:bg-green-950/55",
                )}
                onClick={() => setThreadBucketTab("active")}
              >
                Active ({displayThreadBucketCounts.active})
              </Button>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                role="tab"
                aria-selected={threadBucketTab === "bounced"}
                className={cn(
                  "h-8 shrink-0 rounded-lg border-2 px-2.5 text-xs font-semibold sm:h-9 sm:px-3 sm:text-sm",
                  threadBucketTab === "bounced"
                    ? "border-amber-500 bg-amber-600 text-white hover:bg-amber-600 dark:border-amber-400 dark:bg-amber-600 dark:hover:bg-amber-600"
                    : "border-amber-600/50 bg-amber-600/15 text-amber-950 hover:bg-amber-600/25 dark:border-amber-500/45 dark:bg-amber-950/40 dark:text-amber-100 dark:hover:bg-amber-950/55",
                )}
                onClick={() => setThreadBucketTab("bounced")}
              >
                Bounced ({displayThreadBucketCounts.bounced})
              </Button>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                role="tab"
                aria-selected={threadBucketTab === "dead_mailbox"}
                className={cn(
                  "h-8 shrink-0 rounded-lg border-2 px-2.5 text-xs font-semibold sm:h-9 sm:px-3 sm:text-sm",
                  threadBucketTab === "dead_mailbox"
                    ? "border-red-500 bg-red-600 text-white hover:bg-red-600 dark:border-red-400 dark:bg-red-600 dark:hover:bg-red-600"
                    : "border-red-700/50 bg-red-950/20 text-red-900 hover:bg-red-950/30 dark:border-red-700/45 dark:bg-red-950/35 dark:text-red-100 dark:hover:bg-red-950/50",
                )}
                onClick={() => setThreadBucketTab("dead_mailbox")}
              >
                Dead mailbox ({displayThreadBucketCounts.dead_mailbox})
              </Button>
            </div>
            {trackingCountsReady ? (
            <>
            {sortedFilteredThreads.map((t) => {
              const contact = contactById.get(t.contact_id);
              const counts = messageCountsByThreadId.get(t.id) || { in: 0, out: 0 };
              const label = t.classification;
              const outboundDraftId = threadOutboundDraftId(t);
              const linkedDraft =
                outboundDraftId != null ? draftById.get(outboundDraftId) : undefined;
              const draftLifecycle = linkedDraft
                ? linkedDraft.tracking_status ?? linkedDraft.status
                : null;
              const isThreadDeadMailbox =
                draftLifecycle === "dead_mailbox" || contact?.email_health === "dead_mailbox";
              const isThreadBounced =
                linkedDraft?.tracking_status === "bounced" || contact?.email_health === "bounced";
              const needsInboundAttention = Boolean(threadNeedsInboundAttention.get(t.id));
              const showInboundBadge =
                needsInboundAttention && !isThreadBounced && !isThreadDeadMailbox;
              const threadRemind = activeThreadReminderByThreadId.get(t.id);
              return (
                <div
                  key={t.id}
                  className={
                    isThreadDeadMailbox
                      ? "flex flex-col gap-3 rounded-2xl border-2 border-red-700/50 bg-red-950/10 p-5 dark:border-red-700/40 dark:bg-red-950/20 sm:flex-row sm:items-center sm:justify-between"
                      : isThreadBounced
                        ? "flex flex-col gap-3 rounded-2xl border-2 border-amber-600/45 bg-amber-950/15 p-5 dark:border-amber-600/40 dark:bg-amber-950/25 sm:flex-row sm:items-center sm:justify-between"
                        : "flex flex-col gap-3 rounded-2xl border-2 border-border bg-muted/30 p-5 sm:flex-row sm:items-center sm:justify-between"
                  }
                >
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        {isThreadDeadMailbox ? (
                          <CircleAlert
                            className="h-5 w-5 shrink-0 text-red-600 dark:text-red-400"
                            aria-hidden
                          />
                        ) : isThreadBounced ? (
                          <MailWarning
                            className="h-5 w-5 shrink-0 text-amber-600 dark:text-amber-400"
                            aria-hidden
                          />
                        ) : null}
                        <div className="font-medium">{contact?.company || `Contact #${t.contact_id}`}</div>
                        {isThreadBounced && !isThreadDeadMailbox ? (
                          <Badge
                            variant="outline"
                            className="gap-1 border-amber-600/55 bg-amber-500/15 font-normal text-amber-950 dark:border-amber-500/50 dark:bg-amber-950/35 dark:text-amber-100"
                            title="Outbound delivery failed (bounce)"
                          >
                            <MailWarning className="h-3.5 w-3.5 shrink-0 text-amber-700 dark:text-amber-300" aria-hidden />
                            Bounced
                          </Badge>
                        ) : null}
                        {showInboundBadge ? (
                          <Badge
                            variant="outline"
                            className="gap-1 border-green-600/50 bg-green-600/15 font-normal text-green-800 dark:border-green-600/45 dark:bg-green-950/45 dark:text-green-300"
                            title="Last message in this thread is inbound — needs your attention"
                          >
                            <AlertCircle
                              className="h-3.5 w-3.5 shrink-0 text-green-600 dark:text-green-400"
                              aria-hidden
                            />
                            Inbound
                          </Badge>
                        ) : null}
                        {threadRemind ? (
                          <Badge
                            variant="outline"
                            className="gap-1 border-amber-600/60 bg-amber-500/15 font-normal text-amber-950 dark:border-amber-500/50 dark:bg-amber-950/40 dark:text-amber-100"
                            title={`Reminder: ${new Date(threadRemind.remind_at).toLocaleString()}`}
                          >
                            <Clock className="h-3.5 w-3.5 shrink-0 text-amber-700 dark:text-amber-300" aria-hidden />
                            Remind later
                          </Badge>
                        ) : null}
                        {isThreadDeadMailbox ? (
                          <Badge variant="destructive" className="font-normal text-xs">
                            Dead mailbox
                          </Badge>
                        ) : null}
                        {label ? (
                          <Badge
                            variant="default"
                            className={`font-normal ${threadClassificationBadgeClass(label)}`}
                          >
                            {THREAD_CLASS_LABELS[label] || label}
                          </Badge>
                        ) : null}
                      </div>
                      <div className="mt-1 text-sm text-muted-foreground">
                        {contact?.name || "—"} · {t.subject || "No subject"}
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                        <Badge variant="secondary">{t.status}</Badge>
                        <span>
                          Out {counts.out} · In {counts.in}
                        </span>
                        {t.last_message_at ? (
                          <span>Last: {new Date(t.last_message_at).toLocaleString()}</span>
                        ) : null}
                      </div>
                    </div>
                    <Button type="button" variant="outline" onClick={() => setThreadModalId(t.id)}>
                      Open thread
                    </Button>
                </div>
              );
            })}
            {!threads.length ? (
              <div className="text-sm text-muted-foreground">No threads yet — send at least one draft.</div>
            ) : null}
            {threads.length > 0 && !filteredThreads.length ? (
              <div className="text-sm text-muted-foreground">
                {threadBucketTab === "active"
                  ? "No threads in Active — check Bounced or Dead mailbox."
                  : threadBucketTab === "bounced"
                    ? "No bounced threads in this run."
                    : "No dead mailbox threads in this run."}
              </div>
            ) : null}
            </>
            ) : threadsTrackingListMode === "loading" && filteredThreadPanelLiteRows.length > 0 ? (
              <>
                <p className="text-xs text-muted-foreground" role="status">
                  Showing cached threads — refreshing from server…
                </p>
                {filteredThreadPanelLiteRows.map((row) => (
                  <ThreadCardFromLite key={row.id} row={row} />
                ))}
                {runPanelLiteSnapshot?.threads?.length && filteredThreadPanelLiteRows.length === 0 ? (
                  <div className="text-sm text-muted-foreground">
                    {threadBucketTab === "active"
                      ? "No threads in Active (cached) — check Bounced or Dead mailbox."
                      : threadBucketTab === "bounced"
                        ? "No bounced threads in this tab (cached)."
                        : "No dead mailbox threads in this tab (cached)."}
                  </div>
                ) : null}
              </>
            ) : (
              <TrackingCardsPlaceholder mode={threadsTrackingListMode} kind="Thread" />
            )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="replies" className="mt-4">
          <Card className="rounded-2xl border-2 border-border bg-card shadow-none">
            <CardHeader>
              <CardTitle>Reply drafts</CardTitle>
              <CardDescription>
                Inbound reply drafts (after interested / need_more_info). Generate from the thread modal, then Approve /
                Edit and Send — nothing is sent automatically.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-3">
            {replyDrafts.map((rd) => {
              const c = contactById.get(rd.contact_id);
              const isEditing = replyEditing?.id === rd.id;
              const attachedPacket = assetPackets.find((p) => p.reply_draft_id === rd.id);
              const pv = replySendPreviewByDraftId[rd.id];
              const hasPreviewData =
                pv && !pv.loading && !pv.error && pv.final_body != null;
              const previewAria =
                hasPreviewData && replyPreviewExpanded[rd.id] ? "Hide send preview" : "Load send preview";
              const showPreviewBlock = Boolean(replyPreviewExpanded[rd.id] && hasPreviewData);
              const canRegenReply = ["draft", "failed"].includes(rd.status);
              return (
                <div key={rd.id} className="space-y-3 rounded-2xl border-2 border-border bg-muted/30 p-5">
                    <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                      <div className="min-w-0 flex-1">
                        <div className="font-medium">{c?.company || `Contact #${rd.contact_id}`}</div>
                        <div className="text-sm text-muted-foreground">
                          {c?.name || "—"} · To: {rd.to_email || "—"}
                        </div>
                        <div className="mt-1 flex flex-wrap items-center gap-2">
                          <Badge variant="outline">{rd.reply_type}</Badge>
                          <Badge variant="secondary">{rd.status}</Badge>
                          <Badge variant="secondary">{rd.review_status}</Badge>
                          <span className="text-xs text-muted-foreground">Thread #{rd.thread_id}</span>
                          {attachedPacket ? (
                            <Badge
                              variant="outline"
                              className="border-indigo-500/50 font-normal text-indigo-800 dark:text-indigo-200"
                            >
                              Packet attached
                              {attachedPacket.status === "sent"
                                ? " (sent, locked)"
                                : attachedPacket.status === "archived"
                                  ? " (archived)"
                                  : ""}{" "}
                              #{attachedPacket.id}
                            </Badge>
                          ) : (
                            <span className="text-xs text-muted-foreground">No packet attached</span>
                          )}
                        </div>
                        {attachedPacket ? (
                          <div className="mt-1 text-xs text-muted-foreground">
                            Packet status:{" "}
                            <span className="font-medium text-foreground">{attachedPacket.status}</span>
                            {attachedPacket.status === "sent" ? (
                              <span className="mt-0.5 block text-amber-800 dark:text-amber-200">
                                This packet is locked because it has already been used in a sent reply.
                              </span>
                            ) : null}
                          </div>
                        ) : null}
                        {pv?.error ? (
                          <div className="mt-2 text-xs text-destructive">{pv.error}</div>
                        ) : null}
                        {pv?.loading ? (
                          <div className="mt-2 text-xs text-muted-foreground">Loading preview…</div>
                        ) : null}
                      </div>
                      <div className="flex max-w-full shrink-0 flex-nowrap items-center justify-end gap-2 overflow-x-auto">
                        {!isEditing ? (
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            className="shrink-0"
                            onClick={() => {
                              void (async () => {
                                try {
                                  const r = await fetch(`${API_BASE}/reply-drafts/${rd.id}`);
                                  if (!r.ok) return;
                                  const full = await r.json();
                                  setReplyEditing({
                                    id: full.id,
                                    subject: full.subject ?? "",
                                    body: full.body ?? "",
                                    attached_asset_ids: normalizeAttachedAssetIds(full.attached_asset_ids),
                                  });
                                } catch {
                                  /* keep collapsed */
                                }
                              })();
                            }}
                          >
                            <Pencil className="mr-1 h-3 w-3" />
                            Edit
                          </Button>
                        ) : null}
                        {rd.review_status === "pending" || rd.review_status === "rejected" ? (
                          <Button
                            type="button"
                            size="sm"
                            className="shrink-0"
                            onClick={() => void reviewReplyDraft(rd.id, "approved")}
                          >
                            Approve
                          </Button>
                        ) : null}
                        {canSendReplyDraft(rd) ? (
                          <Button type="button" size="sm" className="shrink-0" onClick={() => void sendReplyDraft(rd.id)}>
                            Send
                          </Button>
                        ) : null}
                        {canRegenReply ? (
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            className="shrink-0"
                            onClick={() => void regenerateReplyDraft(rd.id)}
                          >
                            Regenerate
                          </Button>
                        ) : null}
                        {rd.review_status === "pending" || ["approved", "edited"].includes(rd.review_status) ? (
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            className="shrink-0"
                            onClick={() => void reviewReplyDraft(rd.id, "rejected")}
                          >
                            Reject
                          </Button>
                        ) : null}
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="shrink-0 px-2"
                          onClick={() => void toggleReplySendPreview(rd.id)}
                          disabled={pv?.loading}
                          aria-label={previewAria}
                          title={previewAria}
                        >
                          {pv?.loading ? (
                            "…"
                          ) : hasPreviewData && replyPreviewExpanded[rd.id] ? (
                            <EyeOff className="h-4 w-4" aria-hidden />
                          ) : (
                            <Eye className="h-4 w-4" aria-hidden />
                          )}
                        </Button>
                      </div>
                    </div>
                    {showPreviewBlock ? (
                      <div className="space-y-2 rounded-xl border-2 border-border bg-muted/20 p-3 text-xs">
                        {pv.will_lock_packet ? (
                          <div className="rounded-md border-2 border-amber-500/30 bg-amber-500/10 px-2 py-1.5 text-amber-900 dark:text-amber-100">
                            This packet will be locked after successful send.
                          </div>
                        ) : null}
                        <div className="flex flex-wrap gap-x-4 gap-y-1 text-muted-foreground">
                          <span>
                            <span className="font-medium text-foreground">Attachments to send:</span>{" "}
                            {pv.real_attachments?.length ?? 0}
                          </span>
                          <span>
                            <span className="font-medium text-foreground">Stay as links in body:</span>{" "}
                            {pv.link_only_assets?.length ?? 0}
                          </span>
                        </div>
                        {(pv.real_attachments?.length ?? 0) > 0 ? (
                          <ul className="list-inside list-disc space-y-0.5 text-muted-foreground">
                            {pv.real_attachments.map((a) => (
                              <li key={`${a.asset_id}-${a.filename}`}>
                                {a.filename}{" "}
                                <span className="text-[10px] opacity-80">(asset #{a.asset_id})</span>
                              </li>
                            ))}
                          </ul>
                        ) : null}
                        {(pv.skipped_attachments?.length ?? 0) > 0 ? (
                          <div className="text-amber-800 dark:text-amber-200">
                            <div className="font-medium">Not sent as files (fallback to link in Materials if listed)</div>
                            <ul className="mt-1 list-inside list-disc">
                              {pv.skipped_attachments.map((s, idx) => (
                                <li key={`${s.asset_id ?? "x"}-${idx}`}>
                                  {s.asset_id != null ? `Asset #${s.asset_id}: ` : ""}
                                  {s.reason}
                                </li>
                              ))}
                            </ul>
                          </div>
                        ) : null}
                        <div>
                          <div className="font-medium text-foreground">Reply body (saved draft)</div>
                          <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap text-muted-foreground">
                            {pv.base_body || "—"}
                          </pre>
                        </div>
                        {(pv.packet_block || "").trim() ? (
                          <div>
                            <div className="font-medium text-foreground">Materials block (links only, append on send)</div>
                            <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap text-muted-foreground">
                              {pv.packet_block}
                            </pre>
                          </div>
                        ) : (
                          <div className="text-muted-foreground">
                            {pv.attached_packet_id != null ? (
                              <>
                                {(pv.real_attachments?.length ?? 0) > 0 ? (
                                  <>
                                    No <code className="text-[11px]">Materials:</code> block — packet assets are sent as
                                    file attachments only (not duplicated as links).
                                  </>
                                ) : (
                                  <>
                                    Packet #{pv.attached_packet_id} is attached, but{" "}
                                    the packet <code className="text-[11px]">assets</code> list is empty — add assets to the
                                    library and rebuild the packet.
                                  </>
                                )}
                              </>
                            ) : (
                              <>No materials block (no packet attached or empty assets list).</>
                            )}
                          </div>
                        )}
                        <div>
                          <div className="font-medium text-foreground">Final outbound (what Send uses)</div>
                          <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap">{pv.final_body}</pre>
                        </div>
                      </div>
                    ) : null}
                    <div className="text-sm font-medium">{rd.subject}</div>
                    <EmailDraftBodyPreview
                      body={rd.body}
                      showSignaturePlaceholder={showSignaturePlaceholder}
                      attachedAssetIds={normalizeAttachedAssetIds(rd.attached_asset_ids)}
                      assetLibrary={assets}
                    />
                    {rd.error_message ? (
                      <div className="text-sm text-destructive">{rd.error_message}</div>
                    ) : null}
                </div>
              );
            })}
            {!replyDrafts.length ? (
              <div className="text-sm text-muted-foreground">
                No reply drafts yet — generate one from Threads → Open thread.
              </div>
            ) : null}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="reminders" className="mt-4">
          <Card className="rounded-2xl border-2 border-border bg-card shadow-none">
            <CardHeader>
              <div>
                <CardTitle>Reminders</CardTitle>
                <CardDescription>
                  Dates are stored for your workflow only (not a separate calendar). Create from a thread with{" "}
                  <strong>Set reminder</strong> under &quot;Remind me later&quot;.
                </CardDescription>
              </div>
            </CardHeader>
            <CardContent className="grid gap-3">
            {reminders.map((r) => {
              const c = r.contact_id != null ? contactById.get(r.contact_id) : null;
              const canAct = REMINDER_ACTIVE_STATUSES.includes(r.status);
              const remindDate = new Date(r.remind_at);
              const isOverdue =
                canAct && (r.status === "scheduled" || r.status === "snoozed") && remindDate < new Date();
              return (
                <div key={r.id} className="space-y-3 rounded-2xl border-2 border-border bg-muted/30 p-5">
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                      <div>
                        <div className="font-medium">{r.title}</div>
                        <div className="mt-1 text-sm text-muted-foreground">
                          {c?.company || (r.contact_id != null ? `Contact #${r.contact_id}` : "—")} ·{" "}
                          {c?.name || "—"}
                          {r.thread_id ? (
                            <span className="text-xs text-muted-foreground/90"> · Thread #{r.thread_id}</span>
                          ) : null}
                        </div>
                        <div className="mt-1 flex flex-wrap items-center gap-2">
                          <Badge variant="outline">{r.status}</Badge>
                          <Badge variant="secondary">{r.priority}</Badge>
                          <span className="text-xs text-muted-foreground">
                            Remind: {remindDate.toLocaleString()}
                          </span>
                          {isOverdue ? (
                            <Badge variant="destructive" className="font-normal">
                              Overdue
                            </Badge>
                          ) : null}
                          {r.status === "scheduled" || r.status === "snoozed" ? (
                            <span className="text-xs text-muted-foreground">(upcoming)</span>
                          ) : null}
                          {r.status === "triggered" ? (
                            <Badge variant="default" className="bg-amber-600 font-normal hover:bg-amber-600">
                              Due now
                            </Badge>
                          ) : null}
                        </div>
                        {r.description ? (
                          <p className="mt-2 text-sm text-muted-foreground">{r.description}</p>
                        ) : null}
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {canAct ? (
                          <Button type="button" size="sm" onClick={() => void patchReminderStatus(r.id, "completed")}>
                            Complete
                          </Button>
                        ) : null}
                        {canAct ? (
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            onClick={() => void patchReminderStatus(r.id, "cancelled")}
                          >
                            Cancel
                          </Button>
                        ) : null}
                        {canAct ? (
                          <Button
                            type="button"
                            size="sm"
                            variant="secondary"
                            onClick={() => void snoozeReminderOneDay(r)}
                          >
                            Snooze +1 day
                          </Button>
                        ) : null}
                      </div>
                    </div>
                </div>
              );
            })}
            {!reminders.length ? (
              <div className="text-sm text-muted-foreground">
                No reminders yet — open a thread and use <strong>Set reminder</strong>.
              </div>
            ) : null}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="assets-library" className="mt-4">
          <Card className="rounded-2xl border-2 border-border bg-card shadow-none">
            <CardHeader>
              <CardTitle>Assets</CardTitle>
              <CardDescription>
                Global materials library. Thread packets pick active assets by type (need_more_info vs interested).
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="rounded-2xl border-2 border-border bg-muted/25 p-4">
                <div className="mb-3 text-sm font-medium">Add link</div>
                <p className="mb-3 text-xs text-muted-foreground">
                  Register a public URL (deck on Google Drive, Notion, etc.).
                </p>
                <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
                  <div className="min-w-[140px] flex-1 space-y-1">
                    <div className="text-xs text-muted-foreground">Name</div>
                    <Input
                      value={newAssetName}
                      onChange={(e) => setNewAssetName(e.target.value)}
                      placeholder="Pitch deck Q1"
                    />
                  </div>
                  <div className="min-w-[140px] space-y-1">
                    <div className="text-xs text-muted-foreground">Type</div>
                    <NativeFilterSelect
                      value={newAssetType}
                      onValueChange={setNewAssetType}
                      options={ASSET_LIBRARY_TYPE_OPTS}
                    />
                  </div>
                  <div className="min-w-[180px] flex-1 basis-full space-y-1">
                    <div className="text-xs text-muted-foreground">URL</div>
                    <Input
                      value={newAssetUrl}
                      onChange={(e) => setNewAssetUrl(e.target.value)}
                      placeholder="https://..."
                    />
                  </div>
                  <Button type="button" onClick={() => void submitNewAsset()}>
                    Add link
                  </Button>
                </div>
              </div>

              <div className="rounded-2xl border-2 border-border bg-muted/25 p-4">
                <div className="mb-3 text-sm font-medium">Add file</div>
                {cdnR2UploadReady ? (
                  <p className="mb-3 text-xs text-muted-foreground">
                    Files go to your Cloudflare R2 bucket; the asset link uses your public base URL from the server
                    config.
                  </p>
                ) : (
                  <p className="mb-3 text-xs text-muted-foreground">
                    Upload to project CDN (Cloudflare R2). Requires{" "}
                    <code className="rounded bg-muted px-1 py-0.5 text-[11px]">CDN_ACCOUNT_ID</code>,{" "}
                    <code className="rounded bg-muted px-1 py-0.5 text-[11px]">CDN_R2_BUCKET</code>,{" "}
                    <code className="rounded bg-muted px-1 py-0.5 text-[11px]">CDN_R2_ACCESS_KEY_ID</code>, secret (
                    <code className="rounded bg-muted px-1 py-0.5 text-[11px]">CDN_R2_SECRET_ACCESS_KEY</code> or{" "}
                    <code className="rounded bg-muted px-1 py-0.5 text-[11px]">CDN_API_KEY</code>), and{" "}
                    <code className="rounded bg-muted px-1 py-0.5 text-[11px]">CDN_R2_PUBLIC_BASE_URL</code> in{" "}
                    <code className="rounded bg-muted px-1 py-0.5 text-[11px]">backend/.env</code>.
                    <span className="mt-1 block font-medium text-amber-600 dark:text-amber-500">
                      Upload is disabled until R2 is configured (refresh the page after editing .env).
                    </span>
                  </p>
                )}
                <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
                  <div className="min-w-[140px] flex-1 space-y-1">
                    <div className="text-xs text-muted-foreground">Name</div>
                    <Input
                      value={uploadAssetName}
                      onChange={(e) => setUploadAssetName(e.target.value)}
                      placeholder="Q1 deck.pdf"
                    />
                  </div>
                  <div className="min-w-[140px] space-y-1">
                    <div className="text-xs text-muted-foreground">Type</div>
                    <NativeFilterSelect
                      value={uploadAssetType}
                      onValueChange={setUploadAssetType}
                      options={ASSET_LIBRARY_TYPE_OPTS}
                    />
                  </div>
                  <div className="min-w-[200px] flex-1 basis-full space-y-1">
                    <div className="text-xs text-muted-foreground">File</div>
                    <input
                      ref={uploadFileInputRef}
                      type="file"
                      disabled={!cdnR2UploadReady}
                      className={cn(
                        "flex h-10 w-full cursor-pointer rounded-md border border-input bg-background px-3 py-2 text-sm",
                        "ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium",
                        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20",
                        "disabled:cursor-not-allowed disabled:opacity-50",
                      )}
                      onChange={(e) => setUploadPick(e.target.files?.[0] ?? null)}
                    />
                  </div>
                  <Button
                    type="button"
                    disabled={!cdnR2UploadReady || uploadBusy}
                    title={
                      !cdnR2UploadReady
                        ? "Set R2 variables in backend/.env (see text above), then reload."
                        : undefined
                    }
                    onClick={() => void submitUploadAsset()}
                  >
                    {uploadBusy ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                        Uploading…
                      </>
                    ) : (
                      <>
                        <Upload className="mr-2 h-4 w-4" aria-hidden />
                        Upload
                      </>
                    )}
                  </Button>
                </div>
              </div>
            </div>
          <div className="grid gap-3">
            {assets.map((a) => (
              <div key={a.id} className="rounded-2xl border-2 border-border bg-muted/30 p-5">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="outline">{a.asset_type}</Badge>
                    <Badge variant="secondary">{a.status}</Badge>
                    {assetIsCdnUpload(a) ? (
                      <Badge
                        className="border-transparent bg-green-600 text-white hover:bg-green-600 dark:bg-green-600 dark:hover:bg-green-600"
                        title="Uploaded via CDN (R2 / Cloudflare Images)"
                      >
                        file
                      </Badge>
                    ) : null}
                  </div>
                  <div className="mt-2 font-medium">{a.name}</div>
                  {a.description ? (
                    <p className="mt-1 text-sm text-muted-foreground">{a.description}</p>
                  ) : null}
                  <div className="mt-2 text-sm text-muted-foreground">
                    {a.url ? (
                      <a href={a.url} className="text-primary underline break-all" target="_blank" rel="noreferrer">
                        {a.url}
                      </a>
                    ) : (
                      "—"
                    )}
                    {a.file_path ? <span className="block text-xs">File: {a.file_path}</span> : null}
                  </div>
              </div>
            ))}
            {!assets.length ? (
              <div className="text-sm text-muted-foreground">No assets — add one with the form above.</div>
            ) : null}
          </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="asset-packets" className="mt-4">
          <Card className="rounded-2xl border-2 border-border bg-card shadow-none">
            <CardHeader>
              <CardTitle>Packets</CardTitle>
              <CardDescription>
                Run-level presets of library assets. In email and reply draft editors, use <strong>Assets</strong> (
                pick individually) and <strong>Packets</strong> (merge all ids from a preset). You can also build from
                a classified thread via the thread modal.
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3">
              {(() => {
                const activeNew = assets.filter((a) => a.status === "active");
                const newAddOptions = [
                  { value: "", label: "Add from library…" },
                  ...activeNew.map((a) => ({
                    value: String(a.id),
                    label: `${a.asset_type}: ${(a.name || "").slice(0, 42) || `#${a.id}`}`,
                  })),
                ];
                return (
                  <div className="space-y-3 rounded-2xl border-2 border-dashed border-border bg-muted/15 p-4">
                    <div className="font-medium">New packet</div>
                    <p className="text-xs text-muted-foreground">
                      Title required. Assets are optional; you can edit after creation.
                    </p>
                    <Input
                      placeholder="Packet title"
                      value={newPacketForm.title}
                      onChange={(e) => setNewPacketForm((f) => ({ ...f, title: e.target.value }))}
                    />
                    <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-end">
                      <NativeFilterSelect
                        className="w-full sm:max-w-md"
                        value={newPacketForm.addPick ?? ""}
                        onValueChange={(v) => setNewPacketForm((f) => ({ ...f, addPick: v }))}
                        options={newAddOptions}
                      />
                      <Button
                        type="button"
                        size="sm"
                        variant="secondary"
                        onClick={() => {
                          const pick = newPacketForm.addPick;
                          if (!pick) return;
                          const aid = Number(pick);
                          const lib = activeNew.find((x) => x.id === aid);
                          if (!lib) return;
                          if (newPacketForm.draftAssets.some((row) => row.asset_id === lib.id)) {
                            setNewPacketForm((f) => ({ ...f, addPick: "" }));
                            return;
                          }
                          setNewPacketForm((f) => ({
                            ...f,
                            draftAssets: [...f.draftAssets, libraryRowToPacketSnapshot(lib)],
                            addPick: "",
                          }));
                        }}
                      >
                        Add to list
                      </Button>
                    </div>
                    {newPacketForm.draftAssets.length ? (
                      <ul className="text-xs text-muted-foreground">
                        {newPacketForm.draftAssets.map((row, idx) => (
                          <li key={`${row.asset_id}-${idx}`}>
                            #{row.asset_id} · {row.title || row.name || "—"}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                    <Button
                      type="button"
                      size="sm"
                      disabled={createPacketBusy}
                      aria-busy={createPacketBusy}
                      onClick={() => void createRunPacket()}
                    >
                      {createPacketBusy ? (
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                      ) : null}
                      Create packet
                    </Button>
                  </div>
                );
              })()}
              {assetPackets.map((p) => {
                const c = p.contact_id != null ? contactById.get(p.contact_id) : null;
                const inner = Array.isArray(p.assets)
                  ? p.assets
                  : Array.isArray(p.packet_json?.assets)
                    ? p.packet_json.assets
                    : [];
                const packetThreadIdNum =
                  p.thread_id != null && String(p.thread_id).trim() !== ""
                    ? Number(p.thread_id)
                    : null;
                const hasPacketThread =
                  packetThreadIdNum != null && Number.isFinite(packetThreadIdNum);
                const isArchived = p.status === "archived";
                const isSent = p.status === "sent";
                const isEditingPacket = packetEditState?.packetId === p.id;
                const canEditContents =
                  !isArchived && !isSent && (p.status === "draft" || p.status === "approved");
                const packetSentLocked = isSent;
                const activeLibraryAssets = assets.filter((a) => a.status === "active");
                const addLibraryOptions = [
                  { value: "", label: "Add from library…" },
                  ...activeLibraryAssets.map((a) => ({
                    value: String(a.id),
                    label: `${a.asset_type}: ${(a.name || "").slice(0, 42) || `#${a.id}`}`,
                  })),
                ];
                return (
                  <div key={p.id} className="space-y-3 rounded-2xl border-2 border-border bg-muted/30 p-5">
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                      <div>
                        <div className="font-medium">{p.title}</div>
                        <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                          <Badge variant="outline">{p.packet_type}</Badge>
                          <Badge variant="secondary">{p.status}</Badge>
                          {packetSentLocked ? (
                            <Badge
                              variant="outline"
                              className="border-amber-600/50 font-normal text-amber-900 dark:text-amber-100"
                            >
                              Sent (locked)
                            </Badge>
                          ) : null}
                          <span>
                            {(isEditingPacket ? packetEditState.draftAssets : inner).length} asset
                            {(isEditingPacket ? packetEditState.draftAssets : inner).length === 1 ? "" : "s"}
                          </span>
                          {hasPacketThread ? (
                            <span className="text-xs">Thread #{packetThreadIdNum}</span>
                          ) : (
                            <span className="text-xs">Run preset</span>
                          )}
                          <span>
                            {c?.company || (p.contact_id != null ? `Contact #${p.contact_id}` : "—")} ·{" "}
                            {c?.name || "—"}
                          </span>
                        </div>
                        {p.description ? (
                          <p className="mt-2 text-sm text-muted-foreground">{p.description}</p>
                        ) : null}
                      </div>
                      {!isEditingPacket ? (
                        <div className="flex shrink-0 flex-nowrap items-center gap-2 overflow-x-auto">
                          {canEditContents ? (
                            <Button
                              type="button"
                              size="sm"
                              variant="secondary"
                              className="shrink-0"
                              onClick={() => beginPacketAssetEdit(p)}
                            >
                              Edit
                            </Button>
                          ) : null}
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            className="shrink-0"
                            onClick={() => void duplicatePacket(p.id)}
                          >
                            Duplicate
                          </Button>
                          {!isArchived ? (
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              className="shrink-0"
                              onClick={() => void patchAssetPacket(p.id, { status: "archived" })}
                            >
                              Archive
                            </Button>
                          ) : null}
                          <Button
                            type="button"
                            size="sm"
                            variant="destructive"
                            className="shrink-0"
                            onClick={() => setPacketToDelete({ id: p.id, title: p.title ?? "" })}
                          >
                            Delete
                          </Button>
                        </div>
                      ) : null}
                    </div>
                    {isEditingPacket ? (
                      <div className="rounded-xl border-2 border-indigo-500/30 bg-muted/20 p-3">
                        <div className="mb-3 grid gap-2">
                          <div className="text-xs font-medium text-muted-foreground">Title</div>
                          <Input
                            value={packetEditState.titleDraft ?? ""}
                            onChange={(e) =>
                              setPacketEditState((st) =>
                                st && st.packetId === p.id ? { ...st, titleDraft: e.target.value } : st,
                              )
                            }
                            placeholder="Packet title"
                          />
                        </div>
                        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                          <div className="text-xs font-medium text-muted-foreground">Assets</div>
                          <div className="flex flex-wrap gap-2">
                            <Button type="button" size="sm" onClick={() => void savePacketAssets()}>
                              Save
                            </Button>
                            <Button type="button" size="sm" variant="outline" onClick={() => cancelPacketAssetEdit()}>
                              Cancel
                            </Button>
                          </div>
                        </div>
                        <ul className="space-y-2 text-sm">
                          {packetEditState.draftAssets.map((item, idx) => (
                            <li
                              key={`${item.asset_id ?? "row"}-${idx}`}
                              className="flex flex-col gap-2 rounded-lg border-2 border-border/60 bg-background/80 p-2 sm:flex-row sm:items-center sm:justify-between"
                            >
                              <div className="min-w-0 flex-1">
                                <div className="flex flex-wrap items-center gap-2">
                                  <Badge variant="outline" className="font-normal">
                                    {item.asset_type || "—"}
                                  </Badge>
                                  <span className="font-medium">{item.title || item.name || `Row ${idx + 1}`}</span>
                                </div>
                                {item.asset_id != null ? (
                                  <span className="mt-0.5 block text-[11px] text-muted-foreground">
                                    Library id #{item.asset_id}
                                  </span>
                                ) : null}
                              </div>
                              <div className="flex flex-wrap gap-1">
                                <Button
                                  type="button"
                                  size="sm"
                                  variant="outline"
                                  disabled={idx === 0}
                                  onClick={() =>
                                    setPacketEditState((st) => {
                                      if (!st || st.packetId !== p.id) return st;
                                      if (idx <= 0) return st;
                                      const next = [...st.draftAssets];
                                      [next[idx - 1], next[idx]] = [next[idx], next[idx - 1]];
                                      return { ...st, draftAssets: next };
                                    })
                                  }
                                >
                                  Up
                                </Button>
                                <Button
                                  type="button"
                                  size="sm"
                                  variant="outline"
                                  disabled={idx >= packetEditState.draftAssets.length - 1}
                                  onClick={() =>
                                    setPacketEditState((st) => {
                                      if (!st || st.packetId !== p.id) return st;
                                      if (idx >= st.draftAssets.length - 1) return st;
                                      const next = [...st.draftAssets];
                                      [next[idx], next[idx + 1]] = [next[idx + 1], next[idx]];
                                      return { ...st, draftAssets: next };
                                    })
                                  }
                                >
                                  Down
                                </Button>
                                <Button
                                  type="button"
                                  size="sm"
                                  variant="destructive"
                                  onClick={() =>
                                    setPacketEditState((st) => {
                                      if (!st || st.packetId !== p.id) return st;
                                      const next = st.draftAssets.filter((_, i) => i !== idx);
                                      return { ...st, draftAssets: next };
                                    })
                                  }
                                >
                                  Remove
                                </Button>
                              </div>
                            </li>
                          ))}
                        </ul>
                        <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-end">
                          <NativeFilterSelect
                            className="w-full sm:max-w-md"
                            value={packetEditState.addPick ?? ""}
                            onValueChange={(v) =>
                              setPacketEditState((st) =>
                                st && st.packetId === p.id ? { ...st, addPick: v } : st,
                              )
                            }
                            options={addLibraryOptions}
                          />
                          <Button
                            type="button"
                            size="sm"
                            variant="secondary"
                            onClick={() => {
                              const st = packetEditState;
                              if (!st || st.packetId !== p.id) return;
                              const pick = st.addPick;
                              if (!pick) return;
                              const aid = Number(pick);
                              const lib = activeLibraryAssets.find((x) => x.id === aid);
                              if (!lib) return;
                              if (st.draftAssets.some((row) => row.asset_id === lib.id)) {
                                setPacketEditState({ ...st, addPick: "" });
                                return;
                              }
                              setPacketEditState({
                                ...st,
                                draftAssets: [...st.draftAssets, libraryRowToPacketSnapshot(lib)],
                                addPick: "",
                              });
                            }}
                          >
                            Add to packet
                          </Button>
                        </div>
                        {!packetEditState.draftAssets.length ? (
                          <p className="mt-2 text-xs text-muted-foreground">
                            Empty packet is allowed. Drafts use merged asset ids when you pick this preset.
                          </p>
                        ) : null}
                      </div>
                    ) : inner.length ? (
                      <div className="rounded-xl border-2 border-border/80 bg-muted/30 p-3">
                        <div className="mb-2 text-xs font-medium text-muted-foreground">Contents</div>
                        <ul className="space-y-2 text-sm">
                          {inner.map((item, idx) => (
                            <li
                              key={item.asset_id ?? idx}
                              className="flex flex-col gap-0.5 border-b border-border/50 pb-2 last:border-0 last:pb-0"
                            >
                              <div className="flex flex-wrap items-center gap-2">
                                <Badge variant="outline" className="font-normal">
                                  {item.asset_type}
                                </Badge>
                                <span className="font-medium">{item.title || item.name}</span>
                              </div>
                              {item.url ? (
                                <a
                                  href={item.url}
                                  className="text-primary underline break-all text-xs"
                                  target="_blank"
                                  rel="noreferrer"
                                >
                                  {item.url}
                                </a>
                              ) : item.file_path ? (
                                <span className="text-xs text-muted-foreground">{item.file_path}</span>
                              ) : null}
                              {item.description ? (
                                <span className="text-xs text-muted-foreground">{item.description}</span>
                              ) : null}
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : (
                      <div className="text-xs text-muted-foreground">
                        No assets in this packet yet — use Edit to add from the library.
                      </div>
                    )}
                  </div>
                );
              })}
              {!assetPackets.length ? (
                <div className="text-sm text-muted-foreground">
                  No saved packets yet — create one above or build from a classified thread (thread modal).
                </div>
              ) : null}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="dead" className="mt-4">
          <Card className="rounded-2xl border-2 border-border bg-card shadow-none">
            <CardHeader>
              <CardTitle>Dead mailboxes</CardTitle>
              <CardDescription>
                Rows are contacts with dead-mailbox health. Run performance shows how many dead-mailbox events were
                recorded (can exceed unique contacts if there were multiple sends). Bounced recipients are under Contacts →
                Bounced. Use Re-search queue for replacements.
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3">
            {deadContacts.map((contact) => {
              const pending = pendingReplacementForContact(contact.id);
              const replacementRow = replacementContactForSource(contact.id);
              return (
                <div
                  key={contact.id}
                  className="flex flex-col gap-4 rounded-2xl border-2 border-red-700/50 bg-red-950/10 p-5 dark:border-red-700/40 dark:bg-red-950/20 lg:flex-row lg:items-center lg:justify-between"
                >
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <AlertTriangle className="h-4 w-4 shrink-0 text-red-600" />
                        <div className="font-medium">{contact.company || "Unnamed company"}</div>
                        <Badge variant="destructive">{contact.email_health}</Badge>
                      </div>
                      <div className="mt-1 text-sm text-muted-foreground">
                        {contact.name || "No name"} · {contact.role || "No role"}
                      </div>
                      <div className="mt-1 text-sm">{contact.email || "No email"}</div>
                    </div>
                    {pending ? (
                      pending.status === "running" ? (
                        <Badge variant="secondary">Processing</Badge>
                      ) : pending.status === "failed" ? (
                        <Badge variant="destructive">Task failed — retry from queue</Badge>
                      ) : pending.status === "no_result" ? (
                        <Badge variant="outline">No result — retry from queue</Badge>
                      ) : (
                        <Badge variant="secondary">In queue</Badge>
                      )
                    ) : replacementRow ? (
                      <Badge
                        variant="outline"
                        className="border-violet-500/60 text-violet-800 dark:text-violet-200"
                      >
                        Replacement in contacts (#{replacementRow.id})
                      </Badge>
                    ) : (
                      <Button type="button" variant="outline" onClick={() => void createReplacementTask(contact)}>
                        Auto create replacement task
                      </Button>
                    )}
                </div>
              );
            })}
            {!deadContacts.length ? (
              <div className="text-sm text-muted-foreground">No dead mailboxes yet.</div>
            ) : null}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="queue" className="mt-4">
          <Card className="rounded-2xl border-2 border-border bg-card shadow-none">
            <CardHeader>
              <CardTitle>Re-search queue</CardTitle>
              <CardDescription>
                Replacement-search and enrichment tasks for this run. Re-run from here when needed.
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3">
            {replacementQueueTasks.map((task) => (
              <div
                key={task.id}
                className="flex flex-col gap-4 rounded-2xl border-2 border-border bg-muted/30 p-5 lg:flex-row lg:items-center lg:justify-between"
              >
                  <div>
                    <div className="font-medium">{task.company || "Unknown company"}</div>
                    <div className="mt-1 text-sm text-muted-foreground">
                      {task.task_type.replaceAll("_", " ")} · {task.reason || "No reason"}
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">Task #{task.id}</div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant="secondary">{task.status}</Badge>
                    <Button
                      type="button"
                      variant="outline"
                      disabled={task.status === "running"}
                      title={
                        task.status === "running" ? "Running" : "Run / retry replacement search"
                      }
                      onClick={() => void rerunResearchTask(task)}
                    >
                      Re-run enrichment
                    </Button>
                  </div>
              </div>
            ))}
            {!replacementQueueTasks.length ? (
              <div className="text-sm text-muted-foreground">No re-search tasks in queue.</div>
            ) : null}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {replyEditing ? (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
          <button
            type="button"
            className="fixed inset-0 bg-black/50"
            aria-label="Close"
            onClick={() => setReplyEditing(null)}
          />
          <div className="relative z-50 w-full max-w-2xl rounded-xl border-2 border-border bg-card p-6 shadow-lg">
            <h2 className="text-lg font-semibold">Edit reply draft</h2>
            <div className="mt-4 grid gap-3">
              <Input
                placeholder="Subject"
                value={replyEditing.subject}
                onChange={(e) =>
                  setReplyEditing((prev) => (prev ? { ...prev, subject: e.target.value } : prev))
                }
              />
              <EmailDraftRichTextEditor
                key={replyEditing.id}
                initialBody={replyEditing.body}
                onChange={(body) => setReplyEditing((prev) => (prev ? { ...prev, body } : prev))}
              />
              <DraftAssetAttachmentsField
                assets={assets}
                assetPackets={assetPackets}
                selectedIds={replyEditing.attached_asset_ids}
                onSelectedIdsChange={(attached_asset_ids) =>
                  setReplyEditing((prev) => (prev ? { ...prev, attached_asset_ids } : prev))
                }
              />
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={() => setReplyEditing(null)}>
                Cancel
              </Button>
              <Button type="button" onClick={() => void saveReplyDraftEdit()}>
                Save
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      {threadModalId != null ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <button
            type="button"
            className="fixed inset-0 bg-black/50"
            aria-label="Close"
            onClick={() => setThreadModalId(null)}
          />
          <div className="relative z-50 flex max-h-[85vh] w-full max-w-5xl flex-col gap-4 rounded-2xl border-2 border-border bg-card p-5 shadow-lg">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <h3 className="text-lg font-semibold">Thread #{threadModalId}</h3>
                {(() => {
                  const mt = threads.find((x) => x.id === threadModalId);
                  if (!mt?.classification) return null;
                  return (
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <Badge
                        variant="default"
                        className={`font-normal ${threadClassificationBadgeClass(mt.classification)}`}
                      >
                        {THREAD_CLASS_LABELS[mt.classification] || mt.classification}
                      </Badge>
                      {mt.classification_confidence ? (
                        <span className="text-xs text-muted-foreground">({mt.classification_confidence})</span>
                      ) : null}
                      {mt.classification_reason ? (
                        <span className="w-full text-xs text-muted-foreground">{mt.classification_reason}</span>
                      ) : null}
                    </div>
                  );
                })()}
              </div>
              <div className="flex shrink-0 flex-wrap items-center justify-end gap-1.5">
                {(() => {
                  const mt = threads.find((x) => x.id === threadModalId);
                  const noDraft = threadOutboundDraftId(mt) == null;
                  const isBounced = mt ? isThreadBouncedRow(mt) : false;
                  const isDead = mt ? isThreadDeadMailboxRow(mt) : false;
                  return (
                    <>
                      <Button
                        type="button"
                        size="icon"
                        variant="outline"
                        disabled={threadDeliveryLlmBusy}
                        title="Re-analyze thread with LLM (bounce vs dead mailbox vs none)"
                        className="h-8 w-8 border-2 border-green-700/80 bg-green-600 text-white hover:bg-green-700 hover:text-white dark:border-green-500 dark:bg-green-600 dark:hover:bg-green-700"
                        aria-label="Analyze delivery with LLM"
                        onClick={() => void analyzeThreadDeliveryWithLlm()}
                      >
                        {threadDeliveryLlmBusy ? (
                          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                        ) : (
                          <RefreshCw className="h-4 w-4" aria-hidden />
                        )}
                      </Button>
                      <Button
                        type="button"
                        size="icon"
                        variant="outline"
                        disabled={noDraft || isBounced}
                        title={
                          noDraft
                            ? "No linked outbound draft"
                            : isBounced
                              ? "Already bounced"
                              : "Mark thread as Bounced (irreversible)"
                        }
                        className="h-8 w-8 border-2 border-amber-600/80 bg-amber-500 text-white hover:bg-amber-600 hover:text-white dark:border-amber-500 dark:bg-amber-600 dark:hover:bg-amber-700"
                        aria-label="Mark as bounced"
                        onClick={() => setThreadManualMarkConfirm("bounced")}
                      >
                        <AlertTriangle className="h-4 w-4" aria-hidden />
                      </Button>
                      <Button
                        type="button"
                        size="icon"
                        variant="outline"
                        disabled={noDraft || isDead}
                        title={
                          noDraft
                            ? "No linked outbound draft"
                            : isDead
                              ? "Already dead mailbox"
                              : "Mark thread as Dead mailbox (irreversible)"
                        }
                        className="h-8 w-8 border-2 border-red-700/80 bg-red-600 text-white hover:bg-red-700 hover:text-white dark:border-red-600 dark:bg-red-700 dark:hover:bg-red-800"
                        aria-label="Mark as dead mailbox"
                        onClick={() => setThreadManualMarkConfirm("dead_mailbox")}
                      >
                        <AlertCircle className="h-4 w-4" aria-hidden />
                      </Button>
                    </>
                  );
                })()}
                <Button type="button" size="sm" variant="ghost" onClick={() => setThreadModalId(null)}>
                  Close
                </Button>
              </div>
            </div>
            {threadDeliveryLlmResult ? (
              <div className="rounded-lg border border-green-800/35 bg-green-950/25 px-3 py-2 text-sm dark:border-green-700/40 dark:bg-green-950/35">
                {threadDeliveryLlmResult.error === "llm_not_configured" ? (
                  <p className="text-amber-700 dark:text-amber-300">
                    LLM is not configured on the server — add API keys in backend settings.
                  </p>
                ) : threadDeliveryLlmResult.error === "llm_failed" ? (
                  <p className="text-amber-700 dark:text-amber-300">
                    The model could not classify this thread — try again later.
                  </p>
                ) : (
                  <>
                    <p>
                      <span className="font-semibold text-green-800 dark:text-green-200">LLM verdict: </span>
                      <span>{threadDeliveryLlmIssueLabel(threadDeliveryLlmResult.delivery_issue)}</span>
                      <span className="text-muted-foreground">
                        {" "}
                        · confidence: {threadDeliveryLlmResult.confidence || "—"}
                      </span>
                    </p>
                    {threadDeliveryLlmResult.reason ? (
                      <p className="mt-1 text-muted-foreground">{threadDeliveryLlmResult.reason}</p>
                    ) : null}
                    {(() => {
                      const fixKind = llmDeliveryIssueToManualMarkKind(threadDeliveryLlmResult.delivery_issue);
                      if (!fixKind || threadModalId == null) return null;
                      const mt = threads.find((x) => x.id === threadModalId);
                      const bounced = mt ? isThreadBouncedRow(mt) : false;
                      const dead = mt ? isThreadDeadMailboxRow(mt) : false;
                      let fixDisabled = threadMarkBusy;
                      let fixTitle =
                        fixKind === "bounced"
                          ? "Confirm and mark as Bounced (same as header)"
                          : "Confirm and mark as Dead mailbox (same as header)";
                      if (fixKind === "bounced") {
                        if (bounced) {
                          fixDisabled = true;
                          fixTitle = "Already bounced";
                        } else if (dead) {
                          fixDisabled = true;
                          fixTitle = "Already dead mailbox";
                        }
                      } else if (fixKind === "dead_mailbox" && dead) {
                        fixDisabled = true;
                        fixTitle = "Already dead mailbox";
                      }
                      return (
                        <div className="mt-3 flex flex-wrap items-center gap-2">
                          <Button
                            type="button"
                            size="sm"
                            disabled={fixDisabled}
                            title={fixTitle}
                            className="border-2 border-green-800/60 bg-green-700 text-white hover:bg-green-800 hover:text-white dark:border-green-600 dark:bg-green-700 dark:hover:bg-green-800"
                            onClick={() => {
                              if (fixDisabled) return;
                              setThreadDeliveryLlmResult(null);
                              setThreadManualMarkConfirm(fixKind);
                            }}
                          >
                            Fix
                          </Button>
                          <span className="text-xs text-muted-foreground">
                            Opens confirmation — applies LLM suggestion to this thread.
                          </span>
                        </div>
                      );
                    })()}
                  </>
                )}
              </div>
            ) : null}
            {(() => {
              const mt = threads.find((x) => x.id === threadModalId);
              if (!mt || !["need_more_info", "interested"].includes(mt.classification)) return null;
              return (
                <div className="flex flex-wrap gap-2 border-b border-border pb-3">
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    onClick={() => void generateReplyDraftForThread(mt.id)}
                  >
                    {mt.classification === "need_more_info" ? "Generate info reply" : "Generate reply draft"}
                  </Button>
                </div>
              );
            })()}
            {(() => {
              if (threadModalId == null) return null;
              const activeForThread = activeThreadReminderByThreadId.get(threadModalId);
              return (
                <div className="space-y-2 border-b border-border pb-3">
                  {activeForThread ? (
                    <div className="space-y-2">
                      <p className="text-sm text-muted-foreground">
                        Active: {new Date(activeForThread.remind_at).toLocaleString()} —{" "}
                        <span className="font-medium text-foreground">{activeForThread.status}</span>
                      </p>
                      <div className="flex flex-wrap gap-2">
                        <Button
                          type="button"
                          size="sm"
                          onClick={() => void patchReminderStatus(activeForThread.id, "completed")}
                        >
                          Complete reminder
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() => void snoozeReminderOneDay(activeForThread)}
                        >
                          Snooze +1 day
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-end">
                      <div className="grid w-full gap-1 sm:max-w-xs">
                        <label className="text-xs text-muted-foreground" htmlFor="thread-remind-at">
                          Remind me later
                        </label>
                        <Input
                          id="thread-remind-at"
                          type="datetime-local"
                          value={threadRemindAtLocal}
                          onChange={(e) => setThreadRemindAtLocal(e.target.value)}
                        />
                      </div>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="border-amber-600/50"
                        onClick={() => void createReminderForThread(threadModalId)}
                      >
                        Set reminder
                      </Button>
                    </div>
                  )}
                </div>
              );
            })()}
            <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto">
              {(threadModalMessagesFull ?? runMessages.filter((m) => m.thread_id === threadModalId)).map(
                (m) => {
                  const rawBody = m.body ?? m.body_preview ?? "";
                  return (
                  <div
                    key={m.id}
                    className={`max-w-[95%] rounded-2xl border-2 p-3 text-sm ${
                      m.direction === "outbound"
                        ? "ml-auto border-primary/30 bg-primary/5"
                        : "mr-auto border-muted-foreground/25 bg-muted/40"
                    }`}
                  >
                    <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                      <Badge variant="outline">{m.direction}</Badge>
                      <span>{new Date(m.created_at).toLocaleString()}</span>
                    </div>
                    <div className="font-medium">{m.subject}</div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      {m.from_email || "—"} → {m.to_email || "—"}
                    </div>
                    {threadMessageBodyLooksLikeHtml(rawBody) ? (
                      <div
                        className="email-thread-body mt-2 max-h-[28rem] overflow-y-auto break-words text-sm leading-relaxed [&_a]:break-all [&_a]:underline [&_blockquote]:my-2 [&_blockquote]:border-l-2 [&_blockquote]:border-muted-foreground/40 [&_blockquote]:pl-3 [&_p]:my-1.5 [&_p]:first:mt-0 [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5"
                        dangerouslySetInnerHTML={{
                          __html: DOMPurify.sanitize(rawBody, {
                            FORBID_TAGS: ["img"],
                            ADD_ATTR: ["target", "rel", "style"],
                          }),
                        }}
                      />
                    ) : (
                      <p className="mt-2 whitespace-pre-wrap leading-relaxed">{rawBody}</p>
                    )}
                  </div>
                );
                },
              )}
              {!(
                threadModalMessagesFull ?? runMessages.filter((m) => m.thread_id === threadModalId)
              ).length ? (
                <div className="text-sm text-muted-foreground">No messages in this thread.</div>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

      {threadManualMarkConfirm ? (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
          <button
            type="button"
            className="fixed inset-0 bg-black/60"
            aria-label="Dismiss"
            disabled={threadMarkBusy}
            onClick={() => {
              if (!threadMarkBusy) setThreadManualMarkConfirm(null);
            }}
          />
          <div className="relative z-[61] w-full max-w-md rounded-2xl border-2 border-border bg-card p-6 shadow-lg">
            <h4 className="text-base font-semibold">
              {threadManualMarkConfirm === "bounced" ? "Mark as Bounced?" : "Mark as Dead mailbox?"}
            </h4>
            <p className="mt-3 text-sm text-muted-foreground leading-relaxed">
              This thread will be labeled as{" "}
              <strong className="text-foreground">
                {threadManualMarkConfirm === "bounced" ? "Bounced" : "Dead mailbox"}
              </strong>
              . The linked outbound draft and contact delivery state will be updated.{" "}
              <strong className="text-foreground">This cannot be undone</strong> from the UI.
            </p>
            <div className="mt-6 flex flex-wrap justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={threadMarkBusy}
                onClick={() => setThreadManualMarkConfirm(null)}
              >
                Cancel
              </Button>
              <Button type="button" disabled={threadMarkBusy} onClick={() => void confirmThreadManualMark()}>
                {threadMarkBusy ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                ) : null}
                Confirm
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      <Dialog
        open={packetToDelete != null}
        onOpenChange={(o) => {
          if (!o) setPacketToDelete(null);
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Delete packet?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            Are you sure you want to delete this packet?
            {packetToDelete?.title ? ` “${packetToDelete.title}”` : ""} This cannot be undone.
          </p>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button type="button" variant="outline" onClick={() => setPacketToDelete(null)}>
              Cancel
            </Button>
            <Button type="button" variant="destructive" onClick={() => void confirmDeletePacket()}>
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
