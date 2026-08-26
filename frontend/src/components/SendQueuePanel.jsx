import { useCallback, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { API_BASE } from "@/lib/apiBase";
import { fmtInTz, DEFAULT_TZ } from "@/lib/timeTz";

/** Статусы очереди → русский чип семантического цвета (B-028). */
const STATE_CHIP = {
  queued: { label: "в очереди", variant: "neutral" },
  held: { label: "удержано", variant: "warning" },
  releasing: { label: "освобождается", variant: "info" },
  sent: { label: "отправлено", variant: "success" },
  canceled: { label: "отменено", variant: "outline" },
  failed: { label: "ошибка", variant: "danger" },
};

/**
 * Очередь отправки — живое расписание аутрича (общее для всех кампаний, это очередь ящика):
 * слот, письмо, касание, статус, причина удержания/переноса. «Пауза всё» — аварийный стоп.
 * B-016: слоты по таймзоне политики; B-017: № черновика кликабелен (onOpenDraft).
 */
export default function SendQueuePanel({ tz = DEFAULT_TZ, onOpenDraft }) {
  const [items, setItems] = useState([]);
  const [paused, setPaused] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(`${API_BASE}/sending/queue`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setItems(Array.isArray(data.items) ? data.items : []);
      setPaused(Boolean(data.paused));
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const post = useCallback(
    async (path) => {
      try {
        await fetch(`${API_BASE}${path}`, { method: "POST" });
        await load();
      } catch (e) {
        setError(String(e.message || e));
      }
    },
    [load],
  );

  const active = items.filter((i) => i.state !== "sent" && i.state !== "canceled");

  return (
    <Card className="border">
      <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0 border-b border-border/60 px-4 py-3">
        <CardTitle className="text-sm font-semibold">
          Очередь отправки
          {paused ? (
            <Badge variant="danger" className="ml-2 align-middle">
              на паузе
            </Badge>
          ) : null}
        </CardTitle>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" onClick={load} disabled={loading}>
            Обновить
          </Button>
          {paused ? (
            <Button size="sm" onClick={() => post("/sending/queue/resume")}>
              Возобновить
            </Button>
          ) : (
            <Button size="sm" variant="destructive" onClick={() => post("/sending/queue/pause")}>
              Пауза всё
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {error ? <p className="px-4 pt-3 text-sm text-danger">Ошибка очереди: {error}</p> : null}
        {active.length === 0 ? (
          <p className="px-4 py-4 text-sm text-muted-foreground">
            Очередь пуста — одобренные черновики появятся здесь со слотом отправки.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/60 text-left text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  <th className="px-4 py-2">Когда · {tz.replace("Asia/", "")}</th>
                  <th className="px-2 py-2">Письмо</th>
                  <th className="px-2 py-2">Касание</th>
                  <th className="px-2 py-2">Статус</th>
                  <th className="px-2 py-2">Причина</th>
                  <th className="px-2 py-2" />
                </tr>
              </thead>
              <tbody>
                {active.map((i) => (
                  <tr key={i.id} className="border-b border-border/60 last:border-0 hover:bg-muted/40">
                    <td className="whitespace-nowrap px-4 py-1.5 tabular-nums">{fmtInTz(i.not_before, tz)}</td>
                    <td className="px-2 py-1.5">
                      {onOpenDraft ? (
                        <button
                          type="button"
                          className="font-medium text-info hover:underline"
                          title="Открыть в «Ревью писем»"
                          onClick={() => onOpenDraft(i.draft_id)}
                        >
                          #{i.draft_id}
                        </button>
                      ) : (
                        <>#{i.draft_id}</>
                      )}
                    </td>
                    <td className="px-2 py-1.5 tabular-nums">{i.touch_number}</td>
                    <td className="px-2 py-1.5">
                      <Badge variant={STATE_CHIP[i.state]?.variant || "neutral"}>
                        {STATE_CHIP[i.state]?.label || i.state}
                      </Badge>
                    </td>
                    <td className="px-2 py-1.5 text-muted-foreground">
                      {(i.state === "queued" ? i.last_reschedule_reason : i.hold_reason) || "—"}
                    </td>
                    <td className="px-2 py-1.5">
                      <div className="flex justify-end gap-1 pr-2">
                        {i.state === "held" ? (
                          <Button size="sm" variant="outline" onClick={() => post(`/sending/queue/${i.id}/release`)}>
                            Освободить
                          </Button>
                        ) : (
                          <Button size="sm" variant="outline" onClick={() => post(`/sending/queue/${i.id}/hold`)}>
                            Удержать
                          </Button>
                        )}
                        <Button size="sm" variant="ghost" onClick={() => post(`/sending/queue/${i.id}/cancel`)}>
                          Отменить
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
