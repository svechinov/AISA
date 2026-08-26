import { useCallback, useEffect, useMemo, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { API_BASE } from "@/lib/apiBase";

function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" });
}

const REASON_VARIANT = {
  dead_mailbox: "destructive",
  not_interested: "secondary",
  bounced: "outline",
  manual: "outline",
  unsubscribe: "secondary",
};

/**
 * Do-not-contact registry: view, search, add, and remove entries. Removing an entry does not
 * un-send anything — it only lets a future send to that address pass the suppression gate again,
 * so it's meant for correcting false positives (e.g. a soft bounce misclassified before the fix
 * that stopped `bounced` from auto-suppressing).
 */
export default function SuppressionPanel() {
  const [items, setItems] = useState([]);
  const [query, setQuery] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API_BASE}/suppression`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setItems(Array.isArray(data.items) ? data.items : []);
      setError(null);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (i) => i.email.toLowerCase().includes(q) || (i.domain || "").toLowerCase().includes(q),
    );
  }, [items, query]);

  const addEntry = useCallback(async () => {
    const email = newEmail.trim();
    if (!email) return;
    setAdding(true);
    setError(null);
    try {
      const r = await fetch(`${API_BASE}/suppression`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, reason: "manual" }),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${r.status}`);
      }
      setNewEmail("");
      await load();
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setAdding(false);
    }
  }, [newEmail, load]);

  const removeEntry = useCallback(
    async (id, email) => {
      if (!confirm(`Убрать ${email} из do-not-contact? Письма этому адресу снова смогут проходить гейт.`)) return;
      try {
        const r = await fetch(`${API_BASE}/suppression/${id}`, { method: "DELETE" });
        if (!r.ok && r.status !== 204) throw new Error(`HTTP ${r.status}`);
        await load();
      } catch (e) {
        setError(String(e.message || e));
      }
    },
    [load],
  );

  return (
    <Card className="border">
      <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0">
        <CardTitle className="text-base">Suppression ({items.length})</CardTitle>
        <Button size="sm" variant="outline" onClick={load} disabled={loading}>
          Обновить
        </Button>
      </CardHeader>
      <CardContent className="space-y-3">
        {error ? <p className="text-sm text-destructive">{error}</p> : null}

        <div className="flex flex-col gap-2 sm:flex-row">
          <Input
            placeholder="Добавить email в do-not-contact"
            value={newEmail}
            onChange={(e) => setNewEmail(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addEntry()}
          />
          <Button size="sm" onClick={addEntry} disabled={adding || !newEmail.trim()}>
            Добавить
          </Button>
        </div>

        <Input placeholder="Поиск по email/домену" value={query} onChange={(e) => setQuery(e.target.value)} />

        {filtered.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {items.length === 0 ? "Список пуст." : "Ничего не найдено."}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="py-1 pr-3 font-medium">Email</th>
                  <th className="py-1 pr-3 font-medium">Причина</th>
                  <th className="py-1 pr-3 font-medium">Заметка</th>
                  <th className="py-1 pr-3 font-medium">Добавлено</th>
                  <th className="py-1 font-medium" />
                </tr>
              </thead>
              <tbody>
                {filtered.map((item) => (
                  <tr key={item.id} className="border-b last:border-0">
                    <td className="py-1 pr-3">{item.email}</td>
                    <td className="py-1 pr-3">
                      <Badge variant={REASON_VARIANT[item.reason] || "secondary"}>{item.reason}</Badge>
                    </td>
                    <td className="py-1 pr-3 text-muted-foreground">{item.note || "—"}</td>
                    <td className="py-1 pr-3 whitespace-nowrap text-muted-foreground">
                      {fmtDate(item.created_at)}
                    </td>
                    <td className="py-1">
                      <Button size="sm" variant="ghost" onClick={() => removeEntry(item.id, item.email)}>
                        Убрать
                      </Button>
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
