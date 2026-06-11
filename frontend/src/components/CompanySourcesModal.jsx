import React, { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "./ui/dialog";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Loader2, Globe, Search, Gavel, Download } from "lucide-react";

/** Фаза 4: источники компаний для Run — рейтинг по URL, поиск по критерию, тендерные закупки
 *  (intent). Добавленные компании проходят обычный AI-fit-скоринг и ICP-гейт перед OSINT. */
export function CompanySourcesModal({ apiBase, runId, onCompaniesAdded }) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState("url"); // url | criterion | tenders
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  const MODES = [
    { key: "url", label: "Рейтинг по URL", icon: Globe,
      placeholder: "https://rating.hh.ru/…", hint: "Страница рейтинга/списка → компании из неё" },
    { key: "criterion", label: "По критерию", icon: Search,
      placeholder: "производители мебели Урал", hint: "Поиск страниц-списков по критерию → извлечение" },
    { key: "tenders", label: "Тендеры (intent)", icon: Gavel,
      placeholder: "закупка тренинга для руководителей (можно пусто)", hint: "Заказчики закупок тренингов — уже покупают обучение" },
  ];
  const current = MODES.find((m) => m.key === mode);

  const run = async () => {
    if (!runId) { setError("Сначала выберите Run"); return; }
    if (mode !== "tenders" && !value.trim()) { setError("Заполните поле"); return; }
    setBusy(true); setError(""); setResult(null);
    const paths = {
      url: ["extract-url", { url: value.trim() }],
      criterion: ["extract-criterion", { criterion: value.trim() }],
      tenders: ["extract-tenders", { query: value.trim() }],
    };
    const [path, body] = paths[mode];
    try {
      const res = await fetch(`${apiBase}/company-sources/run/${runId}/${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const text = await res.text();
      if (!res.ok) {
        let detail = text;
        try { detail = JSON.parse(text)?.detail || text; } catch { /* keep raw */ }
        throw new Error(detail);
      }
      const data = JSON.parse(text);
      setResult(data);
      if (data.added_count > 0 && onCompaniesAdded) onCompaniesAdded();
    } catch (e) {
      setError(e.message || String(e));
    }
    setBusy(false);
  };

  return (
    <Dialog open={open} onOpenChange={(o) => { setOpen(o); if (!o) { setResult(null); setError(""); } }}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="gap-2 shrink-0">
          <Download className="h-4 w-4" />
          Источники
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Источники компаний</DialogTitle>
          <p className="text-sm text-muted-foreground">
            Добавляет компании в текущий Run (дубликаты пропускаются). Дальше — обычный путь:
            AI-анализ соответствия → enrich (отбракованные не тратят токены).
          </p>
        </DialogHeader>

        <div className="flex gap-1.5">
          {MODES.map((m) => (
            <Button key={m.key} type="button" size="sm"
                    variant={mode === m.key ? "default" : "outline"}
                    className="gap-1.5"
                    onClick={() => { setMode(m.key); setResult(null); setError(""); }}>
              <m.icon className="h-3.5 w-3.5" />
              {m.label}
            </Button>
          ))}
        </div>

        <div className="space-y-1.5">
          <p className="text-xs text-muted-foreground">{current.hint}</p>
          <div className="flex gap-2">
            <Input placeholder={current.placeholder} value={value}
                   onChange={(e) => setValue(e.target.value)}
                   onKeyDown={(e) => e.key === "Enter" && !busy && run()} />
            <Button onClick={run} disabled={busy} className="shrink-0">
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Извлечь"}
            </Button>
          </div>
        </div>

        {error && <div className="text-sm text-destructive border border-destructive/30 rounded-md p-2">{error}</div>}

        {result && (
          <div className="text-sm border rounded-md p-3 space-y-1.5 max-h-64 overflow-y-auto">
            <div>
              Извлечено: <b>{result.extracted}</b> · добавлено: <b>{result.added_count}</b>
              {result.skipped_duplicates > 0 && <> · дубликатов пропущено: {result.skipped_duplicates}</>}
            </div>
            {result.added?.length > 0 && (
              <ul className="list-disc pl-5 text-xs space-y-0.5">
                {result.added.map((n, i) => <li key={i}>{n}</li>)}
              </ul>
            )}
            {result.source_urls?.length > 0 && (
              <div className="text-xs text-muted-foreground">
                Источники: {result.source_urls.map((u, i) => (
                  <a key={i} href={u} target="_blank" rel="noopener noreferrer" className="underline mr-2 break-all">{u}</a>
                ))}
              </div>
            )}
            {result.extracted === 0 && (
              <div className="text-xs text-muted-foreground">
                Ничего не извлечено — попробуйте другой URL/запрос (страница могла не отдать контент).
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
