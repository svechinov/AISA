import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
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
import { ThemeToggle } from "@/components/ThemeToggle";
import {
  ChevronRight,
  FileText,
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

const API_LABEL = API_BASE === "/api" ? `Vite proxy → ${DEV_PROXY_TARGET}` : API_BASE;

const DEFAULT_OUTREACH_BRIEF =
  "Offer:\nTarget:\nRoles:\nGoal:\nTone: Professional\nNotes:\n";

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

function StatusBadge({ value }) {
  return <Badge variant={statusTone[value] || "secondary"}>{pretty(value)}</Badge>;
}

function SendLifecycleBadge({ status }) {
  const st = status || "draft";
  const cls = sendLifecycleBadgeClass[st];
  return (
    <Badge className={cls} variant="secondary">
      {pretty(st)}
    </Badge>
  );
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
  { value: "contacts", label: "Contacts" },
  { value: "drafts", label: "Drafts" },
  { value: "events", label: "Events" },
  { value: "threads", label: "Threads" },
  { value: "reply-drafts", label: "Reply Drafts" },
  { value: "follow-ups", label: "Follow-ups" },
  { value: "reminders", label: "Reminders" },
  { value: "assets", label: "Assets" },
  { value: "packets", label: "Packets" },
  { value: "dead", label: "Dead mailboxes" },
  { value: "queue", label: "Re-search queue" },
];

function mainNavToTrackingTab(nav) {
  const map = {
    events: "events",
    threads: "threads",
    "reply-drafts": "replies",
    "follow-ups": "next-actions",
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
  const [editDraft, setEditDraft] = useState(null);
  const [draftForm, setDraftForm] = useState({ subject: "", body: "" });

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
      setError(String(e.message || e));
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [projectView]);

  const loadRunDetails = async (runId) => {
    if (!runId) return;
    try {
      const [run, stepsData, contactsData, draftsData, ws] = await Promise.all([
        api(`/runs/${runId}`),
        api(`/steps/run/${runId}`),
        api(`/contacts/run/${runId}`),
        api(`/email-drafts/run/${runId}`),
        api(`/runs/${runId}/workspace`),
      ]);
      setSelectedRun(run);
      setSteps(stepsData);
      setContacts(contactsData);
      setDrafts(draftsData);
      setWorkspace(ws);
    } catch (e) {
      setError(String(e.message || e));
    }
  };

  useEffect(() => {
    const ac = new AbortController();
    void loadProjects(undefined, { signal: ac.signal });
    return () => ac.abort();
  }, [projectView, loadProjects]);

  useEffect(() => {
    if (!selectedProject) return;
    const pid = projectPk(selectedProject);
    (async () => {
      try {
        const runs = await api(`/runs/project/${pid}`);
        setRunsList(runs);
        if (runs.length > 0) {
          await loadRunDetails(runs[0].id);
        } else {
          setSelectedRun(null);
          setSteps([]);
          setContacts([]);
          setDrafts([]);
          setWorkspace(null);
        }
      } catch (e) {
        setRunsList([]);
        setError(String(e?.message || e));
      }
    })();
  }, [selectedProject]);

  useEffect(() => {
    if (!selectedRun?.id) return;
    if (selectedRun.status !== "running") return;
    const id = selectedRun.id;
    const interval = setInterval(() => {
      loadRunDetails(id);
    }, 3000);
    return () => clearInterval(interval);
  }, [selectedRun?.id, selectedRun?.status]);

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
      setError(String(e.message || e));
    }
  };

  const restoreProject = async (projectId) => {
    try {
      setError("");
      await api(`/projects/${projectId}/restore`, { method: "POST" });
      await loadProjects();
    } catch (e) {
      setError(String(e.message || e));
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
      setRunsList(runs);
      await loadRunDetails(run.id);
      setMainNav("contacts");
      setNewRunForm({
        name: "",
        notes: "",
        segment: "",
        outreach_brief: DEFAULT_OUTREACH_BRIEF,
      });
    } catch (e) {
      setError(String(e.message || e));
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
      await api(`/runs/${selectedRun.id}/close`, { method: "PATCH" });
      setCloseRunOpen(false);
      const pid = projectPk(selectedProject);
      const runs = await api(`/runs/project/${pid}`);
      setRunsList(runs);
      if (runs.length > 0) {
        await loadRunDetails(runs[0].id);
      } else {
        setSelectedRun(null);
        setSteps([]);
        setContacts([]);
        setDrafts([]);
        setWorkspace(null);
      }
    } catch (e) {
      setError(String(e.message || e));
    }
  };

  const openRunById = async (runId) => {
    setSwitchRunOpen(false);
    await loadRunDetails(runId);
    if (selectedProject) {
      try {
        const pid = projectPk(selectedProject);
        setRunsList(await api(`/runs/project/${pid}`));
      } catch {
        /* ignore */
      }
    }
    setMainNav("contacts");
  };

  const continueRun = async () => {
    if (!selectedRun) return;
    try {
      setError("");
      const run = await api(`/runs/${selectedRun.id}/continue`, { method: "POST" });
      await loadRunDetails(run.id);
    } catch (e) {
      setError(String(e.message || e));
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
      setError(String(e.message || e));
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
      setError(String(e.message || e));
    }
  };

  const reviewDraft = async (id, review_status) => {
    try {
      setError("");
      await api(`/email-drafts/${id}/review`, {
        method: "PATCH",
        body: { review_status },
      });
      await loadRunDetails(selectedRun.id);
    } catch (e) {
      setError(String(e.message || e));
    }
  };

  const sendDraft = async (draftId) => {
    if (!selectedRun) return;
    try {
      setError("");
      await api(`/sending/drafts/${draftId}/send`, { method: "POST" });
      await loadRunDetails(selectedRun.id);
    } catch (e) {
      setError(String(e.message || e));
    }
  };

  const sendAllApproved = async () => {
    if (!selectedRun) return;
    try {
      setError("");
      await api(`/sending/runs/${selectedRun.id}/send`, { method: "POST" });
      await loadRunDetails(selectedRun.id);
    } catch (e) {
      setError(String(e.message || e));
    }
  };

  const openEditDraft = (d) => {
    setEditDraft(d);
    setDraftForm({ subject: d.subject ?? "", body: d.body ?? "" });
  };

  const saveEditDraft = async () => {
    if (!editDraft || !selectedRun) return;
    try {
      setError("");
      await api(`/email-drafts/${editDraft.id}/edit`, {
        method: "PATCH",
        body: { subject: draftForm.subject, body: draftForm.body },
      });
      setEditDraft(null);
      await loadRunDetails(selectedRun.id);
    } catch (e) {
      setError(String(e.message || e));
    }
  };

  const contactsMatchingSearch = useMemo(() => {
    return contacts.filter((c) => {
      const q = search.trim().toLowerCase();
      return (
        !q || [c.company, c.name, c.role, c.email].some((v) => (v || "").toLowerCase().includes(q))
      );
    });
  }, [contacts, search]);

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

  const contactById = useMemo(() => new Map(contacts.map((c) => [c.id, c])), [contacts]);

  const approvedContacts = contacts.filter((c) => ["approved", "edited"].includes(c.review_status)).length;
  const approvedDrafts = drafts.filter((d) => ["approved", "edited"].includes(d.review_status)).length;
  const sendableDraftsCount = useMemo(() => {
    return drafts.filter(
      (d) =>
        ["approved", "edited"].includes(d.review_status) &&
        !!(d.to_email || "").trim() &&
        ["draft", "failed"].includes(d.status),
    ).length;
  }, [drafts]);
  const pendingContacts = contacts.filter((c) => c.review_status === "pending").length;

  const pending = contactsMatchingSearch.filter((c) => c.review_status === "pending");
  const approvedList = contactsMatchingSearch.filter((c) =>
    ["approved", "edited"].includes(c.review_status),
  );
  const rejectedList = contactsMatchingSearch.filter((c) => c.review_status === "rejected");

  const draftsPending = filteredDrafts.filter((d) => d.review_status === "pending");
  const draftsApprovedList = filteredDrafts.filter((d) =>
    ["approved", "edited"].includes(d.review_status),
  );
  const draftsRejectedList = filteredDrafts.filter((d) => d.review_status === "rejected");

  const canContinue = approvedContacts > 0;

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

  const primaryCta = useMemo(() => {
    if (!selectedRun?.id) return null;
    const phase = workspace?.display_phase;
    if (phase === "Closed") return null;
    if (phase === "Preparing") {
      if (selectedRun.status === "needs_review") {
        return {
          label: "Approve contacts to continue",
          disabled: approvedContacts === 0,
          hint:
            approvedContacts === 0
              ? "Approve or edit at least one contact first (Approve / Edit saves as edited)."
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
    approvedContacts,
    outreachBatchProgress,
    openNewRunDialog,
  ]);

  const contactCardClass = (c) => {
    const rs = c.review_status;
    if (["approved", "edited"].includes(rs)) {
      return "rounded-2xl border border-green-600/40 bg-green-500/5 shadow-none";
    }
    if (rs === "pending") {
      return "rounded-2xl border border-muted bg-muted/25 shadow-none";
    }
    return "rounded-2xl border border-border shadow-none";
  };

  const draftCardClass = (d) => {
    const st = d.tracking_status ?? d.status;
    if (st === "sent") {
      return "rounded-2xl border border-green-600/40 bg-green-500/5 shadow-none";
    }
    if (st === "failed") {
      return "rounded-2xl border border-destructive/45 bg-destructive/5 shadow-none";
    }
    if (st === "sending") {
      return "rounded-2xl border border-blue-500/40 bg-blue-500/5 shadow-none";
    }
    if (st === "replied") {
      return "rounded-2xl border border-emerald-600/40 bg-emerald-500/5 shadow-none";
    }
    if (st === "bounced") {
      return "rounded-2xl border border-orange-500/40 bg-orange-500/5 shadow-none";
    }
    if (st === "dead_mailbox") {
      return "rounded-2xl border border-red-700/40 bg-red-600/5 shadow-none";
    }
    const rs = d.review_status;
    if (["approved", "edited"].includes(rs)) {
      return "rounded-2xl border border-green-600/40 bg-green-500/5 shadow-none";
    }
    if (rs === "pending") {
      return "rounded-2xl border border-muted bg-muted/25 shadow-none";
    }
    return "rounded-2xl border border-border shadow-none";
  };

  const canSendDraft = (d) =>
    ["approved", "edited"].includes(d.review_status) &&
    !!(d.to_email || "").trim() &&
    !["sent", "sending"].includes(d.status);

  const renderContactCard = (contact) => {
    const rs = contact.review_status;
    const isPending = rs === "pending";
    const isRejected = rs === "rejected";
    const isReplacement = contact.source_json?.source === "replacement_search";
    return (
      <Card key={contact.id} className={contactCardClass(contact)}>
        <CardContent className="p-5">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <div className="text-lg font-semibold">{contact.company || "Unnamed company"}</div>
                {isReplacement ? (
                  <Badge variant="default" className="bg-violet-600 hover:bg-violet-600">
                    Replacement
                  </Badge>
                ) : null}
                <StatusBadge value={contact.status} />
                <StatusBadge value={contact.review_status} />
                {!contact.email ? <Badge variant="destructive">No email</Badge> : null}
                {(contact.confidence || "").toLowerCase() === "low" ? (
                  <Badge variant="secondary">Low confidence</Badge>
                ) : null}
                {contact.email_health && contact.email_health !== "unknown" ? (
                  <Badge variant="outline" className="text-xs">
                    Email: {pretty(contact.email_health)}
                  </Badge>
                ) : null}
              </div>
              <div className="text-sm text-muted-foreground">
                {contact.name || "No name"} · {contact.role || "No role"}
              </div>
              <div className="text-sm">{contact.email || "No email"}</div>
              <div className="text-xs text-muted-foreground">{contact.website || "No website"}</div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() =>
                  setEditingContact({
                    id: contact.id,
                    name: contact.name ?? "",
                    email: contact.email ?? "",
                  })
                }
              >
                <Pencil className="mr-1 h-3 w-3" /> Edit
              </Button>
              {isPending ? (
                <>
                  <Button size="sm" onClick={() => approveContact(contact.id)}>
                    Approve
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => reviewContact(contact.id, "rejected")}>
                    Reject
                  </Button>
                </>
              ) : null}
              {!isPending && !isRejected ? (
                <Button size="sm" variant="outline" onClick={() => reviewContact(contact.id, "rejected")}>
                  Reject
                </Button>
              ) : null}
              {isRejected ? (
                <Button size="sm" onClick={() => approveContact(contact.id)}>
                  Approve
                </Button>
              ) : null}
            </div>
          </div>
          {editingContact?.id === contact.id ? (
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
                      const emailVal = (editingContact.email ?? "").trim();
                      const body = { name: nameVal || null };
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
                      setError(String(e.message || e));
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
        </CardContent>
      </Card>
    );
  };

  const renderDraftCard = (draft) => {
    const draftContact = contactById.get(draft.contact_id);
    const isReplacementDraft = draftContact?.source_json?.source === "replacement_search";
    return (
    <Card key={draft.id} className={draftCardClass(draft)}>
      <CardContent className="p-5">
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <div className="text-lg font-semibold">{draft.company || "Untitled draft"}</div>
                {isReplacementDraft ? (
                  <Badge variant="default" className="bg-violet-600 hover:bg-violet-600">
                    Replacement draft
                  </Badge>
                ) : null}
                <SendLifecycleBadge status={draft.tracking_status ?? draft.status} />
                <StatusBadge value={draft.review_status} />
              </div>
              <div className="mt-2 text-sm">
                <span className="font-medium">To:</span> {draft.to_email || "No recipient"}
              </div>
              <div className="text-sm">
                <span className="font-medium">Subject:</span> {draft.subject}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="outline" onClick={() => openEditDraft(draft)}>
                <Pencil className="mr-1 h-3 w-3" /> Edit
              </Button>
              {draft.review_status === "pending" ? (
                <>
                  <Button size="sm" onClick={() => reviewDraft(draft.id, "approved")}>
                    Approve
                  </Button>
                  <Button size="sm" variant="secondary" onClick={() => reviewDraft(draft.id, "approved")}>
                    Approve & Send later
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => reviewDraft(draft.id, "rejected")}>
                    Reject
                  </Button>
                </>
              ) : null}
              {["approved", "edited"].includes(draft.review_status) ? (
                <Button size="sm" variant="outline" onClick={() => reviewDraft(draft.id, "rejected")}>
                  Reject
                </Button>
              ) : null}
              {draft.review_status === "rejected" ? (
                <Button size="sm" onClick={() => reviewDraft(draft.id, "approved")}>
                  Approve
                </Button>
              ) : null}
              {canSendDraft(draft) ? (
                <Button size="sm" onClick={() => sendDraft(draft.id)}>
                  Send
                </Button>
              ) : null}
            </div>
          </div>
          {draft.error_message ? (
            <div className="rounded-xl border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
              {draft.error_message}
            </div>
          ) : null}
          <EmailDraftBodyPreview body={draft.body} />
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
              <h1 className="text-2xl font-bold tracking-tight md:text-3xl">Business workflow dashboard</h1>
              <p className="mt-1 text-sm text-muted-foreground">
                API: <span className="font-mono text-xs">{API_LABEL}</span>
              </p>
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
              <Button onClick={() => void loadProjects()} variant="outline">
                <RefreshCw className="mr-2 h-4 w-4" /> Refresh
              </Button>
              <ThemeToggle />
            </div>
          </div>

          <div className="flex flex-col gap-3 rounded-2xl border border-border bg-card p-4 md:flex-row md:items-center md:justify-between">
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
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="secondary"
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
          <Card className="mb-6 border-destructive/50">
            <CardContent className="p-4 text-sm text-destructive">{error}</CardContent>
          </Card>
        ) : null}

        <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
          <Card className="rounded-2xl shadow-sm">
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
                      className={`rounded-2xl border p-4 transition ${
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
                            className="shrink-0 text-muted-foreground"
                            aria-label="Archive project"
                            onClick={(e) => {
                              e.stopPropagation();
                              void archiveProject(project.id);
                            }}
                          >
                            Archive
                          </Button>
                        ) : (
                          <Button
                            size="sm"
                            variant="ghost"
                            className="shrink-0 text-muted-foreground"
                            onClick={(e) => {
                              e.stopPropagation();
                              void restoreProject(project.id);
                            }}
                          >
                            Restore
                          </Button>
                        )}
                      </div>
                    </div>
                  ))}
                  {!projects.length && (
                    <div className="rounded-2xl border border-dashed p-6 text-sm text-muted-foreground">
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
                <Card className="min-w-0 rounded-2xl shadow-sm">
                  <CardHeader className="min-w-0 space-y-0">
                    <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                      <div className="min-w-0">
                        <CardTitle>Run setup</CardTitle>
                        <CardDescription>Prepare this run before starting outreach</CardDescription>
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
                            : st.ui_status === "In progress"
                              ? "bg-secondary text-secondary-foreground"
                              : "bg-muted text-muted-foreground";
                        return (
                          <div
                            key={st.step_name}
                            className="overflow-hidden rounded-2xl border border-border bg-card shadow-sm"
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
                    <div className="rounded-2xl border border-border bg-muted/30 p-3 text-sm">
                      <div className="font-medium">Setup summary</div>
                      <ul className="mt-2 space-y-1 text-muted-foreground">
                        {workspace.setup_summary?.companies_collected != null ? (
                          <li>
                            Companies collected:{" "}
                            <span className="font-medium text-foreground">
                              {workspace.setup_summary.companies_collected}
                            </span>
                          </li>
                        ) : null}
                        <li>
                          Contacts found:{" "}
                          <span className="font-medium text-foreground">
                            {workspace.setup_summary?.contacts_found ?? "—"}
                          </span>
                        </li>
                        <li>
                          Contacts validated:{" "}
                          <span className="font-medium text-foreground">
                            {workspace.setup_summary?.contacts_validated ?? "—"}
                          </span>
                        </li>
                        <li>
                          Contacts approved:{" "}
                          <span className="font-medium text-foreground">
                            {workspace.setup_summary?.contacts_approved ?? "—"}
                          </span>
                        </li>
                      </ul>
                      <p className="mt-3 text-foreground">{workspace.setup_state_message}</p>
                    </div>
                  </CardContent>
                </Card>

                <Card className="min-w-0 w-full rounded-2xl shadow-sm">
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
                        Follow-ups open:{" "}
                        <span className="font-medium">{workspace.performance?.follow_ups_open ?? 0}</span>
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
                          <li>Follow-ups open: {workspace.conversations.follow_ups_open}</li>
                          <li>Reminders due: {workspace.conversations.reminders_due}</li>
                        </ul>
                      </div>
                    ) : null}
                  </CardContent>
                </Card>
              </div>
            ) : null}

            <div className="flex flex-wrap gap-1 rounded-2xl border border-border bg-muted/20 p-1">
              {MAIN_NAV.map((item) => (
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
              <Card className="rounded-2xl shadow-sm">
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
                      <Card key={r.id} className="rounded-2xl border border-border shadow-none">
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

            {mainNav === "contacts" || mainNav === "drafts" ? (
            <Card className="rounded-2xl shadow-sm">
              <CardHeader>
                <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                  <div>
                    <CardTitle>Review workspace</CardTitle>
                    <CardDescription>Review contacts first, then drafts.</CardDescription>
                  </div>
                  <Input
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Search company, name, email, subject..."
                    className="md:max-w-sm"
                  />
                </div>
              </CardHeader>
              <CardContent>
                <Tabs
                  value={mainNav === "drafts" ? "drafts" : "contacts"}
                  onValueChange={(v) => setMainNav(v)}
                  className="w-full"
                >
                  <TabsList className="grid w-full max-w-md grid-cols-2 rounded-2xl">
                    <TabsTrigger value="contacts">Contacts</TabsTrigger>
                    <TabsTrigger value="drafts">Drafts</TabsTrigger>
                  </TabsList>

                  <TabsContent value="contacts" className="mt-4 space-y-6">
                    <div className="text-sm text-muted-foreground">
                      {pendingContacts} contacts left to review
                    </div>

                    {pendingContacts > 0 ? (
                      <div className="space-y-3">
                        <div className="text-sm font-medium">
                          Pending ({pending.length})
                        </div>
                        <div className="grid gap-3">{pending.map((c) => renderContactCard(c))}</div>
                        {pending.length === 0 ? (
                          <div className="text-sm text-muted-foreground">
                            No pending contacts match your search — clear search or check Approved / Rejected.
                          </div>
                        ) : null}
                      </div>
                    ) : null}

                    {pendingContacts === 0 && contacts.length > 0 ? (
                      <div className="rounded-2xl border border-dashed border-muted-foreground/25 py-10 text-center">
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
                                Approve or edit at least one contact first (Approve / Edit saves as edited).
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
                      <div className="text-sm font-medium">
                        Approved ({approvedList.length})
                      </div>
                      <div className="grid gap-3">{approvedList.map((c) => renderContactCard(c))}</div>
                    </div>

                    {rejectedList.length > 0 ? (
                      <details className="group rounded-2xl border border-border">
                        <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 text-sm font-medium [&::-webkit-details-marker]:hidden">
                          <ChevronRight className="h-4 w-4 shrink-0 transition group-open:rotate-90" />
                          Rejected ({rejectedList.length})
                        </summary>
                        <div className="grid gap-3 border-t border-border px-4 pb-4 pt-3">
                          {rejectedList.map((c) => renderContactCard(c))}
                        </div>
                      </details>
                    ) : null}

                    {contacts.length === 0 ? (
                      <div className="text-center text-sm text-muted-foreground">
                        No contacts for this run yet.
                      </div>
                    ) : null}
                  </TabsContent>

                  <TabsContent value="drafts" className="mt-4 space-y-6">
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                      <Button
                        type="button"
                        onClick={() => void sendAllApproved()}
                        disabled={!selectedRun || sendableDraftsCount === 0}
                      >
                        Send all approved
                      </Button>
                      <NativeFilterSelect
                        className="w-full sm:w-[220px]"
                        value={draftFilter}
                        onValueChange={setDraftFilter}
                        options={DRAFT_FILTER_OPTS}
                      />
                    </div>

                    {drafts.length > 0 ? (
                      <>
                        <div className="space-y-3">
                          <div className="text-sm font-medium">Pending ({draftsPending.length})</div>
                          <div className="grid gap-3">{draftsPending.map((d) => renderDraftCard(d))}</div>
                        </div>

                        <div className="space-y-3">
                          <div className="text-sm font-medium">Approved ({draftsApprovedList.length})</div>
                          <div className="grid gap-3">{draftsApprovedList.map((d) => renderDraftCard(d))}</div>
                        </div>

                        {draftsRejectedList.length > 0 ? (
                          <details className="group rounded-2xl border border-border">
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
                  </TabsContent>

                </Tabs>
              </CardContent>
            </Card>
            ) : null}

            {!["runs", "contacts", "drafts"].includes(mainNav) && selectedRun?.id ? (
              <TrackingView
                runId={selectedRun.id}
                activeTab={mainNavToTrackingTab(mainNav)}
                singleTabMode
              />
            ) : null}

            {!["runs", "contacts", "drafts"].includes(mainNav) && !selectedRun?.id ? (
              <div className="rounded-2xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
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
              {runsList.map((r) => (
                <button
                  key={r.id}
                  type="button"
                  className="w-full rounded-2xl border border-border p-3 text-left text-sm hover:bg-muted/50"
                  onClick={() => void openRunById(r.id)}
                >
                  <div className="font-medium">{r.name}</div>
                  <div className="text-xs text-muted-foreground">
                    {r.display_phase} · Companies {r.companies_count} · Contacts {r.contacts_count} · Sent{" "}
                    {r.emails_sent}
                  </div>
                </button>
              ))}
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
            This run will no longer be used for new outreach sending. Existing threads, replies, follow-ups,
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
          <div className="relative z-50 w-full max-w-2xl rounded-xl border bg-card p-6 shadow-lg">
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
    </div>
  );
}
