import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { NativeFilterSelect } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  AlertTriangle,
  FilePenLine,
  MailCheck,
  MailWarning,
  Mails,
  RefreshCw,
  Reply,
  Send,
  XCircle,
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

const NEXT_ACTION_CLASSIFICATIONS = ["interested", "need_more_info", "ask_later", "not_interested"];

const NEXT_ACTION_HINTS = {
  interested: "Will create: Reply to interested lead",
  need_more_info: "Will create: Send more information",
  ask_later: "Will create: Follow up later",
  not_interested: "Will create: Close thread",
};

const REMINDER_ACTIVE_STATUSES = ["scheduled", "triggered", "snoozed"];

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
  activeTab,
  onActiveTabChange,
  singleTabMode = false,
}) {
  const [events, setEvents] = useState([]);
  const [summary, setSummary] = useState(null);
  const [drafts, setDrafts] = useState([]);
  const [contacts, setContacts] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [threads, setThreads] = useState([]);
  const [runMessages, setRunMessages] = useState([]);
  const [threadModalId, setThreadModalId] = useState(null);
  const [threadClassFilter, setThreadClassFilter] = useState("all");
  const [replyDrafts, setReplyDrafts] = useState([]);
  const [followUpTasks, setFollowUpTasks] = useState([]);
  const [reminders, setReminders] = useState([]);
  const [assets, setAssets] = useState([]);
  const [assetPackets, setAssetPackets] = useState([]);
  const [newAssetName, setNewAssetName] = useState("");
  const [newAssetType, setNewAssetType] = useState("deck");
  const [newAssetUrl, setNewAssetUrl] = useState("");
  /** packet id → selected reply draft id string for attach flow */
  const [packetAttachDraftId, setPacketAttachDraftId] = useState({});
  /** packet assets edit session: draft list + library picker */
  const [packetEditState, setPacketEditState] = useState(null);
  /** reply draft id → send-preview fields + attachment summary */
  const [replySendPreviewByDraftId, setReplySendPreviewByDraftId] = useState({});
  const [replyEditing, setReplyEditing] = useState(null);
  const [filter, setFilter] = useState("all");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [actionNote, setActionNote] = useState("");
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
      const [er, sr, dr, cr, tr, th, msg, rep, fut, rem, ast, apk] = await Promise.all([
        fetch(`${API_BASE}/email-events/run/${runId}`),
        fetch(`${API_BASE}/sending/runs/${runId}/summary`),
        fetch(`${API_BASE}/email-drafts/run/${runId}`),
        fetch(`${API_BASE}/contacts/run/${runId}`),
        fetch(`${API_BASE}/research-tasks/run/${runId}`),
        fetch(`${API_BASE}/email-threads/run/${runId}`),
        fetch(`${API_BASE}/email-threads/run/${runId}/messages`),
        fetch(`${API_BASE}/reply-drafts/run/${runId}`),
        fetch(`${API_BASE}/follow-up-tasks/run/${runId}`),
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
      const futData = fut.ok ? await fut.json() : [];
      setFollowUpTasks(Array.isArray(futData) ? futData : []);
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
      setFollowUpTasks([]);
      setReminders([]);
      setAssets([]);
      setAssetPackets([]);
      setNewAssetName("");
      setNewAssetType("deck");
      setNewAssetUrl("");
      setPacketAttachDraftId({});
      setPacketEditState(null);
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

  const eventTone = (type) => {
    if (type === "sent") return "bg-green-100 text-green-700 border-green-200 dark:bg-green-950/40 dark:text-green-200 dark:border-green-800";
    if (type === "queued") return "bg-slate-100 text-slate-800 border-slate-200 dark:bg-slate-900/50 dark:text-slate-200";
    if (type === "replied") return "bg-blue-100 text-blue-700 border-blue-200 dark:bg-blue-950/40 dark:text-blue-200";
    if (type === "bounced") return "bg-yellow-100 text-yellow-800 border-yellow-200 dark:bg-yellow-950/40 dark:text-yellow-100";
    if (type === "dead_mailbox") return "bg-red-100 text-red-700 border-red-200 dark:bg-red-950/40 dark:text-red-200";
    if (type === "failed") return "bg-red-100 text-red-700 border-red-200 dark:bg-red-950/40 dark:text-red-200";
    if (type === "reply_sent") return "bg-teal-100 text-teal-800 border-teal-200 dark:bg-teal-950/40 dark:text-teal-200";
    return "bg-muted text-muted-foreground border-border";
  };

  const eventIcon = (type) => {
    if (type === "sent") return <Send className="h-4 w-4" />;
    if (type === "replied") return <Reply className="h-4 w-4" />;
    if (type === "bounced") return <MailWarning className="h-4 w-4" />;
    if (type === "dead_mailbox") return <XCircle className="h-4 w-4" />;
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

  const activeReminderByFollowUpTaskId = useMemo(() => {
    const candidates = reminders.filter(
      (r) => r.follow_up_task_id && REMINDER_ACTIVE_STATUSES.includes(r.status),
    );
    candidates.sort((a, b) => b.id - a.id);
    const m = new Map();
    for (const r of candidates) {
      if (!m.has(r.follow_up_task_id)) m.set(r.follow_up_task_id, r);
    }
    return m;
  }, [reminders]);

  const filteredThreads = useMemo(() => {
    if (threadClassFilter === "all") return threads;
    return threads.filter((t) => t.classification === threadClassFilter);
  }, [threads, threadClassFilter]);

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
      const data = await res.json();
      const created = data.drafts_created ?? 0;
      const skipped = (data.skipped_existing_draft_contact_ids ?? []).length;
      const found = data.replacement_contacts_found ?? 0;
      setActionNote(
        `Replacement drafts: ${created} created, ${skipped} skipped (approved replacement contacts: ${found}).`,
      );
      window.setTimeout(() => setActionNote(""), 10000);
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
      const data = await res.json();
      await load();
      const found = data?.replacement_drafts_found ?? 0;
      const sent = data?.sent ?? 0;
      const failed = data?.failed ?? 0;
      setActionNote(`Replacement drafts: found ${found}, sent ${sent}, failed ${failed}.`);
      window.setTimeout(() => setActionNote(""), 10000);
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
      setActionNote("Mock reply recorded via inbox (inbound message + thread updated).");
      window.setTimeout(() => setActionNote(""), 8000);
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
      setActionNote("");
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
      const data = await res.json();
      await load();
      setActionNote(
        data.deduplicated
          ? `Reply draft already exists (#${data.reply_draft_id}).`
          : `Reply draft #${data.reply_draft_id} created.`,
      );
      window.setTimeout(() => setActionNote(""), 8000);
    } catch {
      setError("Generate reply draft failed — check network / backend.");
    }
  }

  async function createNextActionForThread(threadId) {
    setError("");
    try {
      const res = await fetch(`${API_BASE}/follow-up-tasks/thread/${threadId}/create-next-action`, {
        method: "POST",
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        setError(detail?.detail ? String(detail.detail) : `Create failed (${res.status})`);
        return;
      }
      const data = await res.json();
      await load();
      setActionNote(
        data.deduplicated
          ? `Next action already exists (#${data.task_id}, ${data.task_type}).`
          : `Next action #${data.task_id} created (${data.task_type}).`,
      );
      window.setTimeout(() => setActionNote(""), 8000);
    } catch {
      setError("Create next action failed.");
    }
  }

  async function patchFollowUpTaskStatus(taskId, status) {
    setError("");
    try {
      const res = await fetch(`${API_BASE}/follow-up-tasks/${taskId}/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        setError(detail?.detail ? String(detail.detail) : `Update failed (${res.status})`);
        return;
      }
      await load();
    } catch {
      setError("Update follow-up task failed.");
    }
  }

  async function createReminderForFollowUpTask(taskId) {
    setError("");
    try {
      const res = await fetch(`${API_BASE}/reminders/follow-up-task/${taskId}/create`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ remind_at: null }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        setError(detail?.detail ? String(detail.detail) : `Create reminder failed (${res.status})`);
        return;
      }
      const data = await res.json();
      await load();
      setActionNote(
        data.deduplicated
          ? `Reminder already active (#${data.reminder_id}).`
          : `Reminder #${data.reminder_id} created.`,
      );
      window.setTimeout(() => setActionNote(""), 8000);
    } catch {
      setError("Create reminder failed.");
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
    } catch {
      setError("Snooze failed.");
    }
  }

  async function triggerDueReminders() {
    setError("");
    try {
      const res = await fetch(`${API_BASE}/reminders/trigger-due`, { method: "POST" });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        setError(detail?.detail ? String(detail.detail) : `Trigger failed (${res.status})`);
        return;
      }
      const data = await res.json();
      await load();
      setActionNote(
        `Trigger due: found ${data.due_found ?? 0}, set triggered ${data.triggered ?? 0}.`,
      );
      window.setTimeout(() => setActionNote(""), 8000);
    } catch {
      setError("Trigger due reminders failed.");
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

  async function buildAssetPacketForThread(threadId) {
    setError("");
    try {
      const res = await fetch(`${API_BASE}/asset-packets/thread/${threadId}/build`, { method: "POST" });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        setError(detail?.detail ? String(detail.detail) : `Build packet failed (${res.status})`);
        return;
      }
      const data = await res.json();
      await load();
      setActionNote(
        data.deduplicated
          ? `Asset packet already exists (#${data.packet_id}).`
          : `Asset packet #${data.packet_id} built.`,
      );
      window.setTimeout(() => setActionNote(""), 8000);
    } catch {
      setError("Build asset packet failed.");
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

  function beginPacketAssetEdit(packetId, assetsArray) {
    setPacketEditState({
      packetId,
      draftAssets: clonePacketAssetsForEdit(Array.isArray(assetsArray) ? assetsArray : []),
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

  async function savePacketAsNew(packetId) {
    setError("");
    try {
      const res = await fetch(`${API_BASE}/asset-packets/${packetId}/clone`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(typeof data.detail === "string" ? data.detail : `Clone failed (${res.status})`);
        return;
      }
      await load();
      setActionNote(`Packet cloned as draft #${data.id}.`);
      window.setTimeout(() => setActionNote(""), 8000);
    } catch {
      setError("Save as new packet failed.");
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

  async function attachPacketToReplyDraft(packetId) {
    const pick = packetAttachDraftId[packetId];
    if (!pick || pick === "") {
      setError("Select a reply draft.");
      return;
    }
    const replyDraftId = Number(pick);
    if (!Number.isFinite(replyDraftId)) {
      setError("Invalid reply draft.");
      return;
    }
    setError("");
    try {
      const res = await fetch(`${API_BASE}/asset-packets/${packetId}/attach-reply-draft`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reply_draft_id: replyDraftId }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        setError(detail?.detail ? String(detail.detail) : `Attach failed (${res.status})`);
        return;
      }
      await load();
    } catch {
      setError("Attach packet failed.");
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
            <Button type="button" variant="outline" onClick={() => void load()} disabled={loading}>
              <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </Button>
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
      ) : (
        <div className="flex flex-wrap justify-end gap-2">
          <Button type="button" variant="outline" size="sm" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>
      )}

      {error ? <div className="text-sm text-destructive">{error}</div> : null}
      {actionNote ? <div className="text-sm text-muted-foreground">{actionNote}</div> : null}

      {!singleTabMode && summary ? (
        <div className="grid gap-4 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6">
          <Card className="rounded-2xl border border-border bg-card shadow-none">
            <CardContent className="p-4">
              <div className="text-xs text-muted-foreground">Sent</div>
              <div className="mt-1 text-2xl font-semibold">{summary.drafts_sent || 0}</div>
            </CardContent>
          </Card>
          <Card className="rounded-2xl border border-border bg-card shadow-none">
            <CardContent className="p-4">
              <div className="text-xs text-muted-foreground">Replies</div>
              <div className="mt-1 text-2xl font-semibold">{summary.events_replied || 0}</div>
            </CardContent>
          </Card>
          <Card className="rounded-2xl border border-border bg-card shadow-none">
            <CardContent className="p-4">
              <div className="text-xs text-muted-foreground">Failed</div>
              <div className="mt-1 text-2xl font-semibold">{summary.events_failed || 0}</div>
            </CardContent>
          </Card>
          <Card className="rounded-2xl border border-border bg-card shadow-none">
            <CardContent className="p-4">
              <div className="text-xs text-muted-foreground">Bounced</div>
              <div className="mt-1 text-2xl font-semibold">{summary.events_bounced || 0}</div>
            </CardContent>
          </Card>
          <Card className="rounded-2xl border border-border bg-card shadow-none">
            <CardContent className="p-4">
              <div className="text-xs text-muted-foreground">Dead mailboxes</div>
              <div className="mt-1 text-2xl font-semibold">{summary.events_dead_mailbox || 0}</div>
            </CardContent>
          </Card>
          <Card className="rounded-2xl border border-border bg-card shadow-none">
            <CardContent className="p-4">
              <div className="text-xs text-muted-foreground">Replacement tasks</div>
              <div className="mt-1 text-2xl font-semibold">{summary.replacement_email_tasks_open || 0}</div>
            </CardContent>
          </Card>
          <Card className="rounded-2xl border border-border bg-card shadow-none">
            <CardContent className="p-4">
              <div className="text-xs text-muted-foreground">Reply rate</div>
              <div className="mt-1 text-2xl font-semibold">{replyRate}%</div>
              <div className="mt-0.5 text-[11px] text-muted-foreground">Replies / sent</div>
            </CardContent>
          </Card>
          <Card className="rounded-2xl border border-border bg-card shadow-none">
            <CardContent className="p-4">
              <div className="text-xs text-muted-foreground">Repl. drafts</div>
              <div className="mt-1 text-2xl font-semibold">{summary.replacement_drafts_generated ?? 0}</div>
              <div className="mt-0.5 text-[11px] text-muted-foreground">By replacement contacts</div>
            </CardContent>
          </Card>
          <Card className="rounded-2xl border border-border bg-card shadow-none">
            <CardContent className="p-4">
              <div className="text-xs text-muted-foreground">Repl. sent</div>
              <div className="mt-1 text-2xl font-semibold">{summary.replacement_drafts_sent ?? 0}</div>
              <div className="mt-0.5 text-[11px] text-muted-foreground">Replacement drafts</div>
            </CardContent>
          </Card>
          <Card className="rounded-2xl border border-border bg-card shadow-none">
            <CardContent className="p-4">
              <div className="text-xs text-muted-foreground">Threads</div>
              <div className="mt-1 text-2xl font-semibold">{summary.threads_total ?? 0}</div>
              <div className="mt-0.5 text-[11px] text-muted-foreground">
                Replied: {summary.threads_replied ?? 0}
              </div>
            </CardContent>
          </Card>
          <Card className="rounded-2xl border border-border bg-card shadow-none">
            <CardContent className="p-4">
              <div className="text-xs text-muted-foreground">Inbox / Out</div>
              <div className="mt-1 text-2xl font-semibold">
                {summary.messages_inbound ?? 0} / {summary.messages_outbound ?? 0}
              </div>
              <div className="mt-0.5 text-[11px] text-muted-foreground">Messages</div>
            </CardContent>
          </Card>
          <Card className="rounded-2xl border border-border bg-card shadow-none">
            <CardContent className="p-4">
              <div className="text-xs text-muted-foreground">Reply drafts</div>
              <div className="mt-1 text-2xl font-semibold">{summary.reply_drafts_generated ?? 0}</div>
              <div className="mt-0.5 text-[11px] text-muted-foreground">
                Appr. {summary.reply_drafts_approved ?? 0} · Edit {summary.reply_drafts_edited ?? 0} · Sent{" "}
                {summary.reply_drafts_sent ?? 0}
              </div>
            </CardContent>
          </Card>
          <Card className="rounded-2xl border border-border bg-card shadow-none">
            <CardContent className="p-4">
              <div className="text-xs text-muted-foreground">Next actions</div>
              <div className="mt-1 text-2xl font-semibold">{summary.follow_up_tasks_open ?? 0}</div>
              <div className="mt-0.5 text-[11px] text-muted-foreground">
                Open · In prog. {summary.follow_up_tasks_in_progress ?? 0} · Done{" "}
                {summary.follow_up_tasks_completed ?? 0} · Total {summary.follow_up_tasks_total ?? 0}
              </div>
            </CardContent>
          </Card>
          <Card className="rounded-2xl border border-border bg-card shadow-none">
            <CardContent className="p-4">
              <div className="text-xs text-muted-foreground">Reminders</div>
              <div className="mt-1 text-2xl font-semibold">{summary.reminders_scheduled ?? 0}</div>
              <div className="mt-0.5 text-[11px] text-muted-foreground">
                Trig. {summary.reminders_triggered ?? 0} · Snooze {summary.reminders_snoozed ?? 0} · Done{" "}
                {summary.reminders_completed ?? 0} · Total {summary.reminders_total ?? 0}
              </div>
            </CardContent>
          </Card>
          <Card className="rounded-2xl border border-border bg-card shadow-none">
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

      <Card className="rounded-2xl border border-border bg-card shadow-sm">
        <CardContent className="pt-6">
      <Tabs
        value={singleTabMode ? activeTab ?? tabValue : tabValue}
        onValueChange={handleTabChange}
        className="w-full"
      >
        {!singleTabMode ? (
          <TabsList className="flex h-auto min-h-10 w-full flex-wrap gap-1 rounded-2xl border border-border bg-muted/30 p-1">
            <TabsTrigger value="events">Events</TabsTrigger>
            <TabsTrigger value="threads">Threads</TabsTrigger>
            <TabsTrigger value="replies">Reply drafts</TabsTrigger>
            <TabsTrigger value="next-actions">Next actions</TabsTrigger>
            <TabsTrigger value="reminders">Reminders</TabsTrigger>
            <TabsTrigger value="assets-library">Assets</TabsTrigger>
            <TabsTrigger value="asset-packets">Packets</TabsTrigger>
            <TabsTrigger value="dead">Dead mailboxes</TabsTrigger>
            <TabsTrigger value="queue">Re-search queue</TabsTrigger>
          </TabsList>
        ) : null}

        <TabsContent value="events" className="mt-4 space-y-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div className="text-sm text-muted-foreground">Email history is grouped by draft.</div>
            <NativeFilterSelect
              className="w-full md:w-[240px]"
              value={filter}
              onValueChange={setFilter}
              options={EVENT_FILTER_OPTS}
            />
          </div>

          <div className="space-y-4">
            {groupedEvents.map(({ draftId, draft, events: draftEvents }) => (
              <Card key={draftId} className="rounded-2xl border border-border bg-card shadow-none">
                <CardHeader className="pb-3">
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <CardTitle className="text-base">{draft?.company || `Draft #${draftId}`}</CardTitle>
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
                </CardHeader>
                <CardContent className="space-y-3">
                  {draftEvents.map((event, index) => (
                    <div key={event.id}>
                      <div className="flex items-center justify-between gap-3 rounded-2xl border border-border p-3">
                        <div className="flex items-center gap-3">
                          <div className={`rounded-xl border p-2 ${eventTone(event.event_type)}`}>
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
                </CardContent>
              </Card>
            ))}
            {!groupedEvents.length ? (
              <div className="text-sm text-muted-foreground">No events yet.</div>
            ) : null}
          </div>
        </TabsContent>

        <TabsContent value="threads" className="mt-4 space-y-4">
          <p className="text-sm text-muted-foreground">
            Threads appear after you send a draft. Open a thread to see outbound and inbound messages.
            Classification appears after a mock reply (inbox).
          </p>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <NativeFilterSelect
              className="w-full sm:w-[220px]"
              value={threadClassFilter}
              onValueChange={setThreadClassFilter}
              options={THREAD_CLASSIFICATION_FILTER_OPTS}
            />
          </div>
          <div className="grid gap-3">
            {filteredThreads.map((t) => {
              const contact = contactById.get(t.contact_id);
              const counts = messageCountsByThreadId.get(t.id) || { in: 0, out: 0 };
              const label = t.classification;
              return (
                <Card key={t.id} className="rounded-2xl border border-border bg-card shadow-none">
                  <CardContent className="flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <div className="font-medium">{contact?.company || `Contact #${t.contact_id}`}</div>
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
                  </CardContent>
                </Card>
              );
            })}
            {!threads.length ? (
              <div className="text-sm text-muted-foreground">No threads yet — send at least one draft.</div>
            ) : null}
            {threads.length > 0 && !filteredThreads.length ? (
              <div className="text-sm text-muted-foreground">No threads match the selected classification.</div>
            ) : null}
          </div>
        </TabsContent>

        <TabsContent value="replies" className="mt-4 space-y-4">
          <p className="text-sm text-muted-foreground">
            Reply drafts for inbound messages (after interested / need_more_info classification). Generate from the
            thread modal, then Approve / Edit and Send — nothing is sent automatically.
          </p>
          <div className="grid gap-3">
            {replyDrafts.map((rd) => {
              const c = contactById.get(rd.contact_id);
              const isEditing = replyEditing?.id === rd.id;
              const attachedPacket = assetPackets.find((p) => p.reply_draft_id === rd.id);
              const pv = replySendPreviewByDraftId[rd.id];
              return (
                <Card key={rd.id} className="rounded-2xl border border-teal-500/20 bg-card shadow-none">
                  <CardContent className="space-y-3 p-5">
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                      <div>
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
                        <div className="mt-2 flex flex-wrap items-center gap-2">
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            onClick={() => void fetchReplySendPreview(rd.id)}
                          >
                            Load send preview
                          </Button>
                          {pv?.loading ? (
                            <span className="text-xs text-muted-foreground">Loading preview…</span>
                          ) : null}
                        </div>
                        {pv?.error ? (
                          <div className="mt-1 text-xs text-destructive">{pv.error}</div>
                        ) : null}
                        {pv && !pv.loading && !pv.error && pv.final_body != null ? (
                          <div className="mt-2 space-y-2 rounded-xl border border-border bg-muted/20 p-3 text-xs">
                            {pv.will_lock_packet ? (
                              <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-1.5 text-amber-900 dark:text-amber-100">
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
                                        No <code className="text-[11px]">Materials:</code> block — packet assets are sent
                                        as file attachments only (not duplicated as links).
                                      </>
                                    ) : (
                                      <>
                                        Packet #{pv.attached_packet_id} is attached, but{" "}
                                        <code className="text-[11px]">packet_json.assets</code> is empty — add assets to
                                        the library and rebuild the packet.
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
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {rd.review_status === "pending" ? (
                          <>
                            <Button type="button" size="sm" onClick={() => void reviewReplyDraft(rd.id, "approved")}>
                              Approve
                            </Button>
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              onClick={() => void reviewReplyDraft(rd.id, "rejected")}
                            >
                              Reject
                            </Button>
                          </>
                        ) : null}
                        {["approved", "edited"].includes(rd.review_status) ? (
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            onClick={() => void reviewReplyDraft(rd.id, "rejected")}
                          >
                            Reject
                          </Button>
                        ) : null}
                        {rd.review_status === "rejected" ? (
                          <Button type="button" size="sm" onClick={() => void reviewReplyDraft(rd.id, "approved")}>
                            Approve
                          </Button>
                        ) : null}
                        {canSendReplyDraft(rd) ? (
                          <Button type="button" size="sm" onClick={() => void sendReplyDraft(rd.id)}>
                            Send
                          </Button>
                        ) : null}
                        {!isEditing ? (
                          <Button
                            type="button"
                            size="sm"
                            variant="secondary"
                            onClick={() =>
                              setReplyEditing({ id: rd.id, subject: rd.subject ?? "", body: rd.body ?? "" })
                            }
                          >
                            Edit
                          </Button>
                        ) : null}
                      </div>
                    </div>
                    {isEditing ? (
                      <div className="space-y-2 border-t border-border pt-3">
                        <Input
                          value={replyEditing.subject}
                          onChange={(e) =>
                            setReplyEditing((prev) => (prev ? { ...prev, subject: e.target.value } : prev))
                          }
                        />
                        <Textarea
                          className="min-h-[120px] rounded-xl"
                          value={replyEditing.body}
                          onChange={(e) =>
                            setReplyEditing((prev) => (prev ? { ...prev, body: e.target.value } : prev))
                          }
                        />
                        <div className="flex gap-2">
                          <Button type="button" size="sm" onClick={() => void saveReplyDraftEdit()}>
                            Save
                          </Button>
                          <Button type="button" size="sm" variant="outline" onClick={() => setReplyEditing(null)}>
                            Cancel
                          </Button>
                        </div>
                      </div>
                    ) : (
                      <>
                        <div className="text-sm font-medium">{rd.subject}</div>
                        <div className="rounded-xl bg-muted/40 p-3 text-sm whitespace-pre-wrap">{rd.body}</div>
                      </>
                    )}
                    {rd.error_message ? (
                      <div className="text-sm text-destructive">{rd.error_message}</div>
                    ) : null}
                  </CardContent>
                </Card>
              );
            })}
            {!replyDrafts.length ? (
              <div className="text-sm text-muted-foreground">
                No reply drafts yet — generate one from Threads → Open thread.
              </div>
            ) : null}
          </div>
        </TabsContent>

        <TabsContent value="next-actions" className="mt-4 space-y-4">
          <p className="text-sm text-muted-foreground">
            Follow-up work after reply classification. Create from the thread modal with Create next action — no
            auto-creation.
          </p>
          <div className="grid gap-3">
            {followUpTasks.map((ft) => {
              const c = contactById.get(ft.contact_id);
              const canAct = ft.status === "open" || ft.status === "in_progress";
              return (
                <Card key={ft.id} className="rounded-2xl border border-amber-500/20 bg-card shadow-none">
                  <CardContent className="space-y-3 p-5">
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                      <div>
                        <div className="font-medium">{ft.title}</div>
                        <div className="mt-1 text-sm text-muted-foreground">
                          {c?.company || `Contact #${ft.contact_id}`} · {c?.name || "—"}
                        </div>
                        <div className="mt-1 flex flex-wrap items-center gap-2">
                          <Badge variant="outline">{ft.task_type}</Badge>
                          <Badge variant="secondary">{ft.status}</Badge>
                          <Badge variant="secondary">{ft.priority}</Badge>
                          <span className="text-xs text-muted-foreground">Thread #{ft.thread_id}</span>
                          {activeReminderByFollowUpTaskId.has(ft.id) ? (
                            <Badge
                              variant="outline"
                              className="border-cyan-500/50 font-normal text-cyan-800 dark:text-cyan-200"
                            >
                              Reminder: {activeReminderByFollowUpTaskId.get(ft.id)?.status}
                            </Badge>
                          ) : null}
                        </div>
                        {ft.description ? (
                          <p className="mt-2 text-sm text-muted-foreground">{ft.description}</p>
                        ) : null}
                        {ft.due_at ? (
                          <div className="mt-1 text-xs text-muted-foreground">
                            Due: {new Date(ft.due_at).toLocaleString()}
                          </div>
                        ) : null}
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {canAct && ft.status === "open" ? (
                          <Button
                            type="button"
                            size="sm"
                            variant="secondary"
                            onClick={() => void patchFollowUpTaskStatus(ft.id, "in_progress")}
                          >
                            Start
                          </Button>
                        ) : null}
                        {canAct ? (
                          <Button
                            type="button"
                            size="sm"
                            onClick={() => void patchFollowUpTaskStatus(ft.id, "completed")}
                          >
                            Complete
                          </Button>
                        ) : null}
                        {canAct ? (
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            onClick={() => void patchFollowUpTaskStatus(ft.id, "cancelled")}
                          >
                            Cancel
                          </Button>
                        ) : null}
                        {!activeReminderByFollowUpTaskId.has(ft.id) ? (
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            className="border-cyan-500/40"
                            onClick={() => void createReminderForFollowUpTask(ft.id)}
                          >
                            Create reminder
                          </Button>
                        ) : null}
                      </div>
                    </div>
                  </CardContent>
                </Card>
              );
            })}
            {!followUpTasks.length ? (
              <div className="text-sm text-muted-foreground">
                No tasks yet — open a classified thread and click Create next action.
              </div>
            ) : null}
          </div>
        </TabsContent>

        <TabsContent value="reminders" className="mt-4 space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-muted-foreground">
              Internal reminders (not a calendar). Create manually from Next actions. For due items, click Trigger due
              to mark them triggered.
            </p>
            <Button type="button" size="sm" variant="secondary" onClick={() => void triggerDueReminders()}>
              Trigger due reminders
            </Button>
          </div>
          <div className="grid gap-3">
            {reminders.map((r) => {
              const c = r.contact_id != null ? contactById.get(r.contact_id) : null;
              const canAct = REMINDER_ACTIVE_STATUSES.includes(r.status);
              const remindDate = new Date(r.remind_at);
              const isOverdue =
                canAct && (r.status === "scheduled" || r.status === "snoozed") && remindDate < new Date();
              return (
                <Card key={r.id} className="rounded-2xl border border-cyan-500/20 bg-card shadow-none">
                  <CardContent className="space-y-3 p-5">
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                      <div>
                        <div className="font-medium">{r.title}</div>
                        <div className="mt-1 text-sm text-muted-foreground">
                          {c?.company || (r.contact_id != null ? `Contact #${r.contact_id}` : "—")} ·{" "}
                          {c?.name || "—"}
                          {r.follow_up_task_id ? (
                            <span className="text-xs"> · Follow-up #{r.follow_up_task_id}</span>
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
                  </CardContent>
                </Card>
              );
            })}
            {!reminders.length ? (
              <div className="text-sm text-muted-foreground">
                No reminders yet — create one from Next actions (Create reminder).
              </div>
            ) : null}
          </div>
        </TabsContent>

        <TabsContent value="assets-library" className="mt-4 space-y-4">
          <p className="text-sm text-muted-foreground">
            Global materials library. Thread packets pick active assets by type (need_more_info vs interested).
          </p>
          <Card className="rounded-2xl border border-indigo-500/20 bg-card shadow-none">
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Add asset</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
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
            </CardContent>
          </Card>
          <div className="grid gap-3">
            {assets.map((a) => (
              <Card key={a.id} className="rounded-2xl border border-border bg-card shadow-none">
                <CardContent className="p-5">
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
                </CardContent>
              </Card>
            ))}
            {!assets.length ? (
              <div className="text-sm text-muted-foreground">No assets — add one with the form above.</div>
            ) : null}
          </div>
        </TabsContent>

        <TabsContent value="asset-packets" className="mt-4 space-y-4">
          <p className="text-sm text-muted-foreground">
            Packets for this run. Built from the thread modal (Build … packet). Contents are a list of assets in{" "}
            <code className="text-xs">packet_json</code>.
          </p>
          <div className="grid gap-3">
            {assetPackets.map((p) => {
              const c = p.contact_id != null ? contactById.get(p.contact_id) : null;
              const inner = Array.isArray(p.packet_json?.assets) ? p.packet_json.assets : [];
              const packetThreadIdNum =
                p.thread_id != null && String(p.thread_id).trim() !== ""
                  ? Number(p.thread_id)
                  : null;
              const hasPacketThread =
                packetThreadIdNum != null && Number.isFinite(packetThreadIdNum);
              const threadReplyDrafts = hasPacketThread
                ? replyDrafts.filter(
                    (rd) =>
                      rd.thread_id != null && Number(rd.thread_id) === packetThreadIdNum,
                  )
                : [];
              const attachDraftOptions = [
                { value: "", label: "Select reply draft…" },
                ...threadReplyDrafts.map((rd) => ({
                  value: String(rd.id),
                  label: `Draft #${rd.id}: ${(rd.subject || "").slice(0, 48) || "—"}`,
                })),
              ];
              const showAttach =
                hasPacketThread &&
                p.status !== "archived" &&
                p.status !== "sent" &&
                threadReplyDrafts.length > 0;
              const canEditPacketAssets = p.status === "draft" || p.status === "approved";
              const packetSentLocked = p.status === "sent";
              const isEditingPacket = packetEditState?.packetId === p.id;
              const activeLibraryAssets = assets.filter((a) => a.status === "active");
              const addLibraryOptions = [
                { value: "", label: "Add from library…" },
                ...activeLibraryAssets.map((a) => ({
                  value: String(a.id),
                  label: `${a.asset_type}: ${(a.name || "").slice(0, 42) || `#${a.id}`}`,
                })),
              ];
              return (
                <Card key={p.id} className="rounded-2xl border border-indigo-500/20 bg-card shadow-none">
                  <CardContent className="space-y-3 p-5">
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
                          ) : null}
                          <span>
                            {c?.company || (p.contact_id != null ? `Contact #${p.contact_id}` : "—")} ·{" "}
                            {c?.name || "—"}
                          </span>
                        </div>
                        {p.reply_draft_id != null ? (
                          <div className="mt-2 text-sm font-medium text-foreground">
                            Attached to Reply Draft: {p.reply_draft_id}
                          </div>
                        ) : null}
                        {p.description ? (
                          <p className="mt-2 text-sm text-muted-foreground">{p.description}</p>
                        ) : null}
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {canEditPacketAssets && !isEditingPacket ? (
                          <Button
                            type="button"
                            size="sm"
                            variant="secondary"
                            onClick={() => beginPacketAssetEdit(p.id, inner)}
                          >
                            Edit packet
                          </Button>
                        ) : null}
                        {!isEditingPacket ? (
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            onClick={() => void savePacketAsNew(p.id)}
                          >
                            Save as new
                          </Button>
                        ) : null}
                        {p.status === "draft" ? (
                          <Button
                            type="button"
                            size="sm"
                            onClick={() => void patchAssetPacket(p.id, { status: "approved" })}
                          >
                            Approve packet
                          </Button>
                        ) : null}
                        {p.status !== "archived" ? (
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            onClick={() => void patchAssetPacket(p.id, { status: "archived" })}
                          >
                            Archive packet
                          </Button>
                        ) : null}
                      </div>
                    </div>
                    {hasPacketThread && p.status !== "archived" && !threadReplyDrafts.length ? (
                      <div className="text-xs text-muted-foreground">
                        {!replyDrafts.length ? (
                          <>
                            This run has no reply drafts yet. Open thread #{packetThreadIdNum}, generate a reply
                            draft, then return to Packets.
                          </>
                        ) : (
                          <>
                            This run has {replyDrafts.length} reply draft(s), but none are tied to thread #
                            {packetThreadIdNum}. You can attach only to a draft with the same thread_id (same Open
                            thread).
                          </>
                        )}
                      </div>
                    ) : null}
                    {showAttach ? (
                      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-end">
                        <NativeFilterSelect
                          className="w-full sm:max-w-xs"
                          value={packetAttachDraftId[p.id] ?? ""}
                          onValueChange={(v) =>
                            setPacketAttachDraftId((prev) => ({ ...prev, [p.id]: v }))
                          }
                          options={attachDraftOptions}
                        />
                        <Button
                          type="button"
                          size="sm"
                          variant="secondary"
                          onClick={() => void attachPacketToReplyDraft(p.id)}
                        >
                          Attach to reply draft
                        </Button>
                      </div>
                    ) : null}
                    {isEditingPacket ? (
                      <div className="rounded-xl border border-indigo-500/30 bg-muted/20 p-3">
                        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                          <div className="text-xs font-medium text-muted-foreground">Edit packet contents</div>
                          <div className="flex flex-wrap gap-2">
                            <Button type="button" size="sm" onClick={() => void savePacketAssets()}>
                              Save packet
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
                              className="flex flex-col gap-2 rounded-lg border border-border/60 bg-background/80 p-2 sm:flex-row sm:items-center sm:justify-between"
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
                                setError("That asset is already in the packet.");
                                return;
                              }
                              setError("");
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
                            Empty packet is allowed — Send will not add attachments or links from the packet.
                          </p>
                        ) : null}
                      </div>
                    ) : inner.length ? (
                      <div className="rounded-xl border border-border/80 bg-muted/30 p-3">
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
                        No assets in this packet yet (add from the library or Edit packet).
                      </div>
                    )}
                  </CardContent>
                </Card>
              );
            })}
            {!assetPackets.length ? (
              <div className="text-sm text-muted-foreground">
                No packets — for need_more_info / interested threads, click Build … packet in the modal.
              </div>
            ) : null}
          </div>
        </TabsContent>

        <TabsContent value="dead" className="mt-4 space-y-4">
          <div className="grid gap-3">
            {deadContacts.map((contact) => {
              const pending = pendingReplacementForContact(contact.id);
              const replacementRow = replacementContactForSource(contact.id);
              return (
                <Card
                  key={contact.id}
                  className="rounded-2xl border border-red-200/60 bg-card shadow-none dark:border-red-900/50"
                >
                  <CardContent className="flex flex-col gap-4 p-5 lg:flex-row lg:items-center lg:justify-between">
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
                  </CardContent>
                </Card>
              );
            })}
            {!deadContacts.length ? (
              <div className="text-sm text-muted-foreground">No dead mailboxes yet.</div>
            ) : null}
          </div>
        </TabsContent>

        <TabsContent value="queue" className="mt-4 space-y-4">
          <div className="grid gap-3">
            {replacementQueueTasks.map((task) => (
              <Card key={task.id} className="rounded-2xl border border-border bg-card shadow-none">
                <CardContent className="flex flex-col gap-4 p-5 lg:flex-row lg:items-center lg:justify-between">
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
                </CardContent>
              </Card>
            ))}
            {!replacementQueueTasks.length ? (
              <div className="text-sm text-muted-foreground">No re-search tasks in queue.</div>
            ) : null}
          </div>
        </TabsContent>
      </Tabs>
        </CardContent>
      </Card>

      {threadModalId != null ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <button
            type="button"
            className="fixed inset-0 bg-black/50"
            aria-label="Close"
            onClick={() => setThreadModalId(null)}
          />
          <div className="relative z-50 flex max-h-[85vh] w-full max-w-lg flex-col gap-4 rounded-2xl border bg-card p-5 shadow-lg">
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
                    {mt.classification === "need_more_info" ? "Generate info reply" : "Generate follow-up reply"}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="border-indigo-500/40"
                    onClick={() => void buildAssetPacketForThread(mt.id)}
                  >
                    {mt.classification === "need_more_info" ? "Build info packet" : "Build interested packet"}
                  </Button>
                </div>
              );
            })()}
            {(() => {
              const mt = threads.find((x) => x.id === threadModalId);
              if (!mt?.classification || !NEXT_ACTION_CLASSIFICATIONS.includes(mt.classification)) return null;
              return (
                <div className="space-y-2 border-b border-border pb-3">
                  <p className="text-xs text-muted-foreground">{NEXT_ACTION_HINTS[mt.classification]}</p>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => void createNextActionForThread(mt.id)}
                  >
                    Create next action
                  </Button>
                </div>
              );
            })()}
            <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto">
              {runMessages
                .filter((m) => m.thread_id === threadModalId)
                .map((m) => (
                  <div
                    key={m.id}
                    className={`max-w-[95%] rounded-2xl border p-3 text-sm ${
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
    </div>
  );
}
