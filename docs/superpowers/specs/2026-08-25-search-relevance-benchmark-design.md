# Design: A search engine that grades search engines

**Date:** 2026-08-25
**Status:** design agreed in brainstorming; not yet implemented
**Deliverable:** the evaluation. The engine exists to make the evaluation meaningful.

---

## 1. Purpose

Point a system at a fashion storefront. Ingest its catalog, infer what each product
actually is, build independent search over it, then run a fixed set of realistic shopper
queries against both that search and the storefront's own. Publish a scorecard with the
methodology attached.

The output is a *measurement* — a number produced by a stated method comparing two systems
on the same data — not a demo.

## 2. Invariants

These are constraints, not goals. Violating one makes the project worthless rather than
weaker, because its entire value is that its numbers can be trusted.

1. A human produces the ground truth: queries, relevance judgements, enrichment accuracy sample.
2. Judgements are blind and pooled across every system compared.
3. The query set is committed with a timestamp before any tuning. Never edited after results are visible.
4. Any automated proxy is calibrated against human labels, against a threshold fixed in advance.
5. Known advantages are disclosed in the writeup, not discovered by the reader.
6. The core reasoning — ranking, fusion, truncation, metrics — is defensible line by line by the submitter.
7. Third parties are treated well: polite cached access, no rehosted imagery, named comparisons shared privately.

## 3. Scope

**In:** one anchor catalog labeled thoroughly; two languages; one market; ingestion,
enrichment, hybrid retrieval, reranking, truncation, merchandising rules, a narrow answer
layer, the evaluation harness, the labeling tool, deployment, cost/latency accounting.

**Out:** recommendations beyond search, personalisation, A/B infrastructure, multi-tenancy,
auth, anything resembling a commercial product, catalogs larger than those chosen.

**Cut order:** decorative retrieval features, then admin interfaces, then storefront count,
then answer-layer breadth. Never cut: human judgements, comparison table, truncation,
multilingual control, deployment.

## 4. Storefront selection

Hard criteria, checked in this order:

1. Queryable search endpoint (cannot be worked around — check first)
2. >= ~1,000 products
3. Multi-brand (vocabulary diversity)
4. **Native storefront search, no third-party overlay** — so the baseline IS the shopper-facing system
5. Not a Depict customer (anchor only)
6. Commercially stable — will not change owner or platform mid-project

Criterion 4 exists because benchmarking a surface real shoppers don't use is the "rigged
comparison" failure: an honest mistake that reads as dishonesty.

**Status:** see `storefront-research.md`. Zoovillage is the sole surviving anchor candidate
and still needs overlay and catalog-language verification. The Footway group (Footway,
Sportamore, Stayhard, Caliroots) is rejected — Nosto overlay plus an active divestment
process following the 2025 bankruptcy. Depict's real customer list is 79 brands and
includes Swedish multi-brand retailers (Aplace, Grandpa) that a shorter exclusion list
would have missed. English-language slot and Depict reference store remain unfilled.

## 5. Architecture: dataset-centric with a thin service

Every stage emits a versioned artifact. Each search system is a pure function over
artifacts. The evaluation reads artifacts and **never calls the running service** — so
reproducing a number requires no infrastructure, and "I reran it and got something else"
has one possible cause instead of many.

    catalog.parquet -> enriched.parquet -> index/ -> runs/{system}/{query}.json -> scorecard.md

The deployed service loads the same artifacts to serve the live demo and to produce the
latency measurements.

### The spine

    class SearchSystem(Protocol):
        name: str
        def search(self, query: str, k: int) -> list[Hit]: ...

### The ablation ladder

| System | Adds |
|---|---|
| `NativeSearch` | the baseline — the storefront's real search |
| `BM25` | lexical only |
| `BM25+Compound` | lexical with Swedish compound splitting |
| `Dense` | semantic only |
| `Hybrid` | RRF fusion |
| `Hybrid+Rerank` | cross-encoder |
| `Hybrid+Rerank+Truncate` | the cutoff |

The ladder satisfies the requirement that the table include a configuration that performed
*worse* — by construction rather than by search. `Dense` alone is expected to lose to
`BM25` on exact brand and SKU queries.

## 6. Components

### 6.1 Ingestion and incremental sync
*Claim: a pipeline that runs twice without duplicating or losing anything.*

