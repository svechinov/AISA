import React from "react";
import { t } from "@/lib/i18n";

/** Normalize API payload to 24 non-negative integers. */
function normalizeHourlyCounts(counts) {
  if (!Array.isArray(counts)) return Array.from({ length: 24 }, () => 0);
  return Array.from({ length: 24 }, (_, i) => {
    const n = Number(counts[i]);
    return Number.isFinite(n) && n >= 0 ? Math.floor(n) : 0;
  });
}

/**
 * Full-width bar strip: one bar per UTC hour for the last 24h (outreach + reply sends).
 * Height matched to former Run setup step tiles (~5.5rem chart area).
 */
export function RunSetupHourlySendsChart({ counts }) {
  const arr = normalizeHourlyCounts(counts);
  const max = Math.max(1, ...arr);
  const total = arr.reduce((a, b) => a + b, 0);

  return (
    <div className="w-full rounded-2xl border-2 border-border bg-card px-3 py-2 shadow-none">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-2 gap-y-1">
        <span className="text-sm font-medium leading-tight text-foreground">{t("Sends — last 24 hours")}</span>
        <span className="text-[11px] text-muted-foreground">
          {t("UTC")} · {total} {t("total")} · {t("outreach + replies")}
        </span>
      </div>
      <div
        className="flex h-[5.5rem] min-h-[5.5rem] items-end gap-px sm:gap-0.5"
        role="img"
        aria-label={`Hourly sends, 24 buckets, total ${total}`}
      >
        {arr.map((n, i) => {
          const pct = (n / max) * 100;
          const title =
            n === 0
              ? `UTC hour ${i + 1}/24 from window start: 0 sends`
              : `UTC hour ${i + 1}/24 from window start: ${n} send(s)`;
          return (
            <div key={i} className="flex h-full min-w-0 flex-1 flex-col justify-end" title={title}>
              <div
                className="w-full min-w-0 rounded-t-[3px] bg-primary/80 dark:bg-primary/70"
                style={
                  n === 0
                    ? { height: 2 }
                    : { height: `${Math.max(6, pct)}%`, minHeight: 3 }
                }
              />
            </div>
          );
        })}
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-muted-foreground">
        <span>−24h</span>
        <span>−18h</span>
        <span>−12h</span>
        <span>−6h</span>
        <span>now</span>
      </div>
    </div>
  );
}
