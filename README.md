# search-relevance-benchmark

A search engine that grades search engines.

Point the system at a fashion storefront. Ingest its catalog, infer what each product
actually is, build independent search over it, then run a fixed set of realistic shopper
queries against both that search and the storefront's own. Publish a scorecard with the
methodology attached.

The output is a *measurement* — a number produced by a stated method comparing two systems
on the same data — not a demo.

Design: [`docs/superpowers/specs/2026-08-25-search-relevance-benchmark-design.md`](docs/superpowers/specs/2026-08-25-search-relevance-benchmark-design.md)

## What is built so far

The catalog ingestion pipeline (spec section 6.1). Enrichment, retrieval, evaluation and
the service are separate plans; this stage ends with a trustworthy, re-runnable snapshot
and a queue of enrichment jobs waiting to be consumed.

**The claim it exists to support:** run ingest twice back-to-back and get zero new product
versions and zero enrichment jobs. Not zero database *updates* — an unchanged record
legitimately touches `last_seen`.

## Quick start

Requires Python 3.13 and [uv](https://docs.astral.sh/uv/). No runtime dependencies beyond
the standard library and `curl`.

```bash
uv sync
uv run pytest                     # 62 tests
```

Ingest a catalog:

```bash
uv run python -m catalog.ingest \
  --store zoovillage.com \
  --run-id anchor-003 \
  --locale sv-SE \
  --accept-language 'sv-SE,sv;q=0.9,en;q=0.5' \
  --minimum-count 2000
```

This crawls the catalog **twice** and refuses to touch any state unless both crawls agree,
so a run takes a few minutes of mostly waiting. That is the pacing working, not a hang.

Run it a second time with a fresh `--run-id` and it should report
`new=0 source_changed=0 enrichment_stale=0 disappeared=0` and zero enrichment jobs.

## Layout

| Path | What it is |
|---|---|
| `catalog/fetch.py` | Paced, disk-cached, locale-aware HTTP. Caches only *validated* bodies. |
| `catalog/record.py` | Normalisation, and the two hashes the incremental design rests on. |
| `catalog/shopify.py` | Paginated crawl, duplicate-id detection, whole-crawl verification. |
| `catalog/store.py` | SQLite state and the five sync transitions. Soft-delete only. |
| `catalog/ingest.py` | Orchestration, immutable run IDs, artifacts, and the CLI. |
| `artifacts/` | Committed. Manifests: count, content digest, snapshot hash, request profile. |
| `data/` | Git-ignored. Snapshots, response cache, SQLite. The catalog is theirs, not ours. |

## Two design decisions worth knowing

**Two hashes, never one.** `source_payload_hash` covers the source record and drives version
history. `enrichment_input_hash` covers search-relevant fields only and drives enrichment
caching — so a price change records a new version but never re-pays for enrichment. A single
hash could not serve both purposes.

**Consistency is detected, not prevented.** Page-based pagination is unstable under
concurrent catalog edits and the public endpoint offers no `since_id`. So every crawl runs
twice under different cache namespaces and the two content manifests must agree. Re-fetching
page 1 proves only that page 1 is stable. A crawl that cannot prove it saw a consistent
catalog does not become a benchmark.

## Treating third parties well

This is an invariant, not a preference. Violating it makes the project worthless rather
than weaker.

- Minimum 3.0 seconds between live requests. There is deliberately no CLI flag to lower it.
- Every validated response is cached to disk; errors, malformed pages and bot challenges
  never enter the cache.
- Image **URLs** are stored. No image is ever downloaded or rehosted.
- `robots.txt` was checked for every storefront before crawling.
- Named comparisons are shared privately with the storefronts before publication.

## Storefronts

| Role | Store | Products | Scored by |
|---|---|---|---|
| Anchor | zoovillage.com | 2,066 | human labels |
| Storefront 2 | rezetstore.dk | 1,973 | calibrated proxy |
| Storefront 3 | galvingreen.com | 1,365 | calibrated proxy |

Only the anchor is hand-labeled. Storefronts 2 and 3 test whether the findings transfer,
and are scored by proxy only if that proxy first clears a pre-registered agreement
threshold. If it does not, both are cut and the project reports the anchor alone.