Shopify `products.json?limit=250&page=N`, paced 3s, every response cached by URL hash.
State keyed on `product_id` with `content_hash`, `first_seen`, `last_seen`, `deleted_at`.

| Run-2 outcome | Condition | Action |
|---|---|---|
| new | id unseen | insert |
| changed | hash differs | new version row |
| unchanged | hash matches | touch `last_seen` only |
| disappeared | absent now | soft-delete, never hard-delete |

`content_hash` covers only search-relevant fields, so price/inventory churn does not
trigger re-enrichment.

**Acceptance test:** run ingest twice back-to-back; assert zero inserts, zero updates,
zero duplicates.

**Pagination hazard:** page-based pagination is unstable under concurrent catalog edits.
The public endpoint offers no `since_id`, so mitigate by detection — assert id uniqueness
across pages and re-fetch page 1 at the end to confirm it is unchanged. On failure,
discard and re-crawl. A crawl that cannot prove consistency must not become a benchmark.

**Imagery:** store URLs only. Never rehost.

### 6.2 Enrichment into a controlled vocabulary
*Claim: structured output beats prose, because filters need enums.*

Justified concretely: Footway's `product_type` was empty on all 250 products sampled.
Merchant structure is often simply absent.

Five fields, defined in version-controlled YAML: `category` (hierarchical),
`target_group`, `colour`, `material`, `fit`. Narrowed from ten to keep the human accuracy
check affordable — 150 products x 5 fields is 750 judgements, and the hour saved belongs
in relevance judgements.

Output is enum members only. Off-vocabulary output is retried once, then recorded as
`null` with the raw response kept. Null is honest; a hallucinated enum is not. Cached by
`content_hash`.

**Accuracy:** a human hand-labels ~150 random products against the same taxonomy, blind to
model output. Per-field agreement is published including fields that do badly. A field
below acceptable agreement is not used as a hard filter.

### 6.3 Retrieval, fusion, reranking, truncation
*Every choice here is picked for defensibility over sophistication (invariant 6).*

**Lexical:** BM25 over title, tags, vendor, enriched category. Chosen over TF-IDF for term
saturation and length normalisation via `b`.

**Compound control:** the claim that Swedish compounding is a retrieval *mechanism*
requires a control. `regnjacka` cannot match a query for `jacka` under conventional
stemming; subword embeddings can. But "dense beat BM25" has many possible causes, so the
ladder includes `BM25+Compound`. If dense's advantage collapses once BM25 can split
compounds, the mechanism is confirmed and quantified; if not, the explanation was wrong and
that is reported. Only the uncontrolled version is worthless.

**Dense:** local multilingual subword embedding model, cosine over normalised vectors.
**Exact brute-force search, no ANN index** — at ~5,000 products this is one matrix multiply
in single-digit milliseconds. The measured number goes in the README; declining to add
FAISS with a benchmark behind it is a stronger answer than adding it.

**Fusion:** reciprocal rank fusion, `score = sum 1/(k + rank_i)`, `k=60`. Rank-based
because BM25 scores and cosine similarities are on incomparable scales whose distributions
shift per query.

**Truncation:** reranker score -> calibrated `P(relevant)` via logistic regression, cut at
0.5, floor of 1 result, and a cap. **Calibration is fit on a held-out split of queries,
never results.** Fitting the cutoff on the judgements it is evaluated against is leakage
and is the most likely route to a suspiciously good number.

**Metric consequence:** nDCG@20 cannot see padding. Truncation is therefore scored on a
set-based companion — F1 of the returned set against the judged relevant set, at each
system's own cutoff. Ranking quality and stopping quality are different questions.

**Expected failure case (to document, not tune away):** broad exploratory queries — `dam`,
`nyheter`, `jackor` — have genuinely large relevant sets, and a cutoff amputates them.

### 6.4 Labeling protocol and metrics
*The heaviest-weight component alongside truncation.*

**Query set:** ~45 queries, committed and git-tagged with a timestamp before the engine can
return anything; the file hash is printed in the README. Sourced from storefront
autocomplete, popular-search modules and shopper vocabulary — never from inspecting
results. Stratified:

| Stratum | Tests |
|---|---|
| exact / brand | lexical precision |
| category | basic retrieval |
| compound | the Swedish mechanism |
| attribute | enrichment quality |
| natural language | semantic retrieval |
| misspelling | robustness |
| cross-language | the multilingual claim |
| adversarial / absent | correct abstention |

