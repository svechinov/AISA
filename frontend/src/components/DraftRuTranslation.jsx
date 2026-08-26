import { useCallback, useState } from "react";
import { Button } from "@/components/ui/button";
import { Loader2, Languages } from "lucide-react";
import { API_BASE } from "@/lib/apiBase";

/**
 * On-demand RU translation button for the draft review panel. Alexey's English is weak, so he
 * reviews with a Russian translation alongside the English original before approving — the
 * translation is not persisted, just fetched and shown inline on click.
 */
export default function DraftRuTranslation({ draftId }) {
  const [state, setState] = useState("idle"); // idle | loading | shown | error
  const [translation, setTranslation] = useState(null);
  const [error, setError] = useState(null);

  const fetchTranslation = useCallback(async () => {
    setState("loading");
    setError(null);
    try {
      const r = await fetch(`${API_BASE}/email-drafts/${draftId}/translate`, { method: "POST" });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${r.status}`);
      }
      const data = await r.json();
      setTranslation(data);
      setState("shown");
    } catch (e) {
      setError(String(e.message || e));
      setState("error");
    }
  }, [draftId]);

  if (state === "idle" || state === "error") {
    return (
      <div className="space-y-1">
        <Button size="sm" variant="outline" className="gap-1.5" onClick={fetchTranslation}>
          <Languages className="h-3.5 w-3.5" aria-hidden />
          Показать RU
        </Button>
        {error ? <p className="text-xs text-destructive">{error}</p> : null}
      </div>
    );
  }

  if (state === "loading") {
    return (
      <Button size="sm" variant="outline" className="gap-1.5" disabled>
        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
        Перевожу…
      </Button>
    );
  }

  return (
    <div className="space-y-2 rounded-md border border-dashed border-border bg-muted/30 p-3 text-sm">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-muted-foreground">Перевод (RU)</span>
        <Button size="sm" variant="ghost" onClick={fetchTranslation}>
          Обновить перевод
        </Button>
      </div>
      <div>
        <span className="font-medium">Тема:</span> {translation.subject_ru}
      </div>
      <div className="whitespace-pre-wrap break-words">{translation.body_ru}</div>
    </div>
  );
}
