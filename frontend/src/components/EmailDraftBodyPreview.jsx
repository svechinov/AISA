import { useMemo } from "react";
import DOMPurify from "dompurify";
import { isProbablyHtmlEmailBody } from "@/lib/emailDraftBody";

const signaturePlaceholder = (
  <div className="mt-2 w-full border-t border-dashed border-border/60 pt-2">
    <span className="block font-mono text-sm leading-6 text-muted-foreground">[Signature]</span>
  </div>
);

export function EmailDraftBodyPreview({ body, showSignaturePlaceholder = false }) {
  const safeHtml = useMemo(() => {
    const s = body ?? "";
    if (!s.trim()) return null;
    if (!isProbablyHtmlEmailBody(s)) return null;
    return DOMPurify.sanitize(s, {
      USE_PROFILES: { html: true },
      ADD_ATTR: ["target", "rel"],
    });
  }, [body]);

  if (safeHtml) {
    return (
      <>
        <div
          className="email-draft-html-preview rounded-2xl bg-muted/50 p-4 text-sm leading-6 [&_a]:break-all [&_a]:text-primary [&_a]:underline"
          dangerouslySetInnerHTML={{ __html: safeHtml }}
        />
        {showSignaturePlaceholder ? signaturePlaceholder : null}
      </>
    );
  }

  return (
    <>
      <div className="rounded-2xl bg-muted/50 p-4 text-sm leading-6 whitespace-pre-wrap">{body ?? ""}</div>
      {showSignaturePlaceholder ? signaturePlaceholder : null}
    </>
  );
}
