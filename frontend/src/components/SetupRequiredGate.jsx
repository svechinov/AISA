import React, { useCallback, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ChevronDown, ChevronUp, Download, Loader2, RefreshCw } from "lucide-react";

const ENV_API = import.meta.env.VITE_API_BASE?.trim();
const API_BASE =
  ENV_API && ENV_API.length > 0
    ? ENV_API.replace(/\/$/, "")
    : import.meta.env.DEV
      ? "/api"
      : "http://127.0.0.1:8000";

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

function buildEnvSnippet(llmRows, cdnProvider, cdnKey) {
  const priority = llmRows.filter((r) => r.apiKey.trim()).map((r) => r.id);
  const lines = [
    "# AI Biz OS — paste into backend/.env (never commit this file)",
    `LLM_PROVIDER_PRIORITY=${priority.join(",")}`,
  ];
  for (const row of llmRows) {
    const envMap = {
      claude: "ANTHROPIC_API_KEY",
      openai: "OPENAI_API_KEY",
      perplexity: "PERPLEXITY_API_KEY",
      grok: "XAI_API_KEY",
    };
    lines.push(`${envMap[row.id]}=${row.apiKey.trim()}`);
  }
  lines.push(`CDN_PROVIDER=${cdnProvider}`);
  lines.push(`CDN_API_KEY=${cdnKey.trim()}`);
  return `${lines.join("\n")}\n`;
}

/**
 * Blocks the app until LLM + CDN integration keys are present (reported by GET /setup/status).
 * Saves via POST /setup/bootstrap only when the server allows it; always offers a downloadable .env snippet.
 */
export default function SetupRequiredGate({ children }) {
  const [status, setStatus] = useState(null);
  const [loadErr, setLoadErr] = useState("");
  const [submitErr, setSubmitErr] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [checking, setChecking] = useState(false);

  const [llmRows, setLlmRows] = useState(() =>
    LLM_DEFS.map((d) => ({ id: d.id, label: d.label, apiKey: "" })),
  );
  const [cdnProvider, setCdnProvider] = useState("cloudflare");
  const [cdnKey, setCdnKey] = useState("");

  const refresh = useCallback(async () => {
    setLoadErr("");
    setChecking(true);
    try {
      const res = await fetch(`${API_BASE}/setup/status`, {
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      if (!res.ok) throw new Error(`Status ${res.status}`);
      setStatus(await res.json());
    } catch (e) {
      setLoadErr(String(e?.message || e));
      setStatus(null);
    } finally {
      setChecking(false);
    }
  }, []);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  const ready = status?.llm_configured && status?.cdn_configured;

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

  if (ready) return children;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-background p-4">
      <div className="flex max-h-[92vh] w-full max-w-lg flex-col overflow-y-auto overflow-x-hidden rounded-2xl border-2 border-border bg-card shadow-lg">
        <div className="shrink-0 border-b border-border px-5 py-4">
          <h1 className="text-lg font-semibold leading-tight">Configuration required</h1>
          <p className="mt-1 text-xs text-muted-foreground">
            API keys stay on the server or in your local <code className="text-[11px]">backend/.env</code> only —
            never commit secrets. First time: copy <code className="text-[11px]">backend/.env.example</code> to{' '}
            <code className="text-[11px]">backend/.env</code> so the API can allow saving from this screen (see{' '}
            <code className="text-[11px]">ALLOW_SETUP_ENV_WRITE</code>).
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
            {loadErr ? (
              <p className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-destructive">
                Could not reach the API ({loadErr}). Fix the backend URL or start the server, then reload. You can
                still use <strong>Download .env snippet</strong> below.
              </p>
            ) : null}

            <section className="space-y-3">
              <h2 className="text-sm font-medium">1. Large language models</h2>
              <p className="text-xs text-muted-foreground">
                To continue, configure at least one API key for the providers you use. Use the arrows to set
                priority (top = highest). Empty keys are skipped.
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
                To continue, choose one provider and paste its API key (or the main credential your deployment
                uses; you may need additional variables per vendor in <code className="text-[11px]">.env</code>).
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
                The server does not allow writing <code className="text-[11px]">.env</code> from the browser
                (<code className="text-[11px]">ALLOW_SETUP_ENV_WRITE</code> is off or{' '}
                <code className="text-[11px]">APP_ENV=production</code>). Use <strong>Download .env snippet</strong>,
                merge into <code className="text-[11px]">backend/.env</code>, restart the API, and reload.
              </p>
            ) : null}

            <details className="rounded-lg border border-border text-xs">
              <summary className="cursor-pointer px-3 py-2 font-medium">Preview .env fragment</summary>
              <pre className="max-h-32 overflow-auto border-t border-border bg-muted/30 p-3 whitespace-pre-wrap">
                {snippetPreview}
              </pre>
            </details>
          </div>
        </ScrollArea>

        <div className="sticky bottom-0 z-10 flex shrink-0 flex-col gap-2 border-t border-border bg-card px-5 py-4 sm:flex-row sm:flex-wrap sm:justify-end">
          <Button type="button" variant="outline" onClick={downloadSnippet} className="gap-2">
            <Download className="h-4 w-4" />
            Download .env snippet
          </Button>
          {canTryServerSave ? (
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
