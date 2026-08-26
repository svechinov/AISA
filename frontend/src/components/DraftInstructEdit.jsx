import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Loader2, Wand2, X } from "lucide-react";
import { API_BASE } from "@/lib/apiBase";

/**
 * B-018: инструктивная правка письма. Ревьюер пишет по-русски, что поправить → LLM меняет
 * ТОЛЬКО это место в английском тексте → предпросмотр «новый EN + новый RU» → «Принять»
 * сохраняет правку, перепрогоняет критика и сохраняет слот в очереди (apply-эндпойнт).
 */
export default function DraftInstructEdit({ draftId, onApplied, otherPendingIds = [] }) {
  const [instruction, setInstruction] = useState("");
  // idle | loading | preview | applying | applied (предложение батча) | batching
  const [phase, setPhase] = useState("idle");
  const [proposal, setProposal] = useState(null);
  const [error, setError] = useState(null);
  const [appliedInstruction, setAppliedInstruction] = useState("");
  const [batchProgress, setBatchProgress] = useState(null); // {done, total, failed[]}

  const requestEdit = async () => {
    const text = instruction.trim();
    if (!text) return;
    setPhase("loading");
    setError(null);
    try {
      const r = await fetch(`${API_BASE}/email-drafts/${draftId}/instruct`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instruction: text }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${r.status}`);
      setProposal(data);
      setPhase("preview");
    } catch (e) {
      setError(String(e?.message || e));
      setPhase("idle");
    }
  };

  const applyEdit = async () => {
    if (!proposal) return;
    setPhase("applying");
    setError(null);
    try {
      const r = await fetch(`${API_BASE}/email-drafts/${draftId}/instruct-apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // instruction уходит в журнал правок (B-031): повторяющиеся правки — сигнал для канона
        body: JSON.stringify({ subject: proposal.subject, body: proposal.body, instruction: instruction.trim() || null }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${r.status}`);
      const usedInstruction = instruction.trim();
      setInstruction("");
      setProposal(null);
      onApplied?.(data);
      // Уровень волны: та же правка часто нужна остальным письмам, сгенерированным ДО неё —
      // предлагаем применить батчем, чтобы не повторять комментарий к каждому письму руками.
      if (usedInstruction && otherPendingIds.length > 0) {
        setAppliedInstruction(usedInstruction);
        setPhase("applied");
      } else {
        setPhase("idle");
      }
    } catch (e) {
      setError(String(e?.message || e));
      setPhase("preview");
    }
  };

  /** Батч: для каждого ожидающего письма — своя минимальная правка той же инструкцией + apply
   *  (критик перепроверяет каждое; письма остаются pending и всё равно пройдут твоё ревью). */
  const applyToOthers = async () => {
    setPhase("batching");
    setError(null);
    const failed = [];
    const total = otherPendingIds.length;
    for (let i = 0; i < total; i += 1) {
      const id = otherPendingIds[i];
      setBatchProgress({ done: i, total, failed });
      try {
        const r1 = await fetch(`${API_BASE}/email-drafts/${id}/instruct`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ instruction: appliedInstruction }),
        });
        const p = await r1.json().catch(() => ({}));
        if (!r1.ok) throw new Error(typeof p.detail === "string" ? p.detail : `HTTP ${r1.status}`);
        const r2 = await fetch(`${API_BASE}/email-drafts/${id}/instruct-apply`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ subject: p.subject, body: p.body, instruction: appliedInstruction }),
        });
        if (!r2.ok) {
          const a = await r2.json().catch(() => ({}));
          throw new Error(typeof a.detail === "string" ? a.detail : `HTTP ${r2.status}`);
        }
      } catch (e) {
        failed.push(`#${id}: ${String(e?.message || e)}`);
      }
    }
    setBatchProgress({ done: total, total, failed });
    setPhase("idle");
    setAppliedInstruction("");
    if (failed.length > 0) setError(`Не применилось к ${failed.length} письмам — ${failed.join("; ")}`);
    onApplied?.();
  };

  return (
    <div className="space-y-2 rounded-md border border-border bg-muted/20 p-3">
      <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        <Wand2 className="h-3.5 w-3.5" aria-hidden />
        Комментарий к письму
      </div>

      {phase === "applied" ? (
        <div className="space-y-2">
          <p className="text-sm">
            Правка принята. Применить её же к остальным ожидающим письмам ({otherPendingIds.length})?
            <span className="mt-0.5 block text-xs text-muted-foreground">
              каждое письмо правится отдельно той же инструкцией и перепроверяется критиком; все они
              остаются на твоём ревью — одобрение по-прежнему вручную
            </span>
          </p>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={() => void applyToOthers()}>
              Да, ко всем ({otherPendingIds.length})
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setPhase("idle");
                setAppliedInstruction("");
              }}
            >
              Нет, только это письмо
            </Button>
          </div>
        </div>
      ) : phase === "batching" ? (
        <div className="flex items-center gap-2 text-sm">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          Применяю к остальным…{" "}
          <span className="tabular-nums">
            {batchProgress ? `${batchProgress.done} из ${batchProgress.total}` : ""}
          </span>
        </div>
      ) : phase !== "preview" && phase !== "applying" ? (
        <>
          <Textarea
            rows={2}
            placeholder="Напиши по-русски, что поправить — изменится только это место, остальной текст останется как есть"
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            disabled={phase === "loading"}
          />
          <div className="flex items-center gap-2">
            <Button size="sm" onClick={() => void requestEdit()} disabled={phase === "loading" || !instruction.trim()}>
              {phase === "loading" ? (
                <>
                  <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" aria-hidden />
                  Правлю…
                </>
              ) : (
                "Предложить правку"
              )}
            </Button>
            {error ? <p className="min-w-0 text-xs text-danger">{error}</p> : null}
          </div>
        </>
      ) : (
        <div className="space-y-2">
          <div className="rounded-md border border-warning/40 bg-warning-soft/40 p-3">
            <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-warning">
              Предпросмотр правки — проверь по-русски и прими
            </div>
            <div className="mb-2 text-sm">
              <span className="font-medium">Тема:</span> {proposal.subject}
            </div>
            {/* B-546: письмо на русском правится по-русски — второй (переводной) колонке взяться
                неоткуда и не нужно, она дублировала бы тот же текст. */}
            {proposal.language === "ru" ? (
              <div className="min-w-0">
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Новый текст
                </div>
                <div className="whitespace-pre-wrap break-words rounded-md bg-background/60 p-2 text-sm leading-relaxed">
                  {proposal.body}
                </div>
              </div>
            ) : (
              <div className="grid grid-cols-1 items-start gap-3 lg:grid-cols-2">
                <div className="min-w-0">
                  <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Новый EN
                  </div>
                  <div className="whitespace-pre-wrap break-words rounded-md bg-background/60 p-2 text-sm leading-relaxed">
                    {proposal.body}
                  </div>
                </div>
                <div className="min-w-0">
                  <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Новый RU (для проверки)
                  </div>
                  <div className="whitespace-pre-wrap break-words rounded-md bg-background/60 p-2 text-sm leading-relaxed">
                    {proposal.body_ru || "—"}
                  </div>
                </div>
              </div>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" onClick={() => void applyEdit()} disabled={phase === "applying"}>
              {phase === "applying" ? (
                <>
                  <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" aria-hidden />
                  Применяю…
                </>
              ) : (
                "Принять правку"
              )}
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={phase === "applying"}
              onClick={() => {
                setProposal(null);
                setPhase("idle");
              }}
            >
              Ещё раз / изменить инструкцию
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={phase === "applying"}
              onClick={() => {
                setProposal(null);
                setInstruction("");
                setPhase("idle");
              }}
            >
              <X className="mr-1 h-3.5 w-3.5" aria-hidden />
              Отменить
            </Button>
            <span className="text-xs text-muted-foreground">
              после принятия критик перепроверит письмо; слот в очереди сохранится
            </span>
            {error ? <p className="w-full text-xs text-danger">{error}</p> : null}
          </div>
        </div>
      )}
    </div>
  );
}
