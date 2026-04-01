/** True when asset was created via POST /assets/upload (R2 or Cloudflare Images). */
export function assetIsCdnUpload(asset) {
  const cdn = asset?.metadata_json?.cdn;
  return cdn === "cloudflare_r2" || cdn === "cloudflare_images";
}

/**
 * True when the asset likely sends as a MIME attachment (local path, download URL, storage key, or CDN upload).
 * URL-only bookmarks without a file source are false.
 */
export function assetIsLikelyMimeAttachment(asset) {
  if (!asset) return false;
  if (assetIsCdnUpload(asset)) return true;
  if (String(asset.file_path || "").trim()) return true;
  if (String(asset.download_url || "").trim()) return true;
  if (String(asset.storage_key || "").trim()) return true;
  return false;
}
