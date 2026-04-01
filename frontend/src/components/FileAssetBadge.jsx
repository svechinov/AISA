import { Badge } from "@/components/ui/badge";
import { assetIsLikelyMimeAttachment } from "@/lib/assetCdn";
import { cn } from "@/lib/utils";

/** Green «file» badge when the asset is expected to attach as MIME (not link-only). */
export function FileAssetBadge({ asset, className }) {
  if (!assetIsLikelyMimeAttachment(asset)) return null;
  return (
    <Badge
      className={cn(
        "shrink-0 border-transparent bg-green-600 text-xs font-normal text-white hover:bg-green-600 dark:bg-green-600 dark:hover:bg-green-600",
        className,
      )}
      title="Sends as a file attachment when possible (not link-only)"
    >
      file
    </Badge>
  );
}
