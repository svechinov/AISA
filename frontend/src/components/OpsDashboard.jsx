import { useCallback, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { API_BASE } from "@/lib/apiBase";
import SendQueuePanel from "@/components/SendQueuePanel";
import SendingPolicyPanel from "@/components/SendingPolicyPanel";
import SuppressionPanel from "@/components/SuppressionPanel";

import { fmtInTz, DEFAULT_TZ } from "@/lib/timeTz";

const REFRESH_MS = 30000;

function StatTile({ label, value, foot, children }) {
  return (
    <Card className="border">
      <CardContent className="p-4">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{label}</div>
        <div className="mt-1.5 text-[22px] font-semibold leading-tight tabular-nums">{value}</div>
        {children}
        {foot ? <div className="mt-1.5 text-xs text-muted-foreground">{foot}</div> : null}
      </CardContent>
    </Card>
  );
}

function DecisionRow({ chip, chipVariant = "neutral", title, sub, actionLabel, onAction, actionVariant = "outline" }) {
  return (
    <div className="flex items-center gap-3 border-b border-border/60 px-4 py-2.5 text-sm last:border-0">
      <Badge variant={chipVariant} className="shrink-0">{chip}</Badge>
      <div className="min-w-0 flex-1">
        <div className="truncate font-medium">{title}</div>
        {sub ? <div className="mt-0.5 truncate text-xs text-muted-foreground">{sub}</div> : null}
      </div>
      {onAction ? (
        <Button size="sm" variant={actionVariant} className="shrink-0" onClick={onAction}>
          {actionLabel}
        </Button>
      ) : null}
    </div>
  );
}

/**
 * «Сегодня» — операторский экран: что уйдёт само и когда, что требует решения,
 * живы ли системы. GET /ops/summary, автообновление каждые 30 с (B-028 этап 3).
 *
 * runId/runName (B-547): какой ран сейчас выбран в UI — политика в блоке «Система» показывается
 * ЕГО реальным ящиком (resolve_policy_for_run), а не всегда дефолтной. runId необязателен —
 * без него summary работает как раньше (дефолтная политика).
 */
export default function OpsDashboard({ onNavigate, totals, onOpenDraft, runId, runName }) {
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const url = runId
        ? `${API_BASE}/ops/summary?run_id=${runId}`
        : `${API_BASE}/ops/summary`;
      const r = await fetch(url);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setSummary(await r.json());
      setError(null);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const togglePause = useCallback(async () => {
    if (!summary) return;
    setBusy(true);
    try {
      const path = summary.worker.paused ? "/sending/queue/resume" : "/sending/queue/pause";
      await fetch(`${API_BASE}${path}`, { method: "POST" });
      await load();
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }, [summary, load]);

  const releaseHeld = useCallback(
    async (itemId) => {
      try {
        await fetch(`${API_BASE}/sending/queue/${itemId}/release`, { method: "POST" });
        await load();
      } catch (e) {
        setError(String(e.message || e));
      }
    },
    [load],
  );

  if (!summary && loading) {
    return (
      <Card className="border">
        <CardContent className="py-6 text-sm text-muted-foreground">Загрузка…</CardContent>
      </Card>
    );
  }

  if (!summary) {
    return (
      <Card className="border">
        <CardContent className="py-6 text-sm text-danger">
          Не удалось загрузить дашборд{error ? `: ${error}` : ""}.
          <Button size="sm" variant="outline" className="ml-2" onClick={load}>
            Повторить
          </Button>
        </CardContent>
      </Card>
    );
  }

  const { worker, today, queue, requires_decision: decisions, suppression_count, gmail_sync } = summary;
  const tz = today?.timezone || DEFAULT_TZ;
  const capPct = today.policy_configured && today.daily_cap
    ? Math.min(100, Math.round((today.sent_today / today.daily_cap) * 100))
    : 0;
  const openFollowUpsTotal = Object.values(decisions.open_follow_ups_by_type || {}).reduce(
    (a, b) => a + b,
    0,
  );
  const queuedCount = queue.counts_by_state?.queued ?? 0;
  const heldCount = queue.counts_by_state?.held ?? (queue.held?.length || 0);
  const needsDecision = (decisions.pending_drafts || 0) + openFollowUpsTotal + (queue.held?.length || 0);
  const nextSlot = today.next_slots?.[0];

  return (
    <div className="space-y-4">
      {error ? (
        <p className="text-sm text-danger">Ошибка обновления: {error} (показаны последние данные)</p>
      ) : null}

      {/* тайлы: сводка одним взглядом */}
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <StatTile
          label="Отправлено сегодня"
          value={
            today.policy_configured ? (
              <>
                {today.sent_today} <span className="text-sm font-medium text-muted-foreground">из {today.daily_cap}</span>
              </>
            ) : (
              "—"
            )
          }
          foot={
            today.policy_configured
              ? `окно ${today.window_start}–${today.window_end} · ${tz.replace("Asia/", "")}`
              : "политика отправки не настроена"
          }
        >
          {today.policy_configured ? (
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
              <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${Math.max(capPct, 2)}%` }} />
            </div>
          ) : null}
        </StatTile>
        <StatTile
          label="В очереди"
          value={queuedCount}
          foot={
            heldCount > 0
              ? `${heldCount} на удержании · ближайший слот ${nextSlot ? fmtInTz(nextSlot, tz) : "—"}`
              : nextSlot
                ? `ближайший слот — ${fmtInTz(nextSlot, tz)}`
                : "слотов нет"
          }
        />
        <StatTile
          label="Требуют решения"
          value={needsDecision}
          foot={`${decisions.pending_drafts || 0} черновиков · ${openFollowUpsTotal} фоллоу-апов · ${queue.held?.length || 0} удержано`}
        />
        <StatTile
          label="Отправлено всего"
          value={totals?.emails_sent ?? "—"}
          foot={`за 24 ч: ${totals?.emails_sent_24h ?? 0} · ответов: ${totals?.replies ?? 0}`}
        />
      </div>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-[3fr_2fr]">
        {/* что требует решения оператора */}
        <Card className="border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 border-b border-border/60 px-4 py-3">
            <CardTitle className="text-sm font-semibold">Требует вашего решения</CardTitle>
            <button
              type="button"
              className="text-xs font-medium text-info hover:underline"
              onClick={() => onNavigate?.("drafts")}
              disabled={!onNavigate}
            >
              к ревью →
            </button>
          </CardHeader>
          <CardContent className="p-0">
            <DecisionRow
              chip="ревью"
              chipVariant="info"
              title={`${decisions.pending_drafts || 0} черновиков ждут одобрения`}
              sub="одобрение ставит письмо в автоотправку в ближайший слот"
              actionLabel="Ревьюить"
              actionVariant="default"
              onAction={onNavigate ? () => onNavigate("drafts") : undefined}
            />
            <DecisionRow
              chip="фоллоу-ап"
              chipVariant="neutral"
              title={`${openFollowUpsTotal} открытых follow-up задач`}
              sub="треды без ответа — каденция предложит второе касание"
              actionLabel="Открыть"
              onAction={onNavigate ? () => onNavigate("reminders") : undefined}
            />
            {(queue.held || []).slice(0, 5).map((item) => (
              <DecisionRow
                key={item.id}
                chip="удержано"
                chipVariant="warning"
                title={`Письмо #${item.draft_id} на удержании`}
                sub={item.hold_reason || "причина не указана"}
                actionLabel="Освободить"
                onAction={() => void releaseHeld(item.id)}
              />
            ))}
            {(queue.held?.length || 0) > 5 ? (
              <p className="px-4 py-2 text-xs text-muted-foreground">и ещё {queue.held.length - 5} на удержании…</p>
            ) : null}
          </CardContent>
        </Card>

        {/* здоровье систем */}
        <Card className="border">
          <CardHeader className="border-b border-border/60 px-4 py-3">
            <CardTitle className="text-sm font-semibold">Система</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div className="flex items-center gap-3 border-b border-border/60 px-4 py-2.5 text-sm">
              <div className="min-w-0 flex-1">
                <div className="font-medium">Воркер очереди</div>
                <div className="mt-0.5 text-xs text-muted-foreground">
                  тик каждые {worker.interval_seconds} с · последний — {fmtInTz(worker.last_tick_at, tz)}
                </div>
              </div>
              {worker.enabled ? (
                <>
                  <Badge variant={worker.paused ? "danger" : "success"}>
                    {worker.paused ? "на паузе" : "работает"}
                  </Badge>
                  <Button
                    size="sm"
                    variant={worker.paused ? "default" : "outline"}
                    disabled={busy}
                    onClick={togglePause}
                  >
                    {worker.paused ? "Возобновить" : "Пауза"}
                  </Button>
                </>
              ) : (
                <Badge variant="neutral">выключен</Badge>
              )}
            </div>
            <div className="flex items-center gap-3 border-b border-border/60 px-4 py-2.5 text-sm">
              <div className="min-w-0 flex-1">
                <div className="font-medium">Политика отправки</div>
                <div className="mt-0.5 text-xs text-muted-foreground">
                  {today.policy_configured
                    ? `${today.mailbox_email} · окно ${today.window_start}–${today.window_end} (${tz})`
                    : "не настроена"}
                </div>
                {/* B-547: чья это на самом деле политика — рана/персоны, дефолтная, или её вовсе нет */}
                {today.policy_source === "run_persona" ? (
                  <div className="mt-0.5 text-xs text-muted-foreground">
                    политика персоны {today.persona_name || today.persona_slug}
                    {runName ? ` · ран ${runName}` : ""}
                  </div>
                ) : today.policy_source === "default" ? (
                  <div className="mt-0.5 text-xs font-medium text-warning">
                    дефолтная политика — к текущему рану может не относиться
                  </div>
                ) : today.policy_source === "none" ? (
                  <div className="mt-0.5 text-xs font-medium text-danger">
                    у ящика персоны {today.persona_name || today.persona_slug} нет политики
                    отправки — письма этого рана не встанут в очередь
                  </div>
                ) : null}
              </div>
              <Badge
                variant={
                  today.policy_source === "none"
                    ? "danger"
                    : today.policy_configured
                      ? "neutral"
                      : "warning"
                }
              >
                {today.policy_configured ? "активна" : "нет"}
              </Badge>
            </div>
            <div className="flex items-center gap-3 px-4 py-2.5 text-sm">
              <div className="min-w-0 flex-1">
                <div className="font-medium">Do-not-contact</div>
                <div className="mt-0.5 text-xs text-muted-foreground">управление — в панели ниже</div>
              </div>
              <Badge variant="neutral">{suppression_count}</Badge>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Статус Gmail-синка живёт в настройках почты (B-028); тут — только алярм при поломке:
          без синка не видим ответы и bounce, а каденция фоллоу-апов считает тишину неверно. */}
      {!gmail_sync.configured ? (
        <p className="flex items-center gap-2 rounded-md bg-warning-soft px-3 py-2 text-sm font-medium text-warning">
          ⚠ Gmail-синк не настроен — ответы и возвраты не отслеживаются. Проверьте подключение почты в настройках.
        </p>
      ) : null}

      <SendQueuePanel
        tz={tz}
        onOpenDraft={onOpenDraft || (onNavigate ? () => onNavigate("drafts") : undefined)}
      />
      <SendingPolicyPanel mailboxEmail={today.mailbox_email} />
      <SuppressionPanel />
    </div>
  );
}
