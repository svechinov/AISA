import {
  Home,
  Mail,
  Megaphone,
  Building2,
  Users,
  MessagesSquare,
  Reply,
  Bell,
  AlertCircle,
  RefreshCw,
  Settings,
  Tag,
  Server,
} from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * B-028: левый сайдбар — единственная главная навигация (вместо ленты из 13 вкладок).
 * Значения nav совпадают с MAIN_NAV в AiBizOsHumanUI, роутинг контента не менялся.
 */
const NAV_GROUPS = [
  {
    label: "Работа",
    items: [
      { value: "ops", label: "Сегодня", icon: Home },
      { value: "drafts", label: "Ревью писем", icon: Mail },
      { value: "runs", label: "Проекты", icon: Megaphone },
    ],
  },
  {
    label: "Данные",
    items: [
      { value: "companies", label: "Компании", icon: Building2 },
      { value: "contacts", label: "Контакты", icon: Users },
    ],
  },
  {
    label: "Переписка",
    items: [
      { value: "threads", label: "Треды", icon: MessagesSquare },
      { value: "reply-drafts", label: "Ответы", icon: Reply },
      { value: "reminders", label: "Напоминания", icon: Bell },
    ],
  },
  {
    label: "Служебное",
    items: [
      { value: "dead", label: "Мёртвые ящики", icon: AlertCircle },
      { value: "queue", label: "Очередь до-ресёрча", icon: RefreshCw },
    ],
  },
];

export default function AppSidebar({
  nav,
  onNavigate,
  version,
  counts = {},
  onOpenSettings,
  onOpenOffers,
  onOpenSmtp,
}) {
  const settingsItems = [
    { label: "Интеграции и ключи", icon: Settings, onClick: onOpenSettings },
    { label: "Офферы", icon: Tag, onClick: onOpenOffers },
    { label: "SMTP-ящики", icon: Server, onClick: onOpenSmtp },
  ].filter((x) => x.onClick);
  return (
    <aside className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col overflow-y-auto border-r border-border bg-sidebar px-3 py-4 md:flex">
      <div className="mb-2 flex items-center gap-2 px-2">
        <span className="grid h-6 w-6 shrink-0 place-items-center rounded-md bg-primary text-[11px] font-bold text-primary-foreground">
          AS
        </span>
        <span className="truncate text-[13px] font-semibold">AlexStaff · Аутрич</span>
        {version ? (
          <span className="ml-auto shrink-0 text-[10px] tabular-nums text-muted-foreground">v{version}</span>
        ) : null}
      </div>
      {/* Настройки прижаты к низу: конфигурация (ключи, офферы, ящики) — не ежедневная работа */}
      {settingsItems.length > 0 ? (
        <div className="order-last mt-auto flex flex-col gap-0.5 border-t border-border pt-2">
          <div className="px-2 pb-1 pt-1 text-[10.5px] font-semibold uppercase tracking-wider text-muted-foreground">
            Настройки
          </div>
          {settingsItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.label}
                type="button"
                onClick={item.onClick}
                className="flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              >
                <Icon className="h-[15px] w-[15px] shrink-0" aria-hidden />
                {item.label}
              </button>
            );
          })}
        </div>
      ) : null}
      {NAV_GROUPS.map((group) => (
        <div key={group.label}>
          <div className="px-2 pb-1 pt-4 text-[10.5px] font-semibold uppercase tracking-wider text-muted-foreground">
            {group.label}
          </div>
          <div className="flex flex-col gap-0.5">
            {group.items.map((item) => {
              const Icon = item.icon;
              const active = nav === item.value;
              const count = counts[item.value];
              return (
                <button
                  key={item.value}
                  type="button"
                  onClick={() => onNavigate(item.value)}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] font-medium transition-colors",
                    active
                      ? "bg-accent text-accent-foreground"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground",
                  )}
                >
                  <Icon className="h-[15px] w-[15px] shrink-0" aria-hidden />
                  <span className="min-w-0 truncate">{item.label}</span>
                  {count > 0 ? (
                    <span
                      className={cn(
                        "ml-auto rounded-full px-1.5 text-[11px] font-semibold tabular-nums leading-[18px]",
                        active ? "bg-primary/15 text-accent-foreground" : "bg-neutral-soft text-neutral",
                      )}
                    >
                      {count}
                    </span>
                  ) : null}
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </aside>
  );
}
