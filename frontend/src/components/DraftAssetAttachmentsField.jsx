import { useCallback, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { FileAssetBadge } from "@/components/FileAssetBadge";
import { Layers, Paperclip, X } from "lucide-react";
import { t } from "@/lib/i18n";

/** Normalize API JSON list to unique ints (order preserved). */
export function normalizeAttachedAssetIds(raw) {
  if (!Array.isArray(raw)) return [];
  const seen = new Set();
  const out = [];
  for (const x of raw) {
    const n = Number(x);
    if (!Number.isFinite(n) || seen.has(n)) continue;
    seen.add(n);
    out.push(n);
  }
  return out;
}

/** Extract ordered unique asset ids from a packet row (API shape). */
export function assetIdsFromPacket(packet) {
  const inner = Array.isArray(packet?.assets)
    ? packet.assets
    : Array.isArray(packet?.packet_json?.assets)
      ? packet.packet_json.assets
      : [];
  const out = [];
  const seen = new Set();
  for (const row of inner) {
    if (!row || row.asset_id == null) continue;
    const n = Number(row.asset_id);
    if (!Number.isFinite(n) || seen.has(n)) continue;
    seen.add(n);
    out.push(n);
  }
  return out;
}

function mergeIds(existing, additions) {
  const seen = new Set(existing);
  const next = [...existing];
  for (const n of additions) {
    if (!Number.isFinite(n) || seen.has(n)) continue;
    seen.add(n);
    next.push(n);
  }
  return next;
}

/**
 * Pick Assets from the library and/or merge presets from run Packets into attached_asset_ids.
 */
export function DraftAssetAttachmentsField({
  assets,
  selectedIds,
  onSelectedIdsChange,
  assetPackets = null,
}) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const [packetsOpen, setPacketsOpen] = useState(false);

  const byId = useMemo(() => new Map(assets.map((a) => [a.id, a])), [assets]);

  const usablePackets = useMemo(() => {
    if (!Array.isArray(assetPackets) || !assetPackets.length) return [];
    return assetPackets.filter((p) => p.status !== "archived");
  }, [assetPackets]);

  const toggle = useCallback(
    (id) => {
      const n = Number(id);
      if (!Number.isFinite(n)) return;
      if (selectedIds.includes(n)) {
        onSelectedIdsChange(selectedIds.filter((x) => x !== n));
      } else {
        onSelectedIdsChange([...selectedIds, n]);
      }
    },
    [selectedIds, onSelectedIdsChange],
  );

  const remove = useCallback(
    (id) => {
      onSelectedIdsChange(selectedIds.filter((x) => x !== id));
    },
    [selectedIds, onSelectedIdsChange],
  );

  const mergePacket = useCallback(
    (packet) => {
      const add = assetIdsFromPacket(packet);
      onSelectedIdsChange(mergeIds(selectedIds, add));
    },
    [selectedIds, onSelectedIdsChange],
  );

  const sortedList = useMemo(() => [...assets].sort((a, b) => a.id - b.id), [assets]);

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="gap-1"
          onClick={() => setPickerOpen((o) => !o)}
          aria-expanded={pickerOpen}
          title={t("Attach assets from library")}
        >
          <Paperclip className="h-3.5 w-3.5" aria-hidden />
          {t("Assets")}
        </Button>
        {usablePackets.length ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="gap-1"
            onClick={() => setPacketsOpen((o) => !o)}
            aria-expanded={packetsOpen}
            title={t("Add all assets from a saved packet preset")}
          >
            <Layers className="h-3.5 w-3.5" aria-hidden />
            {t("Packets")}
          </Button>
        ) : null}
      </div>
      {pickerOpen ? (
        <div className="max-h-52 overflow-y-auto rounded-xl border-2 border-border bg-muted/20 p-2">
          {sortedList.length ? (
            <ul className="space-y-1">
              {sortedList.map((a) => (
                <li key={a.id}>
                  <label className="flex cursor-pointer items-start gap-2 rounded-lg px-2 py-1.5 hover:bg-muted/50">
                    <input
                      type="checkbox"
                      className="mt-1 shrink-0"
                      checked={selectedIds.includes(a.id)}
                      onChange={() => toggle(a.id)}
                    />
                    <span className="min-w-0 flex-1 text-sm">
                      <span className="font-medium">{a.name || `${t("Asset")} #${a.id}`}</span>
                      <span className="ml-2 text-xs text-muted-foreground">#{a.id}</span>
                      {a.asset_type ? (
                        <Badge variant="outline" className="ml-2 align-middle text-xs font-normal">
                          {a.asset_type}
                        </Badge>
                      ) : null}
                      <FileAssetBadge asset={a} className="ml-2 align-middle" />
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          ) : (
            <p className="px-2 py-3 text-sm text-muted-foreground">{t("No assets in library yet.")}</p>
          )}
        </div>
      ) : null}
      {packetsOpen && usablePackets.length ? (
        <div className="max-h-52 overflow-y-auto rounded-xl border-2 border-border bg-muted/20 p-2">
          <ul className="space-y-1">
            {usablePackets.map((p) => {
              const n = assetIdsFromPacket(p).length;
              return (
                <li
                  key={p.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/60 bg-background/80 px-2 py-2"
                >
                  <div className="min-w-0 text-sm">
                    <span className="font-medium">{p.title || `${t("Packet")} #${p.id}`}</span>
                    <span className="ml-2 text-xs text-muted-foreground">
                      {n} {t("assets")}
                    </span>
                  </div>
                  <Button type="button" size="sm" variant="secondary" onClick={() => mergePacket(p)}>
                    {t("Add assets")}
                  </Button>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
      {selectedIds.length ? (
        <div className="flex flex-wrap gap-2 text-sm">
          {selectedIds.map((id) => (
            <span
              key={id}
              className="inline-flex items-center gap-1 rounded-md border border-border bg-muted/30 px-2 py-0.5 font-mono text-xs text-foreground"
              title={byId.get(id)?.name || undefined}
            >
              [{t("Asset")} #{id}]
              <FileAssetBadge asset={byId.get(id)} className="font-sans align-middle" />
              <button
                type="button"
                className="rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                aria-label={`Remove asset ${id}`}
                onClick={() => remove(id)}
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}
