import { useMemo } from "react";
import DOMPurify from "dompurify";
import { FileAssetBadge } from "@/components/FileAssetBadge";
import { isProbablyHtmlEmailBody } from "@/lib/emailDraftBody";
import { t } from "@/lib/i18n";

function primaryAssetHref(asset) {
  if (!asset) return "";
  const u = (asset.url || "").trim();
  if (u) return u;
  return (asset.download_url || "").trim();
}

function assetLabelsForPreview(attachedAssetIds, assetLibrary) {
  const ids = Array.isArray(attachedAssetIds) ? attachedAssetIds : [];
  const lib = Array.isArray(assetLibrary) ? assetLibrary : [];
  const byId = new Map(lib.filter((a) => a && a.id != null).map((a) => [a.id, a]));
  return ids.map((id) => {
    const a = byId.get(id);
    const name = (a?.name || "").trim();
    const href = primaryAssetHref(a);
    return { id, label: name || `${t("Asset")} #${id}`, href, asset: a };
  });
}

function trailingPreviewBlock({ showSignaturePlaceholder, attachedAssetIds, assetLibrary }) {
  const hasSig = Boolean(showSignaturePlaceholder);
  const assetItems = assetLabelsForPreview(attachedAssetIds, assetLibrary);
  const hasAssets = assetItems.length > 0;
  if (!hasSig && !hasAssets) return null;
  return (
    <div className="mt-2 w-full space-y-0 text-sm leading-6 text-foreground">
      {hasAssets ? (
        <div className="space-y-2">
          <div className="border-t border-border/60" />
          <p className="m-0 font-semibold">{t("Additional assets")}</p>
          <ul className="m-0 mb-0 list-disc space-y-0.5 pl-5">
            {assetItems.map(({ id, label, href, asset }) => (
              <li key={id} className="[&::marker]:text-foreground">
                <span className="inline-flex flex-wrap items-center gap-2 align-middle">
                  {href ? (
                    <a href={href} target="_blank" rel="noopener noreferrer" className="text-primary underline break-all">
                      {label}
                    </a>
                  ) : (
                    <span>{label}</span>
                  )}
                  <FileAssetBadge asset={asset} />
                </span>
              </li>
            ))}
          </ul>
          {!hasSig ? <div className="border-t border-border/60 pb-0.5" /> : null}
        </div>
      ) : null}
      {hasSig ? (
        <div className={hasAssets ? "mt-3 border-t border-dashed border-border/60 pt-2" : "border-t border-dashed border-border/60 pt-2"}>
          <span className="block font-mono text-muted-foreground">[{t("Signature")}]</span>
        </div>
      ) : null}
    </div>
  );
}

export function EmailDraftBodyPreview({
  body,
  showSignaturePlaceholder = false,
  attachedAssetIds = [],
  assetLibrary = [],
}) {
  const safeHtml = useMemo(() => {
    const s = body ?? "";
    if (!s.trim()) return null;
    if (!isProbablyHtmlEmailBody(s)) return null;
    return DOMPurify.sanitize(s, {
      USE_PROFILES: { html: true },
      ADD_ATTR: ["target", "rel"],
    });
  }, [body]);

  const trailing = trailingPreviewBlock({
    showSignaturePlaceholder,
    attachedAssetIds,
    assetLibrary,
  });

  if (safeHtml) {
    return (
      <>
        <div
          className="email-draft-html-preview rounded-2xl bg-muted/50 p-4 text-sm leading-6 [&_a]:break-all [&_a]:text-primary [&_a]:underline"
          dangerouslySetInnerHTML={{ __html: safeHtml }}
        />
        {trailing}
      </>
    );
  }

  return (
    <>
      <div className="rounded-2xl bg-muted/50 p-4 text-sm leading-6 whitespace-pre-wrap">{body ?? ""}</div>
      {trailing}
    </>
  );
}
