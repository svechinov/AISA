import { useMemo } from "react";
import DOMPurify from "dompurify";
import { isProbablyHtmlEmailBody } from "@/lib/emailDraftBody";

function trailingPreviewBlock({ showSignaturePlaceholder, attachedAssetIds }) {
  const hasSig = Boolean(showSignaturePlaceholder);
  const ids = Array.isArray(attachedAssetIds) ? attachedAssetIds : [];
  const hasAssets = ids.length > 0;
  if (!hasSig && !hasAssets) return null;
  return (
    <div className="mt-2 w-full border-t border-dashed border-border/60 pt-2">
      {hasSig ? (
        <span className="block font-mono text-sm leading-6 text-muted-foreground">[Signature]</span>
      ) : null}
      {hasAssets ? (
        <div
          className={`flex flex-wrap gap-x-3 gap-y-1 ${hasSig ? "mt-2" : ""}`}
        >
          {ids.map((id) => (
            <span key={id} className="font-mono text-sm leading-6 text-muted-foreground">
              [Asset #{id}]
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function EmailDraftBodyPreview({
  body,
  showSignaturePlaceholder = false,
  attachedAssetIds = [],
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

  const trailing = trailingPreviewBlock({ showSignaturePlaceholder, attachedAssetIds });

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