The adversarial stratum is where truncation earns its keep; nothing else punishes a system
that returns 60 results for a query the catalog cannot serve.

**Pooling:** union the top-10 from every system per query, deduplicate, strip provenance,
shuffle with a seed derived from the query id. The labeler sees a flat list — no system, no
rank.

**Volume:** ~25-30 unique products per query across ~45 queries = **1,100-1,350
judgements**, 2-3 hours. If reduced, reduce systems in the pool, not queries — query count
drives the confidence intervals.

**Rubric:** graded 0-3. 3 = what was asked for; 2 = valid substitute satisfying the intent;
1 = related but wrong; 0 = irrelevant. Written with worked examples and committed before
labeling begins.

**Self-labeling bias:** the builder is also the labeler. Blind pooling handles provenance,
not personal opinion or drift. Mitigation: re-label a 10% random subsample after a gap of
days and **publish intra-annotator agreement (Cohen's kappa) against yourself.** That figure
is a hard ceiling on how much precision anyone should read into the comparison.

**Pooling's residual bias, disclosed:** a product no system retrieved is never judged, and
would be scored irrelevant if a future system found it.

**Metrics:** nDCG@10 (ranking), Recall@20 (finding), F1 at each system's own cutoff
(stopping), correct-abstention rate (adversarial stratum).

**Confidence intervals:** bootstrap over *queries*, not judgements — the query is the unit
of variation. At n=45 many differences will not reach significance. The table must show
that rather than hide it behind point estimates.

**Proxy calibration:** before any automated judge extends results to storefronts 2 and 3,
its agreement with human labels on the anchor is measured against a threshold fixed in
advance (proposed: kappa >= 0.6). Below it, the proxy is unused and the extra storefronts
are cut.

### 6.5 Interface, answer layer, deployment, cost

**Interface:** deliberately plain and fast; visual polish is explicitly outside the
definition of done. One thing earns real estate — truncation must be *visible*. "4 results
— relevance ends here" beside a baseline returning 60 padded ones is the screenshot that
carries the ninety-second read. Facets come from the enriched enums.

**Answer layer:** narrow. Grounded strictly in retrieved product fields. The test that
matters is refusal — ask something the catalog cannot support and confirm it declines.

**Deployment:** Railway, single service. FastAPI serves both API and the built index; the
Next.js UI is built and served alongside. A warm process keeps the model loaded so latency
figures reflect steady state rather than cold starts.

**Cost and latency:** published per ladder rung, p50 and p95, measured on the deployed
instance, with cost per 1,000 queries and enrichment amortised. The tradeoff is stated
outright: exact search is O(n), fine at 5,000 products and not at 500,000.

## 7. Repository layout

    catalog/      ingestion, sync, enrichment
    engine/       retrieval, fusion, rerank, truncation
    eval/         query set, pooling, labeling tool, metrics, bootstrap
    service/      FastAPI + UI
    data/         cached responses and versioned artifacts (git-ignored, hashes committed)
    docs/         methodology, limitations, the writeup

## 8. Build order and submittable checkpoints

Timeline is open-ended, which makes silence the live risk. Each checkpoint is a point where
the work could be sent as-is.

1. **Query set + rubric committed, timestamped.** Invariant 3 becomes structurally true.
2. **Ingestion + sync, with the twice-run test passing.** First defensible claim.
3. **Enrichment + human accuracy sample.** First published number.
4. **Ladder + harness + labeled ground truth -> the comparison table.** *Submittable: this is the project.*
5. **Truncation calibrated, successes and failure case documented.**
6. **Deployment + latency/cost table.**
7. **The writeup.**

## 9. Disclosures to publish (invariant 5)

- We tuned on the catalog we benchmark.
- Our system is specialised; the comparison is general-purpose.
- The builder is the labeler; intra-annotator agreement is published as the ceiling.
- Pooling cannot judge what no system retrieved.
- At n=45 queries, many differences are not statistically significant.

## 10. Open questions

- Anchor storefront unconfirmed (Zoovillage pending overlay + language verification).
- English-language Nordic storefront unfilled.
- Depict reference store unfilled.
- Public-demo product imagery: hotlink from the merchant CDN, or omit images entirely.
