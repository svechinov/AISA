import { useCallback, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { API_BASE } from "@/lib/apiBase";

const NUMBER_FIELDS = [
  ["daily_cap", "Писем в день (потолок)"],
  ["hourly_cap", "Писем в час"],
  ["min_gap_minutes", "Мин. пауза между письмами (мин)"],
  ["gap_jitter_minutes", "Случайный разброс паузы (мин)"],
  ["follow_up_after_business_days", "Фоллоу-ап через N раб. дней тишины"],
  ["max_touches", "Макс. касаний на контакт"],
];

const TEXT_FIELDS = [
  ["send_days_first_touch", "Дни для первого письма (mon,tue,...)"],
  ["send_days_follow_up", "Дни для фоллоу-апов (mon,tue,...)"],
  ["window_start", "Начало окна (HH:MM)"],
  ["window_end", "Конец окна (HH:MM)"],
  ["timezone", "Часовой пояс (IANA)"],
];

/**
 * Editable sending policy — caps, send window, warm-up ramp, follow-up cadence. Backend validates
 * (app/schemas/sending_policy.py) so a bad value here is rejected with a clear message rather than
 * silently breaking the worker.
 *
 * mailboxEmail (B-547): раньше панель молча брала первую по id политику (items[0]) — легко было
 * править чужой ящик, не заметив. Если передан mailboxEmail — выбираем строку с этим ящиком,
 * fallback на items[0]. При нескольких политиках сверху появляется select ящика.
 */
export default function SendingPolicyPanel({ mailboxEmail } = {}) {
  const [items, setItems] = useState([]);
  const [policy, setPolicy] = useState(null);
  const [form, setForm] = useState({});
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/sending/policies`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      const list = data.items || [];
      setItems(list);
      const chosen = (mailboxEmail && list.find((p) => p.mailbox_email === mailboxEmail)) || list[0] || null;
      setPolicy(chosen);
      if (chosen) setForm(chosen);
      setError(null);
    } catch (e) {
      setError(String(e.message || e));
    }
  }, [mailboxEmail]);

  useEffect(() => {
    load();
  }, [load]);

  const selectMailbox = (email) => {
    const chosen = items.find((p) => p.mailbox_email === email) || null;
    setPolicy(chosen);
    if (chosen) setForm(chosen);
    setSaved(false);
  };

  const setField = (key, value) => {
    setForm((f) => ({ ...f, [key]: value }));
    setSaved(false);
  };

  const save = useCallback(async () => {
    if (!policy) return;
    setSaving(true);
    setError(null);
    try {
      const payload = {};
      for (const [key] of [...NUMBER_FIELDS]) {
        const v = form[key];
        if (v === "" || v === null || v === undefined) continue;
        payload[key] = Number(v);
      }
      for (const [key] of TEXT_FIELDS) {
        if (form[key] !== undefined && form[key] !== "") payload[key] = form[key];
      }
      if (form.warmup_ramp_json) payload.warmup_ramp_json = form.warmup_ramp_json;
      const r = await fetch(`${API_BASE}/sending/policies/${policy.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${r.status}`);
      }
      const updated = await r.json();
      setPolicy(updated);
      setForm(updated);
      setItems((list) => list.map((p) => (p.id === updated.id ? updated : p)));
      setSaved(true);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setSaving(false);
    }
  }, [policy, form]);

  if (!policy) {
    return (
      <Card className="border">
        <CardHeader>
          <CardTitle className="text-base">Политика отправки</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          {error ? `Ошибка: ${error}` : "Загрузка…"}
        </CardContent>
      </Card>
    );
  }

  const ramp = form.warmup_ramp_json || {};
  const setRampField = (key, value) => {
    setForm((f) => ({ ...f, warmup_ramp_json: { ...(f.warmup_ramp_json || {}), [key]: value } }));
    setSaved(false);
  };

  return (
    <Card className="border">
      <CardHeader>
        <CardTitle className="text-base">Политика отправки — {policy.mailbox_email}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        {error ? <p className="text-destructive">{error}</p> : null}
        {saved ? <p className="text-green-600">Сохранено.</p> : null}

        {items.length > 1 ? (
          <label className="block space-y-1">
            <span className="block text-xs text-muted-foreground">Ящик (политик несколько — выбирайте осознанно)</span>
            <select
              className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={policy.mailbox_email}
              onChange={(e) => selectMailbox(e.target.value)}
            >
              {items.map((p) => (
                <option key={p.id} value={p.mailbox_email}>
                  {p.mailbox_email}
                </option>
              ))}
            </select>
          </label>
        ) : null}

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {NUMBER_FIELDS.map(([key, label]) => (
            <label key={key} className="space-y-1">
              <span className="block text-xs text-muted-foreground">{label}</span>
              <Input
                type="number"
                min={key === "gap_jitter_minutes" ? 0 : 1}
                value={form[key] ?? ""}
                onChange={(e) => setField(key, e.target.value)}
              />
            </label>
          ))}
          {TEXT_FIELDS.map(([key, label]) => (
            <label key={key} className="space-y-1">
              <span className="block text-xs text-muted-foreground">{label}</span>
              <Input value={form[key] ?? ""} onChange={(e) => setField(key, e.target.value)} />
            </label>
          ))}
        </div>

        <div className="rounded border p-3">
          <p className="mb-2 text-xs font-medium text-muted-foreground">
            Прогрев (warm-up): старт → +шаг/неделю → потолок
          </p>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <label className="space-y-1">
              <span className="block text-xs text-muted-foreground">Старт (писем/день)</span>
              <Input
                type="number"
                min={1}
                value={ramp.start ?? ""}
                onChange={(e) => setRampField("start", Number(e.target.value))}
              />
            </label>
            <label className="space-y-1">
              <span className="block text-xs text-muted-foreground">Шаг в неделю</span>
              <Input
                type="number"
                min={0}
                value={ramp.step_per_week ?? ""}
                onChange={(e) => setRampField("step_per_week", Number(e.target.value))}
              />
            </label>
            <label className="space-y-1">
              <span className="block text-xs text-muted-foreground">Потолок</span>
              <Input
                type="number"
                min={1}
                value={ramp.cap ?? ""}
                onChange={(e) => setRampField("cap", Number(e.target.value))}
              />
            </label>
            <label className="space-y-1">
              <span className="block text-xs text-muted-foreground">Старт прогрева (YYYY-MM-DD)</span>
              <Input value={ramp.started_on ?? ""} onChange={(e) => setRampField("started_on", e.target.value)} />
            </label>
          </div>
        </div>

        <Button size="sm" onClick={save} disabled={saving}>
          {saving ? "Сохраняю…" : "Сохранить"}
        </Button>
      </CardContent>
    </Card>
  );
}
