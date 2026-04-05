#!/usr/bin/env python3
"""
Print row counts for global assets, asset_packets (optionally for one run),
and asset_packet_assets junction. Use to verify data was not deleted by migrations.

Run from the backend directory (folder that contains app/ and requirements.txt):

    python3 scripts/check_assets_packets.py
    python3 scripts/check_assets_packets.py 19

Needs only ``psycopg2-binary`` (or full ``pip install -r requirements.txt``):

    python3 -m pip install --user psycopg2-binary

Loads DATABASE_URL from backend/.env if present; otherwise defaults to local Postgres
(postgresql://postgres:postgres@localhost:5432/ai_biz_os).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _load_dotenv_simple() -> None:
    """KEY=VALUE lines from backend/.env — no python-dotenv required."""
    p = _BACKEND_ROOT / ".env"
    if not p.is_file():
        return
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError:
        return
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        val = val.strip().strip('"').strip("'")
        os.environ[key] = val


def _help_missing_psycopg2() -> None:
    print(
        "Missing psycopg2 (PostgreSQL driver).\n\n"
        "Install only the driver:\n"
        "  python3 -m pip install --user psycopg2-binary\n\n"
        "Or use the backend virtualenv with all dependencies:\n"
        "  cd ai-biz-os/backend\n"
        "  python3 -m venv .venv\n"
        "  source .venv/bin/activate\n"
        "  pip install -r requirements.txt\n"
        "  python scripts/check_assets_packets.py 19\n",
        file=sys.stderr,
    )


def main() -> None:
    _load_dotenv_simple()
    try:
        import psycopg2
        from psycopg2.extensions import connection as PsycopgConnection
    except ImportError:
        _help_missing_psycopg2()
        raise SystemExit(1) from None

    rid: int | None = None
    if len(sys.argv) > 1:
        try:
            rid = int(sys.argv[1], 10)
        except ValueError:
            print("Usage: python3 scripts/check_assets_packets.py [run_id]", file=sys.stderr)
            raise SystemExit(2) from None

    dsn = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ai_biz_os")
    # SQLAlchemy-style URLs sometimes use +asyncpg etc.; psycopg2 wants postgresql://
    if "+asyncpg" in dsn:
        dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)

    conn: PsycopgConnection
    try:
        conn = psycopg2.connect(dsn)
    except Exception as e:
        print(f"Could not connect: {e}\nDSN (password hidden): {_redact_dsn(dsn)}", file=sys.stderr)
        raise SystemExit(3) from None

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM assets")
            total_assets = cur.fetchone()[0]

            cur.execute("SELECT status, COUNT(*) FROM assets GROUP BY status ORDER BY status")
            by_status = cur.fetchall()

            cur.execute("SELECT COUNT(*) FROM asset_packets")
            total_packets = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM asset_packet_assets")
            junction_rows = cur.fetchone()[0]

            print(f"assets (all rows):           {total_assets}")
            for st, n in by_status:
                print(f"  status={st!r}:             {n}")
            print(f"asset_packets (all runs):    {total_packets}")
            print(f"asset_packet_assets (links): {junction_rows}")

            if rid is not None:
                cur.execute("SELECT COUNT(*) FROM asset_packets WHERE run_id = %s", (rid,))
                n_p = cur.fetchone()[0]

                cur.execute(
                    """
                    SELECT COUNT(*) FROM asset_packet_assets apa
                    INNER JOIN asset_packets ap ON ap.id = apa.packet_id
                    WHERE ap.run_id = %s
                    """,
                    (rid,),
                )
                j_for_run = cur.fetchone()[0]

                print()
                print(f"run_id={rid}: asset_packets rows = {n_p}")
                print(f"run_id={rid}: junction rows for those packets = {j_for_run}")

                cur.execute(
                    """
                    SELECT ap.id, ap.title
                    FROM asset_packets ap
                    WHERE ap.run_id = %s
                      AND NOT EXISTS (
                        SELECT 1 FROM asset_packet_assets apa WHERE apa.packet_id = ap.id
                      )
                    ORDER BY ap.id
                    """,
                    (rid,),
                )
                orphans = cur.fetchall()
                if orphans:
                    print()
                    print(
                        "Packets with NO junction rows (if packet_json.assets was stripped before "
                        "backfill, membership cannot be auto-restored):"
                    )
                    for pid, title in orphans:
                        print(f"  packet_id={pid} title={title!r}")
    finally:
        conn.close()


def _redact_dsn(dsn: str) -> str:
    if "@" not in dsn:
        return dsn
    try:
        head, tail = dsn.split("@", 1)
        if "://" in head:
            scheme, rest = head.split("://", 1)
            if ":" in rest:
                user, _pwd = rest.split(":", 1)
                return f"{scheme}://{user}:***@{tail}"
    except Exception:
        pass
    return dsn


if __name__ == "__main__":
    main()
