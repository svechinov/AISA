import { useMemo } from "react";
import DOMPurify from "dompurify";
import { isProbablyHtmlEmailBody } from "@/lib/emailDraftBody";

export function EmailDraftBodyPreview({ body }) {
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
      <div
        className="email-draft-html-preview rounded-2xl bg-muted/50 p-4 text-sm leading-6 [&_a]:break-all [&_a]:text-primary [&_a]:underline"
        dangerouslySetInnerHTML={{ __html: safeHtml }}
      />
    );
  }

  return (
    <div className="rounded-2xl bg-muted/50 p-4 text-sm leading-6 whitespace-pre-wrap">{body ?? ""}</div>
  );
}
