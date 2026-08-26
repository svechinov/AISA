/** Фаза кампании (display_phase бэкенда) → русский статус-чип (B-028). */
export const RUN_PHASE_CHIP = {
  Preparing: { label: "готовится", variant: "info" },
  Ready: { label: "черновики готовы", variant: "warning" },
  Active: { label: "идёт отправка", variant: "success" },
  Closed: { label: "закрыта", variant: "neutral" },
};
