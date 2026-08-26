"""Orchestrate a verified crawl into immutable snapshot and manifest artifacts."""
import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from catalog.fetch import PoliteFetcher, RequestProfile
from catalog.shopify import crawl_verified
from catalog.store import SyncReport, current_live_count, open_store, sync


class ArtifactExists(Exception):
    """A run ID already names an immutable snapshot or manifest."""


@dataclass
class IngestResult:
    domain: str
    run_id: str
    manifest: dict
    report: SyncReport
    snapshot_path: Path
    manifest_path: Path


def _write_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = path.open("xb")
    except FileExistsError as exc:
        raise ArtifactExists(f"artifact already exists for run {path.stem}") from exc
    try:
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        # Unlike a killed process, an exception that unwinds normally leaves a
        # traceback as evidence, so the truncated file underneath adds nothing
        # except making ArtifactExists lie about this run having succeeded.
        path.unlink(missing_ok=True)
        raise


def ingest(domain: str, data_dir: Path, run_id: str, profile: RequestProfile,
           artifacts_dir: Path | None = None,
           fetcher: PoliteFetcher | None = None, now: str | None = None,
           minimum_count: int = 1, max_drop_fraction: float = 0.10,
           allow_large_drop: bool = False,
           attempt_id: str | None = None) -> IngestResult:
    data_dir = Path(data_dir)
    # NOT under data_dir: data/ is git-ignored, and manifests must be committable.
    artifacts_dir = Path(artifacts_dir) if artifacts_dir else Path("artifacts")
    now = now or datetime.now(UTC).isoformat()
    attempt_id = attempt_id or uuid4().hex
    store_dir = data_dir / domain
    store_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir = artifacts_dir / domain
    snapshot_path = store_dir / f"snapshot-{run_id}.jsonl"
    manifest_path = artifact_dir / f"manifest-{run_id}.json"
    if snapshot_path.exists() or manifest_path.exists():
        raise ArtifactExists(f"run_id={run_id} already has an immutable artifact")

    fetcher = fetcher or PoliteFetcher(data_dir / "cache", profile)
    if fetcher.profile != profile:
        raise ValueError("fetcher profile does not match ingest profile")

    conn = open_store(store_dir / "catalog.db")
    previous_count = current_live_count(conn) or None
    records, core_manifest = crawl_verified(
        fetcher, domain, attempt_id=attempt_id, minimum_count=minimum_count,
        previous_count=previous_count, max_drop_fraction=max_drop_fraction,
        allow_large_drop=allow_large_drop,
    )

    snapshot_bytes = "".join(
        json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n"
        for rec in sorted(records, key=lambda r: r["product_id"])
    ).encode("utf-8")
    manifest = {
        **core_manifest,
        "domain": domain,
        "run_id": run_id,
        "attempt_id": attempt_id,
        "crawled_at": now,
        "request_profile": asdict(profile),
        "snapshot_sha256": hashlib.sha256(snapshot_bytes).hexdigest(),
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()

    # Exclusive creation makes run IDs immutable. Interrupted partial files are evidence to
    # inspect, not objects to overwrite silently. Both artifacts land before sync() commits,
    # so a write failure here never leaves the store durably ahead of what's on disk.
    _write_new(snapshot_path, snapshot_bytes)
    try:
        _write_new(manifest_path, manifest_bytes)
    except Exception:
        # The snapshot this call just wrote would otherwise outlive the failed run and
        # block every retry of this run id with ArtifactExists. A prior run's artifact
        # is never touched here: this path only unlinks the file written moments above.
        snapshot_path.unlink(missing_ok=True)
        raise
    report = sync(conn, records, now=now)
    return IngestResult(domain, run_id, manifest, report, snapshot_path, manifest_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest a Shopify catalog, politely.")
    parser.add_argument("--store", required=True, help="e.g. zoovillage.com")
    parser.add_argument("--locale", required=True, help="catalog locale, e.g. sv-SE or en")
    parser.add_argument("--accept-language", required=True)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--artifacts-dir", default="artifacts")
    parser.add_argument("--minimum-count", type=int, default=1)
    parser.add_argument("--max-drop-fraction", type=float, default=0.10)
    parser.add_argument("--allow-large-drop", action="store_true")
    parser.add_argument("--run-id", default=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    args = parser.parse_args()

    profile = RequestProfile(args.locale, args.accept_language)
    result = ingest(
        args.store, Path(args.data_dir), run_id=args.run_id, profile=profile,
        artifacts_dir=Path(args.artifacts_dir), minimum_count=args.minimum_count,
        max_drop_fraction=args.max_drop_fraction,
        allow_large_drop=args.allow_large_drop,
    )
    r = result.report
    print(f"{result.domain}  run={result.run_id}  products={result.manifest['count']}")
    print(f"  new={r.new} source_changed={r.source_changed} "
          f"enrichment_stale={r.enrichment_stale} unchanged={r.unchanged} "
          f"disappeared={r.disappeared}")
    print(f"  enrichment jobs queued: {r.enrichment_jobs}")
    print(f"  snapshot: {result.snapshot_path}")
    print(f"  manifest: {result.manifest_path}")


if __name__ == "__main__":
    main()
