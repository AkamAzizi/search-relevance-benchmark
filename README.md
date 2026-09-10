# search-relevance-benchmark

A search engine that grades search engines.

The output is a *measurement* — a number produced by a stated method comparing two systems
on the same data — not a demo.

**Public scorecard:** [BM25+Lex vs Store A native](site/index.html)
(open that file; methodology is on the page).

This is an independent methodology demonstration. It is not an official audit or
endorsement of the retailer.

Design: [`docs/superpowers/specs/2026-08-25-search-relevance-benchmark-design.md`](docs/superpowers/specs/2026-08-25-search-relevance-benchmark-design.md)

## Result (Swedish fashion retailer A, snapshot `anchor-003`, 1,904 products)

24 frozen queries, catalog-grounded grades, nDCG@10 on the 21 answerable queries.

| System | nDCG@10 | P@10 (grade ≥ 2) | Results on absent queries |
|---|---|---|---|
| BM25+Lex | **0.998** | 0.875 | 0 |
| Store A native | 0.957 | 0.846 | 25 |
| BM25+Compound | 0.926 | 0.825 | 0 |
| BM25 | 0.811 | 0.708 | 0 |

Held-out check on `store-a-v2` (16 queries, frozen and committed before BM25+Lex was
run on it): BM25+Lex **0.941** · Store A native 0.885 ·
results on absent queries BM25+Lex 0 / native 3.

BM25+Lex is BM25+Compound plus four query-side rules derived from the catalog, not the
query set: the modifier of a compound is kept (*herr* from *herrjeans*), English garment
words map to the Swedish head (*jacket* → *jacka*), a token within one edit of exactly
one vendor token also matches it (*carhart* → *carhartt*), and a document's score is
scaled by the share of query terms it matches. It was designed after the v1 results
were visible, so its v1 number is a development number; the held-out line is the sealed
one. Compound splitting remains a real mechanism on its own: on *jacka* / *skjorta* /
*väska* BM25+Compound scores 1.000 against plain BM25 at 0.784.
Query set hashes: v1 `777c230f5d94de28ada067bb66e0e9b9fad73f57f2bfab2801a0611e561c8381`,
v2 `2b4f842c1511fe29ac5b9a2bfe516fdfabe236af47720b29d6ccd4fae7410dca`.

This is **not** the human-pooled, sealed test split in the spec. Grades come from
merchant fields (vendor, product type, tags), committed with the queries, before
any ranking ran. Brand and type queries are a retrieval ceiling: every match has
the same grade, so nDCG@10 is 1.000 for any system that fills ten slots with
relevant items.

## Quick start

Requires Python 3.13 and [uv](https://docs.astral.sh/uv/). No runtime dependencies beyond
the standard library and `curl`.

```bash
uv sync
uv run pytest
```

Ingest a catalog (crawls twice; pacing is 3s between live requests). The live host
stays private:

```bash
uv run python -m catalog.ingest \
  --store "$STORE_HOST" \
  --run-id anchor-004 \
  --locale sv-SE \
  --accept-language 'sv-SE,sv;q=0.9,en;q=0.5' \
  --minimum-count 1500
```

Score native search against BM25, writing `site/index.html`:

```bash
uv run python -m eval.run \
  --snapshot data/store-a/snapshot-anchor-003.jsonl \
  --manifest artifacts/store-a/manifest-anchor-003.json \
  --queries artifacts/queries/store-a-v1.json \
  --out artifacts/store-a/scorecard-v1 \
  --holdout artifacts/store-a/scorecard-v2/scorecard.json \
  --capture-native \
  --host "$STORE_HOST"
```

`--capture-native` hits the live `/search` page once per query and caches the HTML.
Re-running uses the cache. Native HTML stays in git-ignored `data/`; product ids and
scores are committed under `artifacts/`. `--host` is required for capture and is
never written to public artifacts.

Run the same command first with `--queries artifacts/queries/store-a-v2.json --out artifacts/store-a/scorecard-v2 --site ""` and without `--holdout` to produce the held-out scorecard.

## Layout

| Path | What it is |
|---|---|
| `catalog/` | Polite ingest, two-hash sync, verified crawls. |
| `engine/` | Fielded BM25, Swedish fashion-head splitting, and the BM25+Lex query lexicon. |
| `eval/` | Frozen queries, catalog-grounded grades, nDCG, native capture, the page. |
| `site/index.html` | The public scorecard (Store A). |
| `artifacts/` | Committed. Manifests, query set, run specs, runs, scorecard. |
| `data/` | Git-ignored. Snapshots, response cache, SQLite. The catalog is theirs. |

## Treating third parties well

- Minimum 3.0 seconds between live requests. There is deliberately no CLI flag to lower it.
- Every validated response is cached to disk; errors, malformed pages and bot challenges
  never enter the cache.
- Image **URLs** are stored. No image is ever downloaded, rehosted, or shown on the scorecard.
- `robots.txt` was checked for every storefront before crawling.
- Named comparisons are shared privately with the storefronts before publication.
- The public scorecard does not name the retailer.

## Storefronts

| Role | Store | Products (this scorecard) | Scored by |
|---|---|---|---|
| Anchor | Store A | 1,904 (`anchor-003`) | catalog-grounded grades |
| Storefront 2 | ingested, not scored here | — | — |
| Storefront 3 | ingested, not scored here | — | — |
