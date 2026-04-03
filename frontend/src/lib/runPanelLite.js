/**
 * Denormalized “panel lite” rows for instant paint from localStorage (see humanUiSnapshot run_panel_lite).
 * Built from the same API arrays as TrackingView load() — no heavy fields (e.g. draft body).
 */

const REMINDER_ACTIVE_STATUSES = ["scheduled", "triggered", "snoozed"];

/** @param {object | null} t */
function threadOutboundDraftId(t) {
  if (t == null) return null;
  const id = t.effective_draft_id ?? t.draft_id;
  return id != null ? id : null;
}

function aggregateMessagesByThread(messages) {
  const byThread = new Map();
  for (const msg of messages || []) {
    const tid = msg.thread_id;
    if (tid == null) continue;
    if (!byThread.has(tid)) byThread.set(tid, []);
    byThread.get(tid).push(msg);
  }
  const counts = new Map();
  const needsInbound = new Map();
  for (const [tid, arr] of byThread) {
    arr.sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
    const last = arr[arr.length - 1];
    let inn = 0;
    let out = 0;
    for (const m of arr) {
      if (m.direction === "inbound") inn += 1;
      else out += 1;
    }
    counts.set(tid, { in: inn, out: out });
    needsInbound.set(tid, last?.direction === "inbound");
  }
  return { counts, needsInbound };
}

function reminderByThreadId(reminders) {
  const m = new Map();
  for (const r of reminders || []) {
    if (!r.thread_id || !REMINDER_ACTIVE_STATUSES.includes(r.status)) continue;
    const prev = m.get(r.thread_id);
    const t = new Date(r.remind_at).getTime();
    if (!prev || t < new Date(prev.remind_at).getTime()) {
      m.set(r.thread_id, r);
    }
  }
  return m;
}

/**
 * @param {object[]} threads
 * @param {object[]} contacts
 * @param {object[]} drafts
 * @param {object[]} messages
 * @param {object[]} reminders
 */
export function buildThreadPanelLiteRows(threads, contacts, drafts, messages, reminders) {
  if (!Array.isArray(threads) || threads.length === 0) return [];
  const contactById = new Map((contacts || []).map((c) => [c.id, c]));
  const draftById = new Map((drafts || []).map((d) => [d.id, d]));
  const { counts, needsInbound } = aggregateMessagesByThread(messages);
  const remindMap = reminderByThreadId(reminders);

  return threads.map((t) => {
    const contact = contactById.get(t.contact_id);
    const did = threadOutboundDraftId(t);
    const linkedDraft = did != null ? draftById.get(did) : undefined;
    const draftLifecycle = linkedDraft ? linkedDraft.tracking_status ?? linkedDraft.status : null;
    const isDead = draftLifecycle === "dead_mailbox" || contact?.email_health === "dead_mailbox";
    const isBounced =
      (linkedDraft ? linkedDraft.tracking_status : null) === "bounced" ||
      contact?.email_health === "bounced";
    const cts = counts.get(t.id) || { in: 0, out: 0 };
    const rem = remindMap.get(t.id);
    return {
      id: t.id,
      contact_id: t.contact_id,
      subject: t.subject ?? "",
      status: t.status ?? "",
      last_message_at: t.last_message_at ?? null,
      classification: t.classification ?? null,
      effective_draft_id: did,
      company: contact?.company ?? null,
      contact_name: contact?.name ?? null,
      msg_in: cts.in,
      msg_out: cts.out,
      needs_inbound: Boolean(needsInbound.get(t.id)),
      is_dead_mailbox: Boolean(isDead),
      is_bounced: Boolean(isBounced),
      has_reminder: Boolean(rem),
      remind_at: rem?.remind_at ?? null,
    };
  });
}

export function sortThreadPanelLiteRows(rows) {
  return [...rows].sort((a, b) => {
    const aTier = a.is_dead_mailbox ? 2 : a.is_bounced ? 1 : 0;
    const bTier = b.is_dead_mailbox ? 2 : b.is_bounced ? 1 : 0;
    if (aTier !== bTier) return aTier - bTier;
    const aAtt = a.needs_inbound ? 1 : 0;
    const bAtt = b.needs_inbound ? 1 : 0;
    if (aAtt !== bAtt) return bAtt - aAtt;
    const aRm = a.has_reminder ? 1 : 0;
    const bRm = b.has_reminder ? 1 : 0;
    if (aRm !== bRm) return bRm - aRm;
    const ta = a.last_message_at ? new Date(a.last_message_at).getTime() : 0;
    const tb = b.last_message_at ? new Date(b.last_message_at).getTime() : 0;
    if (tb !== ta) return tb - ta;
    return b.id - a.id;
  });
}

