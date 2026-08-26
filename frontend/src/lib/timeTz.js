// B-016: время оператору показываем в таймзоне политики отправки (Никосия), не в UTC браузера.

export const DEFAULT_TZ = "Asia/Nicosia";

/** API отдаёт наивные UTC-таймстампы (без Z) — без нормализации Date() читает их как локальные. */
export function parseUtcIso(iso) {
  if (!iso) return null;
  const s = String(iso);
  const hasZone = /Z$|[+-]\d{2}:?\d{2}$/.test(s);
  const d = new Date(hasZone ? s : `${s}Z`);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** «пт, 10 июл., 15:40» в заданной таймзоне. */
export function fmtInTz(iso, tz = DEFAULT_TZ, opts = {}) {
  const d = parseUtcIso(iso);
  if (!d) return "—";
  return d.toLocaleString("ru-RU", {
    timeZone: tz,
    weekday: "short",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    ...opts,
  });
}

/** «10 июл.» — только дата, без времени, в заданной таймзоне. */
export function fmtDateInTz(iso, tz = DEFAULT_TZ) {
  const d = parseUtcIso(iso);
  if (!d) return "—";
  return d.toLocaleString("ru-RU", {
    timeZone: tz,
    day: "2-digit",
    month: "short",
  });
}
