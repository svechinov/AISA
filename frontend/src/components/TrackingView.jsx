import { useCallback, useEffect, useMemo, useState } from "react";
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
  Send,
} from "lucide-react";

const ENV_API = import.meta.env.VITE_API_BASE?.trim();
const API_BASE =
  ENV_API && ENV_API.length > 0
    ? ENV_API.replace(/\/$/, "")
    : import.meta.env.DEV
      ? "/api"
      : "http://127.0.0.1:8000";

const EVENT_FILTER_OPTS = [
  { value: "all", label: "All events" },
  { value: "queued", label: "Queued" },
  { value: "sent", label: "Sent" },
  { value: "replied", label: "Replied" },
  { value: "bounced", label: "Bounced" },
  { value: "dead_mailbox", label: "Dead mailbox" },
  { value: "failed", label: "Failed" },
  { value: "reply_sent", label: "Reply sent" },
];

const THREAD_CLASSIFICATION_FILTER_OPTS = [
  { value: "all", label: "All" },
  { value: "interested", label: "Interested" },
  { value: "need_more_info", label: "Need info" },
  { value: "not_interested", label: "Not interested" },
];

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

export default function TrackingView({
  runId,
  runSignatureHtml = "",
  activeTab,
  onActiveTabChange,
  singleTabMode = false,
  onRunWorkspaceRefresh,
}) {
  const showSignaturePlaceholder = Boolean((runSignatureHtml ?? "").trim());
  const [events, setEvents] = useState([]);
  const [summary, setSummary] = useState(null);
  const [drafts, setDrafts] = useState([]);
  const [contacts, setContacts] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [threads, setThreads] = useState([]);
  const [runMessages, setRunMessages] = useState([]);
  const [threadModalId, setThreadModalId] = useState(null);
  const [threadRemindAtLocal, setThreadRemindAtLocal] = useState("");
  const [threadClassFilter, setThreadClassFilter] = useState("all");
  const [replyDrafts, setReplyDrafts] = useState([]);
  const [reminders, setReminders] = useState([]);
  const [assets, setAssets] = useState([]);
  const [assetPackets, setAssetPackets] = useState([]);
  const [newAssetName, setNewAssetName] = useState("");
  const [newAssetType, setNewAssetType] = useState("deck");
  const [newAssetUrl, setNewAssetUrl] = useState("");
  /** packet assets edit session: draft list + library picker + title */
  const [packetEditState, setPacketEditState] = useState(null);
  const [packetToDelete, setPacketToDelete] = useState(null);
  const [newPacketForm, setNewPacketForm] = useState({
    title: "",
    draftAssets: [],
    addPick: "",
  });
  /** reply draft id → send-preview fields + attachment summary */
  const [replySendPreviewByDraftId, setReplySendPreviewByDraftId] = useState({});
  /** When false, send-preview block is collapsed even if data is cached */
  const [replyPreviewExpanded, setReplyPreviewExpanded] = useState({});
  const [replyEditing, setReplyEditing] = useState(null);
  const [filter, setFilter] = useState("all");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [innerTab, setInnerTab] = useState("events");

  useEffect(() => {
    setInnerTab(activeTab || "events");
  }, [runId, activeTab]);

  const tabValue = activeTab || innerTab;
  const handleTabChange = (v) => {
    setInnerTab(v);
    onActiveTabChange?.(v);
  };

  const load = useCallback(async () => {
    if (!runId) return;
    setLoading(true);
    setError("");
    try {
      const [er, sr, dr, cr, tr, th, msg, rep, rem, ast, apk] = await Promise.all([
        fetch(`${API_BASE}/email-events/run/${runId}`),
        fetch(`${API_BASE}/sending/runs/${runId}/summary`),
        fetch(`${API_BASE}/email-drafts/run/${runId}`),
        fetch(`${API_BASE}/contacts/run/${runId}`),
        fetch(`${API_BASE}/research-tasks/run/${runId}`),
        fetch(`${API_BASE}/email-threads/run/${runId}`),
        fetch(`${API_BASE}/email-threads/run/${runId}/messages`),
        fetch(`${API_BASE}/reply-drafts/run/${runId}`),
        fetch(`${API_BASE}/reminders/run/${runId}`),
        fetch(`${API_BASE}/assets`),
        fetch(`${API_BASE}/asset-packets/run/${runId}`),
      ]);
      if (!er.ok) throw new Error(`Events: ${er.status}`);
      if (!sr.ok) throw new Error(`Summary: ${sr.status}`);
      const [e, s] = await Promise.all([er.json(), sr.json()]);
      setEvents(Array.isArray(e) ? e : []);
      setSummary(s || null);

      const d = dr.ok ? await dr.json() : [];
      setDrafts(Array.isArray(d) ? d : []);

      const c = cr.ok ? await cr.json() : [];
      setContacts(Array.isArray(c) ? c : []);

      const t = tr.ok ? await tr.json() : [];
      setTasks(Array.isArray(t) ? t : []);

      const threadData = th.ok ? await th.json() : [];
      setThreads(Array.isArray(threadData) ? threadData : []);
      const msgData = msg.ok ? await msg.json() : [];
      setRunMessages(Array.isArray(msgData) ? msgData : []);
      const repData = rep.ok ? await rep.json() : [];
      setReplyDrafts(Array.isArray(repData) ? repData : []);
      const remData = rem.ok ? await rem.json() : [];
      setReminders(Array.isArray(remData) ? remData : []);
      const astData = ast.ok ? await ast.json() : [];
      setAssets(Array.isArray(astData) ? astData : []);
      const apkData = apk.ok ? await apk.json() : [];
      setAssetPackets(Array.isArray(apkData) ? apkData : []);
    } catch (err) {
      setError(String(err?.message || err));
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    if (!runId) {
      setEvents([]);
      setSummary(null);
      setDrafts([]);
      setContacts([]);
      setTasks([]);
      setThreads([]);
      setRunMessages([]);
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
      setThreadClassFilter("all");
      return;
    }
    void load();
    const i = setInterval(() => void load(), 3000);
    return () => clearInterval(i);
  }, [runId, load]);

  useEffect(() => {
    if (threadModalId == null) {
      setThreadRemindAtLocal("");
      return;
    }
    const d = new Date();
    d.setDate(d.getDate() + 3);
    d.setHours(9, 0, 0, 0);
    setThreadRemindAtLocal(toDatetimeLocalValue(d));
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

  const filteredEvents = useMemo(() => {
    return events.filter((e) => {
      if (filter === "all") return true;
      return e.event_type === filter;
    });
  }, [events, filter]);

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

  const filteredThreads = useMemo(() => {
    if (threadClassFilter === "all") return threads;
    return threads.filter((t) => t.classification === threadClassFilter);
  }, [threads, threadClassFilter]);

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
  }, [filteredThreads, threadNeedsInboundAttention, activeThreadReminderByThreadId]);

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
    for (const event of filteredEvents) {
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
  }, [filteredEvents, drafts]);

  const deadContacts = useMemo(() => {
    return contacts.filter((c) => c.email_health === "dead_mailbox" || c.email_health === "bounced");
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

  async function sendSingleDraft(draftId) {
    try {
      await fetch(`${API_BASE}/sending/drafts/${draftId}/send`, { method: "POST" });
      await load();
    } catch {
      setError("Send failed — check network / backend.");
    }
  }

  async function sendApprovedDrafts() {
    if (!runId) return;
    try {
      await fetch(`${API_BASE}/sending/runs/${runId}/send`, { method: "POST" });
      await load();
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
      await load();
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
      await load();
    } catch {
      setError("Send replacement drafts failed — check network / backend.");
    }
  }

  async function mockTracking(draftId, pathSuffix) {
    try {
      await fetch(`${API_BASE}/tracking/drafts/${draftId}/${pathSuffix}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ payload_json: {} }),
      });
      await load();
    } catch {
      setError("Mock tracking call failed.");
    }
  }

  async function mockInboxReply(draft) {
    if (!draft?.id) return;
    setError("");
    const contact = contactById.get(draft.contact_id);
    const fromEmail =
      contact?.email?.trim() ||
      `buyer@${(contact?.company || draft.company || "company")
        .toLowerCase()
        .replace(/\s+/g, "")}.example`;
    const subject = draft.subject?.startsWith("Re:") ? draft.subject : `Re: ${draft.subject || ""}`.trim();
    try {
      const res = await fetch(`${API_BASE}/inbox/mock-receive`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          draft_id: draft.id,
          from_email: fromEmail,
          to_email: "inbox@ai-biz-os.local",
          subject,
          body: "Thanks, send me more information.",
        }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        setError(detail?.detail ? String(detail.detail) : `Inbox mock failed (${res.status})`);
        return;
      }
      await load();
    } catch {
      setError("Mock inbox reply failed — check network / backend.");
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
      await load();
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
      await load();
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
      await load();
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
      await load();
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
      await load();
    } catch {
      setError("Create asset failed.");
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
        await load();
        onRunWorkspaceRefresh?.();
        return;
      }
      await load();
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
      await load();
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
    const inner = Array.isArray(p?.packet_json?.assets) ? p.packet_json.assets : [];
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
      await load();
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
      await load();
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
      await load();
    } catch {
      setError("Create packet failed.");
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
      await load();
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
      await load();
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
      await load();
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
      await load();
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
      await load();
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

      {error ? <div className="text-sm text-destructive">{error}</div> : null}

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
              <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
                <div>
                  <CardTitle>Events</CardTitle>
                  <CardDescription>Email history is grouped by draft.</CardDescription>
                </div>
                <NativeFilterSelect
                  className="w-full md:w-[240px]"
                  value={filter}
                  onValueChange={setFilter}
                  options={EVENT_FILTER_OPTS}
                />
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-4">
                {groupedEvents.map(({ draftId, draft, events: draftEvents }) => {
                  const chainEndsDeadMailbox =
                    draftEvents.length > 0 &&
                    draftEvents[draftEvents.length - 1].event_type === "dead_mailbox";
                  return (
                  <div
                    key={draftId}
                    className={
                      chainEndsDeadMailbox
                        ? "rounded-2xl border-2 border-red-700/50 bg-red-950/10 p-4 dark:border-red-700/40 dark:bg-red-950/20"
                        : "rounded-2xl border-2 border-border bg-muted/25 p-4"
                    }
                  >
                    <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                      <div>
                        <div className="flex flex-wrap items-center gap-2">
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
                        <div className="mt-1 text-sm text-muted-foreground">{draft?.to_email || "No recipient"}</div>
                        <div className="mt-1 text-sm">{draft?.subject || "No subject"}</div>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {canShowSend(draft) ? (
                          <Button type="button" size="sm" onClick={() => void sendSingleDraft(draftId)}>
                            Send
                          </Button>
                        ) : null}
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          disabled={draft?.status !== "sent"}
                          title={
                            draft?.status !== "sent"
                              ? "Send the email first — a thread will appear"
                              : "Mock reply via inbox (inbound message)"
                          }
                          onClick={() => void mockInboxReply(draft)}
                        >
                          Mock reply (inbox)
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() => void mockTracking(draftId, "mock-bounce")}
                        >
                          Mock bounce
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() => void mockTracking(draftId, "mock-dead-mailbox")}
                        >
                          Mock dead mailbox
                        </Button>
                      </div>
                    </div>
                    <div
                      className={`mt-4 space-y-3 border-t pt-4 ${chainEndsDeadMailbox ? "border-red-700/30" : "border-border/50"}`}
                    >
                      {draftEvents.map((event, index) => (
                        <div key={event.id}>
                          <div
                            className={`flex items-center justify-between gap-3 rounded-2xl border-2 p-3 ${chainEndsDeadMailbox ? "border-red-700/35 bg-red-950/15 dark:border-red-700/30 dark:bg-red-950/25" : "border-border bg-muted/40"}`}
                          >
                            <div className="flex items-center gap-3">
                              <div className={`rounded-xl p-2 ${eventTone(event.event_type)}`}>
                                {eventIcon(event.event_type)}
                              </div>
                              <div>
                                <div className="font-medium capitalize">{event.event_type.replaceAll("_", " ")}</div>
                                <div className="text-xs text-muted-foreground">Event #{event.id}</div>
                              </div>
                            </div>
                            <Badge variant="secondary">{new Date(event.created_at).toLocaleString()}</Badge>
                          </div>
                          {index < draftEvents.length - 1 ? <Separator className="my-2" /> : null}
                        </div>
                      ))}
                    </div>
                  </div>
                  );
                })}
                {!groupedEvents.length ? (
                  <div className="text-sm text-muted-foreground">No events yet.</div>
                ) : null}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="threads" className="mt-4">
          <Card className="rounded-2xl border-2 border-border bg-card shadow-none">
            <CardHeader>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
                <div>
                  <CardTitle>Threads</CardTitle>
                  <CardDescription>
                    Threads appear after you send a draft.                     Open a thread for messages, generating a reply, or a reminder.{" "}
                    <strong>Inbound</strong> and <strong>Remind later</strong> badges (after inbound, before dead mailbox)
                    pin threads toward the top.
                  </CardDescription>
                </div>
                <NativeFilterSelect
                  className="w-full sm:w-[220px]"
                  value={threadClassFilter}
                  onValueChange={setThreadClassFilter}
                  options={THREAD_CLASSIFICATION_FILTER_OPTS}
                />
              </div>
            </CardHeader>
            <CardContent className="grid gap-3">
            {sortedFilteredThreads.map((t) => {
              const contact = contactById.get(t.contact_id);
              const counts = messageCountsByThreadId.get(t.id) || { in: 0, out: 0 };
              const label = t.classification;
              const linkedDraft = t.draft_id != null ? draftById.get(t.draft_id) : undefined;
              const draftLifecycle = linkedDraft
                ? linkedDraft.tracking_status ?? linkedDraft.status
                : null;
              const isThreadDeadMailbox =
                draftLifecycle === "dead_mailbox" || contact?.email_health === "dead_mailbox";
              const needsInboundAttention = Boolean(threadNeedsInboundAttention.get(t.id));
              const threadRemind = activeThreadReminderByThreadId.get(t.id);
              return (
                <div
                  key={t.id}
                  className={
                    isThreadDeadMailbox
                      ? "flex flex-col gap-3 rounded-2xl border-2 border-red-700/50 bg-red-950/10 p-5 dark:border-red-700/40 dark:bg-red-950/20 sm:flex-row sm:items-center sm:justify-between"
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
                        ) : null}
                        <div className="font-medium">{contact?.company || `Contact #${t.contact_id}`}</div>
                        {needsInboundAttention ? (
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
                        ) : (
                          <Badge variant="outline" className="font-normal text-muted-foreground">
                            —
                          </Badge>
                        )}
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
              <div className="text-sm text-muted-foreground">No threads match the selected classification.</div>
            ) : null}
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
                            onClick={() =>
                              setReplyEditing({
                                id: rd.id,
                                subject: rd.subject ?? "",
                                body: rd.body ?? "",
                                attached_asset_ids: normalizeAttachedAssetIds(rd.attached_asset_ids),
                              })
                            }
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
                                    <code className="text-[11px]">packet_json.assets</code> is empty — add assets to the
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
            <div className="rounded-2xl border-2 border-border bg-muted/25 p-4">
              <div className="mb-3 text-sm font-medium">Add asset</div>
              <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
              <div className="min-w-[140px] flex-1 space-y-1">
                <div className="text-xs text-muted-foreground">Name</div>
                <Input value={newAssetName} onChange={(e) => setNewAssetName(e.target.value)} placeholder="Pitch deck Q1" />
              </div>
              <div className="min-w-[140px] space-y-1">
                <div className="text-xs text-muted-foreground">Type</div>
                <NativeFilterSelect
                  value={newAssetType}
                  onValueChange={setNewAssetType}
                  options={ASSET_LIBRARY_TYPE_OPTS}
                />
              </div>
              <div className="min-w-[180px] flex-1 space-y-1">
                <div className="text-xs text-muted-foreground">URL</div>
                <Input
                  value={newAssetUrl}
                  onChange={(e) => setNewAssetUrl(e.target.value)}
                  placeholder="https://..."
                />
              </div>
              <Button type="button" onClick={() => void submitNewAsset()}>
                Add asset
              </Button>
              </div>
            </div>
          <div className="grid gap-3">
            {assets.map((a) => (
              <div key={a.id} className="rounded-2xl border-2 border-border bg-muted/30 p-5">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="outline">{a.asset_type}</Badge>
                    <Badge variant="secondary">{a.status}</Badge>
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
                    <Button type="button" size="sm" onClick={() => void createRunPacket()}>
                      Create packet
                    </Button>
                  </div>
                );
              })()}
              {assetPackets.map((p) => {
                const c = p.contact_id != null ? contactById.get(p.contact_id) : null;
                const inner = Array.isArray(p.packet_json?.assets) ? p.packet_json.assets : [];
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
                Contacts marked with dead-mailbox email health. Create replacement task from Re-search queue.
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
          <div className="relative z-50 flex max-h-[85vh] w-full max-w-lg flex-col gap-4 rounded-2xl border-2 border-border bg-card p-5 shadow-lg">
            <div className="flex items-start justify-between gap-2">
              <div>
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
              <Button type="button" size="sm" variant="ghost" onClick={() => setThreadModalId(null)}>
                Close
              </Button>
            </div>
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
                  <div className="text-xs font-medium text-muted-foreground">Reminder</div>
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
              {runMessages
                .filter((m) => m.thread_id === threadModalId)
                .map((m) => (
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
                    <p className="mt-2 whitespace-pre-wrap leading-relaxed">{m.body}</p>
                  </div>
                ))}
              {!runMessages.some((m) => m.thread_id === threadModalId) ? (
                <div className="text-sm text-muted-foreground">No messages in this thread.</div>
              ) : null}
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
