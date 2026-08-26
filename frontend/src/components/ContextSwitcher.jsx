import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { RUN_PHASE_CHIP } from "@/lib/runPhase";

/** Один выпадающий сегмент селектора контекста. Меню закрывается кликом вне и Escape. */
function Segment({ label, bold, title, disabled, children, menuWidth = "min-w-[240px]" }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    const onKey = (e) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative min-w-0">
      <button
        type="button"
        title={title}
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "flex min-w-0 items-center gap-1.5 px-3 py-1.5 text-sm transition-colors hover:bg-muted disabled:cursor-default disabled:opacity-70",
          bold && "font-semibold",
        )}
      >
        <span className="truncate">{label}</span>
        <ChevronDown
          className={cn("h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")}
          aria-hidden
        />
      </button>
      {open ? (
        <div
          className={cn(
            "absolute left-0 top-full z-50 mt-1 max-h-80 overflow-y-auto rounded-md border border-border bg-card py-1 shadow-lg",
            menuWidth,
          )}
        >
          {typeof children === "function" ? children(() => setOpen(false)) : children}
        </div>
      ) : null}
    </div>
  );
}

function MenuItem({ active, onClick, children, chip }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-muted"
    >
      <span className={cn("h-3.5 w-3.5 shrink-0", !active && "opacity-0")}>
        <Check className="h-3.5 w-3.5 text-primary" aria-hidden />
      </span>
      <span className="min-w-0 flex-1 truncate">{children}</span>
      {chip}
    </button>
  );
}

/**
 * Селектор рабочего контекста в шапке (B-028, согласовано 10.07): два дропдауна —
 * проект (сегмент рынка) и кампания (волна). Только переключение: выбор меняет данные
 * всех экранов; создание и настройка проектов/кампаний живут на экране «Проекты».
 */
export default function ContextSwitcher({
  projects = [],
  selectedProject,
  onSelectProject,
  runs = [],
  selectedRun,
  onSelectRun,
  onOpenProjectsScreen,
}) {
  const activeProjects = projects.filter((p) => !p.is_archived);

  const footer = onOpenProjectsScreen ? (
    <>
      <div className="my-1 border-t border-border" aria-hidden />
      <button
        type="button"
        onClick={onOpenProjectsScreen}
        className="w-full px-3 py-1.5 text-left text-sm font-medium text-info hover:bg-muted"
      >
        Экран «Проекты» — создание и настройка →
      </button>
    </>
  ) : null;

  return (
    <div className="flex min-w-0 max-w-full items-stretch overflow-visible rounded-md border border-border bg-card">
      <Segment
        label={selectedProject?.name ?? "Проект не выбран"}
        bold
        title="Выбрать проект (сегмент рынка)"
      >
        {(close) => (
          <>
            {activeProjects.length === 0 ? (
              <p className="px-3 py-2 text-sm text-muted-foreground">Проектов пока нет.</p>
            ) : (
              activeProjects.map((p) => (
                <MenuItem
                  key={p.id}
                  active={selectedProject?.id === p.id}
                  onClick={() => {
                    onSelectProject?.(p);
                    close();
                  }}
                >
                  {p.name}
                </MenuItem>
              ))
            )}
            {footer}
          </>
        )}
      </Segment>
      <span className="w-px shrink-0 bg-border" aria-hidden />
      <Segment
        label={
          selectedRun
            ? selectedRun.name?.trim() || `Кампания #${selectedRun.id}`
            : "кампания не выбрана"
        }
        title="Выбрать кампанию (волну)"
        disabled={!selectedProject}
        menuWidth="min-w-[280px]"
      >
        {(close) => (
          <>
            {runs.length === 0 ? (
              <p className="px-3 py-2 text-sm text-muted-foreground">
                В проекте пока нет кампаний.
              </p>
            ) : (
              runs.map((r) => {
                const phase = RUN_PHASE_CHIP[r.display_phase];
                return (
                  <MenuItem
                    key={r.id}
                    active={selectedRun?.id === r.id}
                    onClick={() => {
                      onSelectRun?.(r);
                      close();
                    }}
                    chip={phase ? <Badge variant={phase.variant}>{phase.label}</Badge> : null}
                  >
                    {r.name?.trim() || `Кампания #${r.id}`}
                  </MenuItem>
                );
              })
            )}
            {footer}
          </>
        )}
      </Segment>
    </div>
  );
}