/** @param {ReturnType<typeof buildThreadPanelLiteRows>} rows @param {"active"|"bounced"|"dead_mailbox"} tab */
export function filterThreadPanelLiteByTab(rows, tab) {
  if (tab === "dead_mailbox") return rows.filter((r) => r.is_dead_mailbox);
  if (tab === "bounced") return rows.filter((r) => r.is_bounced && !r.is_dead_mailbox);
  return rows.filter((r) => !r.is_bounced && !r.is_dead_mailbox);
}

/**
 * @param {object[]} events
 * @param {object[]} drafts
 * @param {object[]} contacts
 */
export function buildEventsPanelLite(events, drafts, contacts) {
  const contactById = new Map((contacts || []).map((c) => [c.id, c]));
  const draftById = new Map((drafts || []).map((d) => [d.id, d]));
  const map = new Map();
  for (const ev of events || []) {
    const did = ev.draft_id;
    if (did == null) continue;
    if (!map.has(did)) map.set(did, []);
    map.get(did).push(ev);
  }
  const out = [];
  for (const [draftId, draftEvents] of map) {
    draftEvents.sort((a, b) => a.id - b.id);
    const draft = draftById.get(draftId);
    const last = draftEvents[draftEvents.length - 1];
    const chainEndsDead = last?.event_type === "dead_mailbox";
    const chainEndsBounced = last?.event_type === "bounced";
    const c = draft?.contact_id != null ? contactById.get(draft.contact_id) : undefined;
    const draftLifecycle = draft ? draft.tracking_status ?? draft.status : null;
    const isDead =
      draftLifecycle === "dead_mailbox" || c?.email_health === "dead_mailbox" || chainEndsDead;
    const isBounced =
      (draft ? draft.tracking_status : null) === "bounced" ||
      c?.email_health === "bounced" ||
      chainEndsBounced;
    let bucket = "active";
    if (isDead) bucket = "dead_mailbox";
    else if (isBounced) bucket = "bounced";
    out.push({
      draftId,
      company: draft?.company || null,
      to_email: draft?.to_email || null,
      subject: draft?.subject || null,
      eventCount: draftEvents.length,
      chainEndsDeadMailbox: Boolean(chainEndsDead),
      chainEndsBounced: Boolean(chainEndsBounced),
      bucket,
      isReplacement: Boolean(
        draft?.contact_id != null &&
          contactById.get(draft.contact_id)?.source_json?.source === "replacement_search",
      ),
    });
  }
  out.sort((a, b) => a.draftId - b.draftId);
  return out;
}

/** @param {object[]} groups @param {"active"|"bounced"|"dead_mailbox"} tab */
export function filterEventsPanelLiteByTab(groups, tab) {
  return (groups || []).filter((g) => g.bucket === tab);
}

/** @param {object} c */
export function stripContactForPanelLite(c) {
  if (!c || typeof c !== "object") return null;
  return {
    id: c.id,
    company: c.company ?? null,
    name: c.name ?? null,
    email: c.email ?? null,
    review_status: c.review_status ?? null,
    email_health: c.email_health ?? null,
    website: c.website ?? null,
    source_json:
      c.source_json && typeof c.source_json === "object"
        ? { source: c.source_json.source, replaces_contact_id: c.source_json.replaces_contact_id }
        : null,
    personalization_json:
      c.personalization_json && typeof c.personalization_json === "object"
        ? {
            why_this_company: c.personalization_json.why_this_company,
            offer_fit: c.personalization_json.offer_fit,
            role_angle: c.personalization_json.role_angle,
          }
        : null,
  };
}

/** @param {object} d */
export function stripDraftForPanelLite(d) {
  if (!d || typeof d !== "object") return null;
  return {
    id: d.id,
    contact_id: d.contact_id ?? null,
    company: d.company ?? null,
    to_email: d.to_email ?? null,
    subject: d.subject ?? null,
    status: d.status ?? null,
    review_status: d.review_status ?? null,
    tracking_status: d.tracking_status ?? null,
    review_notes: d.review_notes ?? null,
    error_message: d.error_message ?? null,
    attached_asset_ids: d.attached_asset_ids ?? null,
    generation_meta_json:
      d.generation_meta_json && typeof d.generation_meta_json === "object"
        ? {
            validation_score: d.generation_meta_json.validation_score,
            style_mode: d.generation_meta_json.style_mode,
            pipeline_source: d.generation_meta_json.pipeline_source,
            is_valid: d.generation_meta_json.is_valid,
          }
        : null,
  };
}

export const MAX_CONTACTS_PANEL_LITE = 2500;
