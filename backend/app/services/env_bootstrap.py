"""Write integration keys to backend .env (opt-in only) and read setup status from disk."""

from __future__ import annotations

import os
import re
from pathlib import Path


def _load_dotenv_file(path: str | os.PathLike[str] | None = None, *, override: bool = False) -> bool:
    """Load .env if python-dotenv is installed; otherwise no-op (return False)."""
    try:
        from dotenv import load_dotenv as _load
    except ModuleNotFoundError:
        return False
    if path is None:
        return bool(_load(override=override))
    return bool(_load(str(path), override=override))


def _load_env_file_manual(path: Path, *, override: bool) -> None:
    """Minimal KEY=VAL .env parser when python-dotenv is not installed."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("export "):
            s = s[7:].strip()
        if "=" not in s:
            continue
        key, _, raw = s.partition("=")
        key = key.strip()
        if not key:
            continue
        val = raw.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        if override or key not in os.environ:
            os.environ[key] = val

# Project tree (local): .../ai-biz-os/backend/app/services/env_bootstrap.py
# BACKEND_ROOT = .../backend
# Docker image: WORKDIR /app, package at /app/app → BACKEND_ROOT = /app (parent of "app" package dir is wrong!)

# __file__ = .../backend/app/services/env_bootstrap.py → parents[2] = .../backend (host) or /app (Docker)
BACKEND_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE_PATH = BACKEND_ROOT / ".env"


def safe_str_path(p: Path) -> str:
    """Avoid rare OSError from Path.resolve() (symlink loops, permission); never raises."""
    try:
        return str(p.resolve(strict=False))
    except TypeError:
        try:
            return str(p.resolve())
        except OSError:
            return str(p)
    except OSError:
        return str(p)


def _repo_dotenv_path() -> Path | None:
    """
    Monorepo-style: ai-biz-os/.env next to ai-biz-os/backend/.
    In Docker (/app only), parent is '/' — do not use /.env.
    """
    parent = BACKEND_ROOT.resolve().parent
    if parent == Path(parent.anchor):
        return None
    return parent / ".env"


def _likely_docker_single_dir_layout() -> bool:
    """e.g. WORKDIR /app in container — only /app/.env makes sense, not repo root."""
    br = BACKEND_ROOT.resolve()
    return br.parent.resolve() == Path(br.anchor)


LLM_KEY_BY_PROVIDER: dict[str, str] = {
    "claude": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "perplexity": "PERPLEXITY_API_KEY",
    "grok": "XAI_API_KEY",
    "kimi": "OLLAMA_ANTHROPIC_TOKEN",
}

VALID_LLM = frozenset(LLM_KEY_BY_PROVIDER)
VALID_CDN = frozenset({"cloudflare", "akamai", "cloudfront", "gcp_cdn"})

_DEFAULT_LLM_PRIORITY: tuple[str, ...] = ("claude", "gemini", "openai", "perplexity", "grok")


def llm_providers_ready_from_environ() -> list[str]:
    """Provider ids with a non-empty API key: LLM_PROVIDER_PRIORITY order first, then any other with a key."""
    load_env_from_file()
    raw = os.environ.get("LLM_PROVIDER_PRIORITY", "").strip()
    priority = [p.strip().lower() for p in raw.split(",") if p.strip()]
    if not priority:
        priority = list(_DEFAULT_LLM_PRIORITY)
    out: list[str] = []
    seen: set[str] = set()
    for p in priority:
        if p in VALID_LLM and os.environ.get(LLM_KEY_BY_PROVIDER[p], "").strip():
            out.append(p)
            seen.add(p)
    for p in _DEFAULT_LLM_PRIORITY:
        if p not in seen and os.environ.get(LLM_KEY_BY_PROVIDER[p], "").strip():
            out.append(p)
    return out


def cdn_provider_id_from_environ() -> str:
    """CDN_PROVIDER from env, lowercased (may be set without a valid key)."""
    load_env_from_file()
    return os.environ.get("CDN_PROVIDER", "").strip().lower()


def r2_upload_ready_from_environ() -> bool:
    """
    Cloudflare R2 upload readiness from env only (same rules as ``cdn_upload_service.r2_upload_ready``).

    Used by GET /setup/status so that endpoint never imports ``boto3`` or ``cdn_upload_service`` —
    a broken boto3 install or heavy import side effects must not block the configuration gate.
    """
    load_env_from_file()

    def _e(key: str, default: str = "") -> str:
        return (os.environ.get(key) or default).strip()

    prov = _e("CDN_PROVIDER").lower()
    secret = _e("CDN_R2_SECRET_ACCESS_KEY") or _e("CDN_API_KEY")
    return bool(
        prov == "cloudflare"
        and _e("CDN_ACCOUNT_ID")
        and _e("CDN_R2_BUCKET")
        and _e("CDN_R2_ACCESS_KEY_ID")
        and secret
        and _e("CDN_R2_PUBLIC_BASE_URL")
    )


def ordered_env_candidates() -> list[Path]:
    """
    Existing files only, in load order. Later entries override earlier for duplicate keys.
    1) AI_BIZ_OS_DOTENV if set
    2) repo-root .env (ai-biz-os/.env), never /.env
    3) backend / WORKDIR .env (backend/.env or /app/.env in Docker)
    """
    paths: list[Path] = []
    extra = os.environ.get("AI_BIZ_OS_DOTENV", "").strip()
    if extra:
        ep = Path(extra).expanduser().resolve()
        if ep.is_file():
            paths.append(ep)
    rp = _repo_dotenv_path()
    if rp is not None and rp.is_file():
        paths.append(rp)
    if ENV_FILE_PATH.is_file():
        paths.append(ENV_FILE_PATH.resolve())
    elif ENV_FILE_PATH.exists() and not ENV_FILE_PATH.is_file():
        # Docker occasionally ends up with a directory at /.env — skip, avoid read errors
        pass
    return paths


def env_files_for_pydantic() -> tuple[str, ...]:
    """Same order as runtime load_dotenv; used by Settings() at import time."""
    return tuple(str(p) for p in ordered_env_candidates())


def discover_env_files() -> list[Path]:
    return list(ordered_env_candidates())


def load_env_from_file() -> None:
    for p in ordered_env_candidates():
        try:
            if not _load_dotenv_file(p, override=True):
                _load_env_file_manual(p, override=True)
        except (OSError, UnicodeDecodeError, ValueError):
            continue


def peek_env_key_from_files(key: str) -> str:
    """
    Last non-empty assignment for `key` across ordered_env_candidates() (same precedence as loading).
    Used when os.environ is missing a value despite the file containing it (dotenv edge cases / partial reads).
    """
    want = (key or "").strip()
    if not want:
        return ""
    last: str = ""
    for path in ordered_env_candidates():
        try:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line in text.splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if s.startswith("export "):
                s = s[7:].strip()
            if "=" not in s:
                continue
            k, _, raw = s.partition("=")
            if k.strip() != want:
                continue
            val = raw.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            if val:
                last = val
    return last.strip()


def llm_configured_from_environ() -> bool:
    load_env_from_file()
    return bool(
        os.environ.get("ANTHROPIC_API_KEY", "").strip()
        or os.environ.get("GEMINI_API_KEY", "").strip()
        or os.environ.get("OPENAI_API_KEY", "").strip()
        or os.environ.get("PERPLEXITY_API_KEY", "").strip()
        or os.environ.get("XAI_API_KEY", "").strip()
    )


def cdn_configured_from_environ() -> bool:
    load_env_from_file()
    p = os.environ.get("CDN_PROVIDER", "").strip().lower()
    k = os.environ.get("CDN_API_KEY", "").strip()
    return bool(p and k and p in VALID_CDN)


def env_write_blocked_reason() -> str:
    """
    Empty string -> API may write .env (same rules as bootstrap_env_write_allowed).
    Non-empty -> human-readable reason (show in UI); OAuth persist uses this too.
    """
    load_env_from_file()
    if os.environ.get("APP_ENV", "").strip().lower() == "production":
        return "APP_ENV=production disables writing secrets from the API (including GOOGLE_REFRESH_TOKEN)."
    val = os.environ.get("ALLOW_SETUP_ENV_WRITE", "").strip()
    lc = val.lower()
    if lc in ("1", "true", "yes", "on"):
        return ""
    if not val:
        return (
            "ALLOW_SETUP_ENV_WRITE is not enabled in this API process. "
            "Set ALLOW_SETUP_ENV_WRITE=true in the .env that this process loads (or in docker-compose `environment` / `env_file`) "
            "and restart the server — editing a file on the host is not enough if the container never sees that variable."
        )
    return (
        f"ALLOW_SETUP_ENV_WRITE={val!r} is not accepted; use true, 1, yes, or on (then restart the API)."
    )


def bootstrap_env_write_allowed() -> bool:
    return env_write_blocked_reason() == ""


def build_setup_hints(
    *,
    llm_ok: bool,
    cdn_ok: bool,
    allow_write: bool,
) -> list[str]:
    """Safe, no-secret hints for the setup UI."""
    hints: list[str] = []
    paths = discover_env_files()

    if not paths:
        hints.append(
            f"No .env file on disk inside this process. Expected at: {safe_str_path(ENV_FILE_PATH)} "
            f"(that is your backend/.env on the host when using Docker build context ../backend).",
        )
        if _likely_docker_single_dir_layout():
            hints.append(
                "Docker Compose (infra/): add under `backend:` → `env_file: ../backend/.env` "
                "so variables from your host `backend/.env` are injected. "
                "Alternatively mount: `volumes: - ../backend/.env:/app/.env` (path is relative to the compose file).",
            )
        else:
            rp = _repo_dotenv_path()
            if rp is not None:
                hints.append(f"Or use a repo-root file: {safe_str_path(rp)} (loaded before backend/.env if present).")
            hints.append(
                "Optional: set AI_BIZ_OS_DOTENV to an absolute path of a .env file to load first.",
            )
        hints.append(
            "The API also uses variables already in the process environment (e.g. from `docker compose` env_file).",
        )
    else:
        hints.append(
            "Loaded: " + " → ".join(safe_str_path(p) for p in paths)
            + " (later path wins for duplicate variable names).",
        )

    if not llm_ok:
        hints.append(
            "LLM: set at least one of ANTHROPIC_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY, "
            "PERPLEXITY_API_KEY, XAI_API_KEY (exact names — copy from backend/.env.example).",
        )

    if not cdn_ok:
        hints.append(
            f"CDN: set CDN_PROVIDER to one of {', '.join(sorted(VALID_CDN))} and a non-empty CDN_API_KEY.",
        )

    if not allow_write:
        if os.environ.get("APP_ENV", "").strip().lower() == "production":
            hints.append("Saving from the browser is disabled when APP_ENV=production.")
        elif not os.environ.get("ALLOW_SETUP_ENV_WRITE", "").strip():
            hints.append(
                "Saving from the browser: add ALLOW_SETUP_ENV_WRITE=true to .env (local/dev only). "
                "Or keep editing .env manually — that is fine.",
            )
        else:
            cand = os.environ.get("ALLOW_SETUP_ENV_WRITE", "").strip().lower()
            if cand not in ("1", "true", "yes", "on"):
                hints.append(
                    f"ALLOW_SETUP_ENV_WRITE is “{cand}”; use true / 1 / yes / on to allow server-side save.",
                )

    return hints


def _escape_env_value(val: str) -> str:
    if not val:
        return ""
    if re.search(r'[\s\n\r#"\'\\]', val):
        escaped = val.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return val


def upsert_env_file_at(path: Path, updates: dict[str, str]) -> None:
    """
    Merge updates into one .env file. Preserves unrelated keys and comment lines.
    Empty string in updates removes that key's line if it existed, or adds nothing.
    """
    path = path.resolve()
    if path.exists() and not path.is_file():
        raise OSError(f"Not a file (is it a directory?): {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        lines: list[str] = (
            path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
        )
    except UnicodeDecodeError:
        lines = []

    out: list[str] = []
    keys_seen_in_updates: set[str] = set()

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out.append(line)
            continue
        if "=" not in stripped:
            out.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            keys_seen_in_updates.add(key)
            val = updates[key].strip() if isinstance(updates[key], str) else ""
            if val:
                out.append(f"{key}={_escape_env_value(val)}")
            # empty val: drop previous assignment
        else:
            out.append(line)

    for key, raw in updates.items():
        if key not in keys_seen_in_updates:
            val = raw.strip() if isinstance(raw, str) else ""
            if val:
                out.append(f"{key}={_escape_env_value(val)}")

    path.write_text("\n".join(out) + ("\n" if out else ""), encoding="utf-8")


def upsert_env_file(updates: dict[str, str]) -> None:
    """Merge updates into backend/.env (package root), then reload process env from all candidates."""
    upsert_env_file_at(ENV_FILE_PATH, updates)
    load_env_from_file()


def upsert_env_files_everywhere(updates: dict[str, str]) -> None:
    """
    Merge updates into every dotenv file the app loads (candidates), plus backend/.env always.

    Used for GOOGLE_REFRESH_TOKEN so the token is visible wherever the developer looks and
    Docker/env_file paths that point at backend/.env still receive the value.
    """
    targets: set[Path] = {p.resolve() for p in ordered_env_candidates()}
    targets.add(ENV_FILE_PATH.resolve())
    for p in sorted(targets, key=lambda x: str(x)):
        upsert_env_file_at(p, updates)
    load_env_from_file()
