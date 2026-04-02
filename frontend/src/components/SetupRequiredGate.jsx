import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Check, ChevronDown, ChevronUp, Download, Loader2, RefreshCw } from "lucide-react";

const ENV_API = import.meta.env.VITE_API_BASE?.trim();
const API_BASE =
  ENV_API && ENV_API.length > 0
    ? ENV_API.replace(/\/$/, "")
    : import.meta.env.DEV
      ? "/api"
      : "http://127.0.0.1:8000";

const SETUP_STATUS_TIMEOUT_MS = 25000;
const VERIFY_STAGGER_MS = 380;

async function fetchJsonWithTimeout(url, init, timeoutMs) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: ctrl.signal });
  } finally {
    clearTimeout(timer);
  }
}

const LLM_DEFS = [
  { id: "claude", label: "Claude (Anthropic)" },
  { id: "openai", label: "ChatGPT (OpenAI)" },
  { id: "perplexity", label: "Perplexity" },
  { id: "grok", label: "Grok (xAI)" },
];

const CDN_OPTIONS = [
  { id: "cloudflare", label: "Cloudflare" },
  { id: "akamai", label: "Akamai" },
  { id: "cloudfront", label: "Amazon CloudFront" },
  { id: "gcp_cdn", label: "Google Cloud CDN" },
];

const MASK_PLACEHOLDER = "••••••••";

function buildEnvSnippet(llmRows, cdnProvider, cdnKey) {
  const priority = llmRows.filter((r) => r.apiKey.trim()).map((r) => r.id);
  const keyById = Object.fromEntries(llmRows.map((r) => [r.id, r.apiKey.trim()]));

  const lines = [
    "# AI Biz OS — paste into backend/.env (never commit this file)",
    "ALLOW_SETUP_ENV_WRITE=true",
    "",
    `LLM_PROVIDER_PRIORITY=${priority.join(",")}`,
    `ANTHROPIC_API_KEY=${keyById.claude ?? ""}`,
    `OPENAI_API_KEY=${keyById.openai ?? ""}`,
    `PERPLEXITY_API_KEY=${keyById.perplexity ?? ""}`,
    `XAI_API_KEY=${keyById.grok ?? ""}`,
    "",
    `CDN_PROVIDER=${cdnProvider}`,
    `CDN_API_KEY=${cdnKey.trim()}`,
    "CDN_R2_BUCKET=",
    "CDN_ACCOUNT_ID=",
    "CDN_R2_ACCESS_KEY_ID=",
    "CDN_R2_SECRET_ACCESS_KEY=",
    "CDN_R2_PUBLIC_BASE_URL=",
    "",
    "GOOGLE_CLIENT_ID=",
    "GOOGLE_CLIENT_SECRET=",
    "GOOGLE_REFRESH_TOKEN=",
    "GMAIL_SEND_AS_EMAIL=",
  ];
  return `${lines.join("\n")}\n`;
}

function labelForLlm(id) {
  return LLM_DEFS.find((d) => d.id === id)?.label ?? id;
}

function labelForCdn(providerId) {
  const p = (providerId || "").trim().toLowerCase();
  return CDN_OPTIONS.find((o) => o.id === p)?.label ?? (p || "CDN");
}

/**
 * Blocks the app until GET /setup/status reports llm_configured && cdn_configured.
 * After a successful status: masked rows for secrets in .env, then green checks one-by-one; only configured LLM slots are listed.
 */
