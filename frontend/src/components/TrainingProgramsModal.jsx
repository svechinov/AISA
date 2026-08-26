import React, { useState, useEffect } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "./ui/dialog";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Textarea } from "./ui/textarea";
import { Badge } from "./ui/badge";
import { GraduationCap, Trash2, Plus, Loader2, Pencil, X, Paperclip } from "lucide-react";

/** Каталог офферов (бывш. «тренинговые программы» — наследие старой системы): матчер
 *  подставляет оффер в слот «Решение» письма. Управляется извне через open/onOpenChange
 *  (вход — «Настройки» в сайдбаре, B-028); без этих пропсов рендерит собственную кнопку. */
export function TrainingProgramsModal({ apiBase, open: openProp, onOpenChange }) {
  const controlled = openProp !== undefined;
  const [openState, setOpenState] = useState(false);
  const open = controlled ? openProp : openState;
  const setOpen = (v) => {
    if (onOpenChange) onOpenChange(v);
    if (!controlled) setOpenState(v);
  };
  const [programs, setPrograms] = useState([]);
  const [assets, setAssets] = useState([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editingId, setEditingId] = useState(null);

  const emptyForm = { name: "", description: "", target_pains: "", audience: "", format: "", bullets: "", asset_id: "" };
  const [form, setForm] = useState(emptyForm);

  // Authorization is injected by the global fetch interceptor (src/main.jsx) — do not duplicate it here.
  const authHeaders = () => ({ "Content-Type": "application/json" });

  const fetchAll = async () => {
    setLoading(true);
    try {
      const [pRes, aRes] = await Promise.all([
        fetch(`${apiBase}/training-programs`, { headers: authHeaders() }),
        fetch(`${apiBase}/assets`, { headers: authHeaders() }),
      ]);
      if (pRes.ok) setPrograms(await pRes.json());
      if (aRes.ok) setAssets(await aRes.json());
    } catch (e) {
      console.error("Failed to load training programs", e);
    }
    setLoading(false);
  };

  useEffect(() => {
    if (open) fetchAll();
  }, [open, apiBase]);

  const linesToList = (s) => String(s || "").split("\n").map((x) => x.trim()).filter(Boolean);

  const startEdit = (p) => {
    setEditingId(p.id);
    setForm({
      name: p.name || "",
      description: p.description || "",
      target_pains: (p.target_pains || []).join("\n"),
      audience: p.audience || "",
      format: p.format || "",
      bullets: (p.bullets || []).join("\n"),
      asset_id: p.asset_id ? String(p.asset_id) : "",
    });
  };

  const cancelEdit = () => {
    setEditingId(null);
    setForm(emptyForm);
  };

  const handleSave = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const payload = {
        name: form.name,
        description: form.description || null,
        target_pains: linesToList(form.target_pains),
        audience: form.audience || null,
        format: form.format || null,
        bullets: linesToList(form.bullets),
        asset_id: form.asset_id ? Number(form.asset_id) : null,
      };
      const url = editingId
        ? `${apiBase}/training-programs/${editingId}`
        : `${apiBase}/training-programs`;
      const res = await fetch(url, {
        method: editingId ? "PATCH" : "POST",
        headers: authHeaders(),
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        cancelEdit();
        fetchAll();
      } else {
        alert("Не удалось сохранить программу: " + (await res.text()).slice(0, 300));
      }
    } catch (e) {
      console.error(e);
    }
    setSaving(false);
  };

  const handleArchive = async (id) => {
    if (!confirm("Архивировать программу? Матчер перестанет её предлагать.")) return;
    try {
      await fetch(`${apiBase}/training-programs/${id}`, { method: "DELETE", headers: authHeaders() });
      if (editingId === id) cancelEdit();
      fetchAll();
    } catch (e) {
      console.error(e);
    }
  };

  const assetName = (id) => {
    const a = assets.find((x) => x.id === id);
    return a ? (a.name || a.filename || `Asset #${id}`) : `Asset #${id}`;
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      {!controlled ? (
        <DialogTrigger asChild>
          <Button variant="outline" size="sm" className="gap-2 shrink-0">
            <GraduationCap className="h-4 w-4" />
            Офферы
          </Button>
        </DialogTrigger>
      ) : null}
      <DialogContent className="max-w-4xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>Каталог офферов</DialogTitle>
          <p className="text-sm text-muted-foreground">
            Матчер подбирает оффер под боль компании и подставляет его в слот «Решение» письма.
            Пустой каталог = письма используют общий оффер из промпта кампании.
          </p>
        </DialogHeader>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 flex-1 min-h-0">
          {/* List side */}
          <div className="overflow-y-auto pr-2 space-y-3">
            <h3 className="font-semibold text-sm">Активные офферы ({programs.length})</h3>
            {loading ? (
              <div className="flex justify-center p-4"><Loader2 className="animate-spin h-5 w-5" /></div>
            ) : programs.length === 0 ? (
              <div className="text-sm text-muted-foreground p-4 border border-dashed rounded-lg text-center">
                Каталог пуст — письма используют общий оффер из промпта кампании.
              </div>
            ) : (
              programs.map((p) => (
                <div key={p.id} className="border rounded-lg p-3 flex flex-col gap-1.5 shadow-sm text-sm">
                  <div className="flex justify-between items-start gap-2">
                    <div className="font-medium">{p.name}</div>
                    <div className="flex gap-1 shrink-0">
                      <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => startEdit(p)}>
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => handleArchive(p.id)}>
                        <Trash2 className="h-3.5 w-3.5 text-destructive" />
                      </Button>
                    </div>
                  </div>
                  {p.format && <div className="text-xs text-muted-foreground">{p.format}{p.audience ? ` · ${p.audience}` : ""}</div>}
                  {(p.target_pains || []).length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {p.target_pains.map((tp, i) => (
                        <Badge key={i} variant="secondary" className="text-[10px]">{tp}</Badge>
                      ))}
                    </div>
                  )}
                  {p.asset_id && (
                    <div className="flex items-center gap-1 text-xs text-muted-foreground">
                      <Paperclip className="h-3 w-3" /> {assetName(p.asset_id)}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>

          {/* Form side */}
          <form onSubmit={handleSave} className="flex flex-col gap-2.5 bg-muted/30 p-4 rounded-md border overflow-y-auto">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold text-sm">{editingId ? `Правка #${editingId}` : "Новый оффер"}</h3>
              {editingId && (
                <Button type="button" variant="ghost" size="sm" className="h-7 gap-1" onClick={cancelEdit}>
                  <X className="h-3.5 w-3.5" /> Отмена
                </Button>
              )}
            </div>

            <div className="space-y-1">
              <label className="text-xs font-medium">Название *</label>
              <Input required placeholder="Быстрое закрытие одной ключевой роли" value={form.name}
                     onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </div>

            <div className="space-y-1">
              <label className="text-xs font-medium">Описание</label>
              <Textarea rows={2} placeholder="Что это за оффер и какой результат даёт клиенту"
                        value={form.description}
                        onChange={(e) => setForm({ ...form, description: e.target.value })} />
            </div>

            <div className="space-y-1">
              <label className="text-xs font-medium">Целевые боли (по одной на строку) *</label>
              <Textarea rows={3} placeholder={"долгий найм\nоткрыто несколько ролей параллельно\nне хватает senior-кандидатов"}
                        value={form.target_pains}
                        onChange={(e) => setForm({ ...form, target_pains: e.target.value })} />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-xs font-medium">Аудитория</label>
                <Input placeholder="фаундеры и лиды студий 10–30 чел." value={form.audience}
                       onChange={(e) => setForm({ ...form, audience: e.target.value })} />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium">Формат</label>
                <Input placeholder="contingency-поиск" value={form.format}
                       onChange={(e) => setForm({ ...form, format: e.target.value })} />
              </div>
            </div>

            <div className="space-y-1">
              <label className="text-xs font-medium">Буллиты для письма (по одному на строку)</label>
              <Textarea rows={3} placeholder={"первый кандидат через 24–72 часа после согласования условий\nкандидаты приходят уже мотивированными"}
                        value={form.bullets}
                        onChange={(e) => setForm({ ...form, bullets: e.target.value })} />
            </div>

            {/* Поле «PDF-материал» скрыто (решение 10.07): вложений в холодных письмах нет,
                материалы — только после ответа. asset_id в форме и бэкенде сохранён. */}

            <Button type="submit" className="mt-1 w-full" disabled={saving}>
              {saving ? <Loader2 className="animate-spin h-4 w-4 mr-2" /> : <Plus className="h-4 w-4 mr-2" />}
              {editingId ? "Сохранить изменения" : "Добавить оффер"}
            </Button>
          </form>
        </div>
      </DialogContent>
    </Dialog>
  );
}