export default function SetupRequiredGate({ children }) {
  const [status, setStatus] = useState(null);
  const [loadErr, setLoadErr] = useState("");
  const [submitErr, setSubmitErr] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [checking, setChecking] = useState(false);
  /** How many checklist rows have shown the green check (after API success). */
  const [verifyCount, setVerifyCount] = useState(0);
  const [verificationDone, setVerificationDone] = useState(false);

  const [llmRows, setLlmRows] = useState(() =>
    LLM_DEFS.map((d) => ({ id: d.id, label: d.label, apiKey: "" })),
  );
  const [cdnProvider, setCdnProvider] = useState("cloudflare");
  const [cdnKey, setCdnKey] = useState("");

  const refresh = useCallback(async () => {
    setLoadErr("");
    setChecking(true);
    setVerifyCount(0);
    setVerificationDone(false);
    try {
      const res = await fetchJsonWithTimeout(
        `${API_BASE}/setup/status`,
        {
          cache: "no-store",
          headers: { Accept: "application/json" },
        },
        SETUP_STATUS_TIMEOUT_MS,
      );
      if (!res.ok) throw new Error(`Status ${res.status}`);
      setStatus(await res.json());
    } catch (e) {
      const name = e?.name;
      const msg =
        name === "AbortError"
          ? `Timed out after ${SETUP_STATUS_TIMEOUT_MS / 1000}s — API may still be starting. Re-check.`
          : String(e?.message || e);
      setLoadErr(msg);
      setStatus(null);
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const integrationReady = Boolean(status?.llm_configured && status?.cdn_configured);

  /** LLM rows listed on the checklist: only providers that have keys, or all four when none (setup mode). */
  const checklistLlmIds = useMemo(() => {
    const ready = Array.isArray(status?.llm_providers_ready) ? status.llm_providers_ready : [];
    if (ready.length > 0) return ready.map((x) => String(x).toLowerCase());
    return LLM_DEFS.map((d) => d.id);
  }, [status]);

  const verifyTotal = useMemo(() => {
    if (!integrationReady) return 0;
    const nLlm = Array.isArray(status?.llm_providers_ready) ? status.llm_providers_ready.length : 0;
    return nLlm + 1;
  }, [integrationReady, status?.llm_providers_ready]);

  useEffect(() => {
    if (!status || !integrationReady || verifyTotal === 0) {
      setVerifyCount(0);
      setVerificationDone(false);
      return;
    }
    setVerifyCount(0);
    setVerificationDone(false);
    let i = 0;
    const t = setInterval(() => {
      i += 1;
      setVerifyCount(i);
      if (i >= verifyTotal) {
        clearInterval(t);
        setVerificationDone(true);
      }
    }, VERIFY_STAGGER_MS);
    return () => clearInterval(t);
  }, [status, integrationReady, verifyTotal]);

  const canEnterApp = integrationReady && verificationDone;

  const moveLlm = (index, dir) => {
    setLlmRows((prev) => {
      const j = index + dir;
      if (j < 0 || j >= prev.length) return prev;
      const next = [...prev];
      [next[index], next[j]] = [next[j], next[index]];
      return next;
    });
  };

  const downloadSnippet = () => {
    const text = buildEnvSnippet(llmRows, cdnProvider, cdnKey);
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "ai-biz-os-integration.env";
    a.click();
    URL.revokeObjectURL(url);
  };

  const submit = async () => {
    setSubmitErr("");
    setSubmitting(true);
    try {
      const res = await fetch(`${API_BASE}/setup/bootstrap`, {
        method: "POST",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          llm_rows: llmRows.map((r) => ({ provider: r.id, api_key: r.apiKey })),
          cdn_provider: cdnProvider,
          cdn_api_key: cdnKey,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || res.status));
      }
      window.location.reload();
    } catch (e) {
      setSubmitErr(String(e?.message || e));
    } finally {
      setSubmitting(false);
    }
  };

  const canTryServerSave = status?.allow_env_write;
  const snippetPreview = useMemo(
    () => buildEnvSnippet(llmRows, cdnProvider, cdnKey),
    [llmRows, cdnProvider, cdnKey],
  );

  if (canEnterApp) return children;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-background p-4">
      <div className="flex max-h-[92vh] w-full max-w-lg flex-col overflow-y-auto overflow-x-hidden rounded-2xl border-2 border-border bg-card shadow-lg">
        <div className="shrink-0 border-b border-border px-5 py-4">
          <h1 className="text-lg font-semibold leading-tight">Configuration required</h1>
          <p className="mt-1 text-xs text-muted-foreground">
            The app opens after the API confirms LLM and CDN keys in <code className="text-[11px]">backend/.env</code>.
            Entries already on the server show as masked; green checks appear line by line after the status response.
          </p>
          {status && !loadErr ? (
            <div className="mt-2 space-y-2 text-xs text-muted-foreground" aria-live="polite">
              <p>
                Status: LLM {status.llm_configured ? "ready" : "missing"} · CDN{" "}
                {status.cdn_configured ? "ready" : "missing"}
                {status.allow_env_write ? "" : " · server save disabled"}
              </p>
              {status.env_paths_found?.length ? (
                <p className="break-all">
                  <span className="font-medium text-foreground">Env files: </span>
                  {status.env_paths_found.join(" → ")}
                </p>
              ) : null}
              {status.hints?.length ? (
                <ul className="list-inside list-disc space-y-1 text-foreground/90">
                  {status.hints.map((h, i) => (
                    <li key={i}>{h}</li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
        </div>

        <ScrollArea className="px-5">
          <div className="space-y-6 py-4 text-sm">
            {/* Checklist: verification progress */}
            {status && !loadErr ? (
              <section className="space-y-3 rounded-xl border border-border bg-muted/15 p-3">
                <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Integration check
                </h2>
                <ul className="space-y-2">
                  {checklistLlmIds.map((pid, idx) => {
                    const hasKey = Boolean(status?.llm_providers_ready?.some((x) => String(x).toLowerCase() === pid));
                    const showMask = hasKey;
                    const showInput = !hasKey && status.llm_providers_ready?.length === 0;
                    const ticked = integrationReady && idx < verifyCount;

                    return (
                      <li
                        key={pid}
                        className="flex items-center gap-2 rounded-lg border border-border/80 bg-card px-3 py-2"
                      >
                        <div className="min-w-0 flex-1">
                          <div className="text-xs font-medium">{labelForLlm(pid)}</div>
                          {checking ? (
                            <div className="mt-1 h-9 w-full animate-pulse rounded-md bg-muted/60" />
                          ) : showMask ? (
                            <Input
                              readOnly
                              className="mt-1 h-9 font-mono text-xs"
                              type="text"
                              value={MASK_PLACEHOLDER}
                              aria-label={`${labelForLlm(pid)}: key present`}
                            />
                          ) : showInput ? (
                            <p className="mt-1 text-[11px] text-muted-foreground">Enter a key below or in .env</p>
                          ) : null}
                        </div>
                        <div className="flex h-9 w-9 shrink-0 items-center justify-center">
                          {checking ? (
                            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-hidden />
                          ) : integrationReady && ticked ? (
                            <Check className="h-5 w-5 text-green-600 dark:text-green-500" strokeWidth={2.5} aria-label="OK" />
                          ) : integrationReady && hasKey && !ticked ? (
                            <span className="text-muted-foreground" aria-hidden>
                              …
                            </span>
                          ) : !integrationReady && hasKey ? (
                            <Check className="h-5 w-5 text-green-600/70 dark:text-green-500/70" strokeWidth={2.5} aria-label="Key present" />
                          ) : null}
                        </div>
                      </li>
                    );
                  })}

                  {/* CDN row */}
                  <li className="flex items-center gap-2 rounded-lg border border-border/80 bg-card px-3 py-2">
                    <div className="min-w-0 flex-1">
                      <div className="text-xs font-medium">CDN — {labelForCdn(status.cdn_provider)}</div>
                      {checking ? (
                        <div className="mt-1 h-9 w-full animate-pulse rounded-md bg-muted/60" />
                      ) : status.cdn_configured ? (
                        <Input
                          readOnly
                          className="mt-1 h-9 font-mono text-xs"
                          type="text"
                          value={MASK_PLACEHOLDER}
                          aria-label="CDN key present"
                        />
                      ) : (
                        <p className="mt-1 text-[11px] text-muted-foreground">Set CDN provider and key below</p>
                      )}
                    </div>
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center">
                      {checking ? (
                        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-hidden />
                      ) : integrationReady && status.cdn_configured && verifyCount > checklistLlmIds.length ? (
                        <Check className="h-5 w-5 text-green-600 dark:text-green-500" strokeWidth={2.5} aria-label="OK" />
                      ) : integrationReady && status.cdn_configured ? (
                        <span className="text-muted-foreground" aria-hidden>
                          …
                        </span>
                      ) : !integrationReady && status.cdn_configured ? (
                        <Check className="h-5 w-5 text-green-600/70 dark:text-green-500/70" strokeWidth={2.5} aria-label="CDN key present" />
                      ) : null}
                    </div>
                  </li>
                </ul>
                {integrationReady && !verificationDone ? (
                  <p className="text-[11px] text-muted-foreground">Confirming each line…</p>
                ) : null}
              </section>
            ) : null}

            {loadErr ? (
              <p className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-destructive">
                Could not reach the API ({loadErr}). Fix the backend URL or start the server, then Re-check.
              </p>
            ) : null}

            {/* Setup form when incomplete */}
            {status && (!status.llm_configured || !status.cdn_configured) ? (
              <>
                <section className="space-y-3">
                  <h2 className="text-sm font-medium">1. Large language models</h2>
                  <p className="text-xs text-muted-foreground">
                    At least one API key required. Order = priority (top first). Empty rows are skipped on save.
                  </p>
                  <ul className="space-y-2">
                    {llmRows.map((row, i) => (
                      <li
                        key={row.id}
                        className="flex flex-col gap-2 rounded-xl border border-border bg-muted/20 p-3 sm:flex-row sm:items-center"
                      >
                        <div className="min-w-0 flex-1 space-y-1">
                          <div className="text-xs font-medium">{row.label}</div>
                          <Input
                            type="password"
                            autoComplete="off"
                            placeholder="API key (optional for each)"
                            value={row.apiKey}
                            onChange={(e) => {
                              const v = e.target.value;
                              setLlmRows((prev) => prev.map((r) => (r.id === row.id ? { ...r, apiKey: v } : r)));
                            }}
                          />
                        </div>
                        <div className="flex shrink-0 gap-1 self-end sm:self-center">
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            className="h-8 w-8 p-0"
                            disabled={i === 0}
                            onClick={() => moveLlm(i, -1)}
                            aria-label="Move up"
                          >
                            <ChevronUp className="h-4 w-4" />
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            className="h-8 w-8 p-0"
                            disabled={i === llmRows.length - 1}
                            onClick={() => moveLlm(i, 1)}
                            aria-label="Move down"
                          >
                            <ChevronDown className="h-4 w-4" />
                          </Button>
                        </div>
                      </li>
                    ))}
                  </ul>
                </section>

                <section className="space-y-3">
                  <h2 className="text-sm font-medium">2. CDN / edge storage</h2>
                  <p className="text-xs text-muted-foreground">
                    Provider and API key (see <code className="text-[11px]">backend/.env.example</code> for R2 fields).
                  </p>
                  <div className="space-y-2 rounded-xl border border-border bg-muted/20 p-3">
                    {CDN_OPTIONS.map((opt) => (
                      <label key={opt.id} className="flex cursor-pointer items-center gap-2 text-xs">
                        <input
                          type="radio"
                          name="cdn"
                          className="h-3.5 w-3.5 accent-primary"
                          checked={cdnProvider === opt.id}
                          onChange={() => setCdnProvider(opt.id)}
                        />
                        <span>{opt.label}</span>
                      </label>
                    ))}
                    <Input
                      type="password"
                      autoComplete="off"
                      className="mt-2"
                      placeholder="CDN / storage API key"
                      value={cdnKey}
                      onChange={(e) => setCdnKey(e.target.value)}
                    />
                  </div>
                </section>

                {submitErr ? (
                  <p className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                    {submitErr}
                  </p>
                ) : null}

                {status && !status.allow_env_write ? (
                  <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-950 dark:text-amber-100">
                    Server save is off (<code className="text-[11px]">ALLOW_SETUP_ENV_WRITE</code> /{" "}
                    <code className="text-[11px]">APP_ENV</code>). Use <strong>Download .env snippet</strong>, merge into{" "}
                    <code className="text-[11px]">backend/.env</code>, restart the API, reload.
                  </p>
                ) : null}

                <details className="rounded-lg border border-border text-xs">
                  <summary className="cursor-pointer px-3 py-2 font-medium">Preview .env fragment</summary>
                  <pre className="max-h-32 overflow-auto border-t border-border bg-muted/30 p-3 whitespace-pre-wrap">
                    {snippetPreview}
                  </pre>
                </details>
              </>
            ) : null}
          </div>
        </ScrollArea>

        <div className="sticky bottom-0 z-10 flex shrink-0 flex-col gap-2 border-t border-border bg-card px-5 py-4 sm:flex-row sm:flex-wrap sm:justify-end">
          <Button type="button" variant="outline" onClick={downloadSnippet} className="gap-2">
            <Download className="h-4 w-4" />
            Download .env snippet
          </Button>
          {canTryServerSave && status && (!status.llm_configured || !status.cdn_configured) ? (
            <Button
              type="button"
              disabled={submitting || checking}
              onClick={() => void submit()}
              className="gap-2"
            >
              {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Save and reload
            </Button>
          ) : null}
          <Button
            type="button"
            variant="secondary"
            disabled={checking}
            onClick={() => void refresh()}
            className="gap-2"
          >
            {checking ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            Re-check status
          </Button>
        </div>
      </div>
    </div>
  );
}
