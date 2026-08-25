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
3. The query set is committed with a timestamp before any tuning, split into development and
   sealed test at commit time, and never edited after results are visible.
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

**Selected, verified 2026-08-25:**

| Slot | Store | Products | Vendors | Catalog language | Search |
|---|---|---|---|---|---|
| **Anchor** | **zoovillage.com** | ~2,000-2,250 | 31 | Swedish descriptions, English titles | native Shopify |
| **English** | **rezetstore.dk** | >1,250 | 33 | English | native Shopify |

Both pass all six criteria. Overlay checks: Zoovillage loads Klaviyo (email) and Pertento
(A/B testing) but no search vendor; Rezet loads Klaviyo only. Both server-render results
from `action="/search"`. An apparent Constructor.io hit on Zoovillage was a false positive —
JavaScript `constructor()` declarations in Shopify web components — and was discarded after
checking for the real `cnstrc` fingerprint.

**Zoovillage carries an unplanned bonus:** English product titles over Swedish
descriptions. The cross-language retrieval problem is therefore present *inside a single
catalog*, giving the multilingual claim a matched-catalog control rather than one confounded
across two storefronts. Its descriptions are also densely compounded — `bomberjacka`,
`coachjacka`, `mockajacka`, `pilejacka`, `hybridjacka`, `flanellskjorta`, `jeansskjorta`,
`manchesterskjorta`, `axelväska`, `handväska`, `läderväska`, `långklänning`, `maxiklänning`
— which is the section 4 mechanism available in quantity.

**Rejected:** the Footway group (Footway, Sportamore, Stayhard, Caliroots) — Nosto overlay
plus an active divestment following the 2025 bankruptcy. Norse Store, Storm Fashion (under
1,000). Junkyard (blocks automated access). Outnorth, Addnature, Dunken, Nitty Gritty,
Care of Carl, Johnells (no catalog API).

**On Depict's customer list:** it is 79 brands, not the 9 initially excluded, and it
includes Swedish *multi-brand* retailers — Aplace and Grandpa — that a shorter list would
have missed. Neither selected store appears on it.

## 5. Architecture: dataset-centric with a thin service

Every stage emits a versioned artifact. The evaluation reads artifacts and **never calls a
running service** — so reproducing a number requires no infrastructure, and "I reran it and
got something else" has one possible cause instead of many.

**The baseline is not a pure function, and this spec must not pretend otherwise.** Local
systems are deterministic functions over the catalog snapshot. `NativeSearch` is a live
remote black box whose internal index may hold newer, deleted, unavailable or
differently-localised products. It is therefore handled as a **capture-and-replay
adapter**: raw responses are captured once, as close to crawl time as possible, together
with locale, market, currency, headers, cookies, endpoint parameters, timestamp, and the
product/variant mapping used to resolve its results onto local ids. The harness replays
those captured artifacts and never calls the storefront during evaluation. Overlap with the
local snapshot is audited and reported, and the writeup states plainly that exact snapshot
equality cannot be proven for a black-box baseline.

    catalog.parquet -> enriched.parquet -> index/ -> runs/{system}/{query}.json -> scorecard.md

The deployed service loads the same artifacts to serve the live demo and to produce the
latency measurements.

### The public seam

`search(query, k)` is too small to carry the real contract — snapshot, locale,
configuration, determinism, timeout behaviour, identity semantics and failure modes all
stay implicit inside it. It survives as an *internal* seam that both local retrievers and
the capture-replay adapter satisfy. What the evaluation module actually exposes is:

    evaluate(run_spec: RunSpec,
             catalog_snapshot: SnapshotRef,
             query_set: QuerySetRef) -> RunArtifact

    score(run_artifacts: list[RunArtifact],
          qrels: Qrels) -> Scorecard

`RunSpec` fully identifies the system and its configuration: model revisions, prompts,
fusion and truncation parameters, index build, code version. A `RunArtifact` that cannot
name what produced it has no business in a benchmark.

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

The ladder is an ablation, not a device for manufacturing a loser. Nothing here guarantees
that `Dense` underperforms `BM25` on exact brand and SKU queries — that is a hypothesis the
frozen experiment tests, and whatever it produces is what gets reported. A methodology that
sounds as though it *needs* a losing configuration undercuts the honesty it was meant to
demonstrate.

Every rung is scored, and every rung contributes its top-20 to the judgement pool (6.4).

## 6. Components

### 6.1 Ingestion and incremental sync
*Claim: a pipeline that runs twice without duplicating or losing anything.*

Shopify `products.json?limit=250&page=N`, paced 3s, every response cached by URL hash.
State keyed on `product_id`, carrying `first_seen`, `last_seen`, `deleted_at`, and **two
distinct hashes** rather than one:

- `source_payload_hash` — the complete source record, price and inventory included. Drives
  version history, so nothing the source sent is silently discarded.
- `enrichment_input_hash` — search-relevant fields only (title, body, tags, vendor,
  product_type, options, variant titles). Drives enrichment caching, so price churn does
  not re-pay for enrichment.

A single hash could not serve both purposes: excluding price kept enrichment cheap but
threw away source history.

| Run-2 outcome | Condition | Action |
|---|---|---|
| new | id unseen | insert version, enqueue enrichment |
| source-changed | `source_payload_hash` differs | new version row |
| enrichment-stale | `enrichment_input_hash` differs | new version row, enqueue enrichment |
| unchanged | both hashes match | touch `last_seen` only |
| disappeared | absent now | soft-delete, never hard-delete |

**Acceptance test:** run ingest twice back-to-back; assert **zero new product versions and
zero enrichment jobs**. Asserting "zero database updates" was wrong — an unchanged record
legitimately touches `last_seen`, so that assertion contradicted the very transition table
it was meant to verify.

**Pagination hazard:** page-based pagination is unstable under concurrent catalog edits.
The public endpoint offers no `since_id`, so mitigate by detection: assert id uniqueness
across pages, and **compare two consecutive complete crawl manifests**. Re-fetching page 1
proves only that page 1 is stable; it says nothing about whether the crawl as a whole saw a
consistent catalog. On mismatch, discard and re-crawl.

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
`enrichment_input_hash`, so a price change never re-pays for enrichment.

**Accuracy:** a human hand-labels ~150 products against the same taxonomy, blind to model
output. Sampling is **stratified by predicted value** wherever a field is imbalanced —
uniform random sampling of an imbalanced field measures the head and says nothing about the
tail.

Exact agreement is the wrong gate on its own. A field can score 0.85 while every rare
colour, material or category fails badly, and rare values are precisely what attribute
queries ask for. So the published figures are **coverage, per-value precision and recall,
and macro-F1** — macro, so a rare value counts as much as a common one.

**Threshold fixed in advance: macro-F1 < 0.70 disqualifies a field.** Disqualification is
total and enumerated: the field is excluded from hard filters, from facets, from BM25 field
weighting, and from answer-layer grounding. The earlier version disqualified a field only
as a "hard filter" while 6.3 kept feeding enriched category into BM25 and 6.5 kept building
facets from the same enums — so the gate disabled nothing. Setting the number and the
consequence before measuring is what makes this a test rather than a rationalisation.

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

**Truncation: two decisions, fitted separately, both on development data only.**

**1. Query-level no-match.** Before any ranking cutoff, decide whether the catalog can serve
this query at all. If it cannot, **return zero results.**

This is a **single threshold `T` on the maximum relevance score** across candidates — one
parameter, not a fitted classifier. The development split holds only 5 absent queries, and a
multi-feature classifier fitted on 5 positives would overfit so badly that the test result
would be noise. One parameter is what this data can support.

The wording is deliberate: **maximum relevance score, not `P(relevant)`.** Calling it a
probability asserts a calibration that nothing here establishes.

**Pre-registered selection rule, fixed before labeling:** `T` is the largest threshold
producing **at most 2 false abstentions across the 25 answerable development queries**, ties
broken toward the smaller `T`.

State this precisely: it is an **empirical development-set constraint of <=2/25, not
evidence that the population false-abstention rate is below 10%.** Twenty-five queries
cannot support that inference — the binomial interval around 2/25 is far too wide to exclude
much of anything — and the writeup describes it in exactly these terms. It is a reproducible
rule for picking a threshold, not a performance claim.

Largest-subject-to-a-budget rather than balanced accuracy, for two reasons: falsely
abstaining on a query the catalog *can* serve is worse for a shopper than over-returning on
one it cannot, and false abstention is observed on the larger class, so the constrained side
is the better-measured one.

**2. Result-level cutoff.** For queries that pass, a logistic regression maps reranker score
to a relevance estimate. **Whether that estimate may be called `P(relevant)` and cut at 0.5
depends on a calibration check it must pass first** — a reliability curve and Brier score on
development data, both published. If it calibrates, cut at 0.5 and call it a probability. If
it does not, the cut point is selected on development data by the same
largest-subject-to-a-budget rule, and the output is called a relevance score. Cap of 20
either way.

**There is no floor of one result.** An earlier version had one, which made abstention
impossible and left the correct-abstention metric in 6.4 measuring nothing at all — a system
forced to return something can never be scored on declining to.

**Both thresholds are selected on development data only. Test data is used exactly once, for
final evaluation.** Fitting a cutoff on the judgements it is then evaluated against is
leakage, and the most likely route to a suspiciously good number.

**The abstention sensitivity curve is reported, not selected from.** Correct-abstention and
false-abstention across a range of `T` tells a reader how much the result depends on where
the line was drawn, which is worth publishing. But it is published *after* `T` is fixed by
the pre-registered rule. Choosing `T` by reading that curve on test data would be exactly
the cherry-picking the sealed split exists to prevent.

**Metric consequence:** nDCG@20 cannot see padding. Truncation is therefore scored on a
set-based companion — F1 of the returned set against the judged relevant set, at each
system's own cutoff. Ranking quality and stopping quality are different questions.

**Expected failure case (to document, not tune away):** broad exploratory queries — `dam`,
`nyheter`, `jackor` — have genuinely large relevant sets, and a cutoff amputates them.

### 6.4 Labeling protocol and metrics
*The heaviest-weight component alongside truncation.*

**Query set:** ~70 queries, committed and git-tagged with a timestamp before the engine can
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

**Development / test split.** Freezing the query set stops query cherry-picking. It does
not stop tuning fusion weights, BM25 parameters, rerank depth, enrichment prompts or
truncation thresholds against results and labels you have already seen — which is the same
failure wearing a different hat, and the one that actually produces flattering headline
numbers.

So the ~70 queries are split into **30 development** and **40 test** at commit time,
before any labeling, using the asymmetric allocation below. Development judgements are visible, and are what
everything is tuned and calibrated against. **Test judgements stay sealed.** Every
`RunSpec` is frozen and every test `RunArtifact` is written and hashed *before* test
judgements are revealed. The headline table is computed once, from that frozen state.

If a bug forces a re-run after the seal is broken, the writeup says so and says what
changed. Breaking the seal quietly is the single failure this entire design exists to
prevent.

**The allocation is asymmetric, and fixed at commit time.** Spreading 40 test queries
evenly over eight strata leaves five each — too thin to support the two results the project
actually rests on. So the test split is weighted toward them:

| Stratum | Dev | Test | Role |
|---|---|---|---|
| compound | 4 | **10** | primary hypothesis 1 |
| adversarial / absent | 5 | **10** | primary hypothesis 2 |
| exact / brand | 4 | 4 | descriptive |
| cross-language | 3 | 4 | descriptive |
| category | 4 | 3 | descriptive |
| attribute | 4 | 3 | descriptive |
| natural language | 3 | 3 | descriptive |
| misspelling | 3 | 3 | descriptive |
| **total** | **30** | **40** | |

Among the six non-primary strata, exact/brand and cross-language take the extra query each:
exact/brand is where the lexical-versus-dense tradeoff is expected to surface, and
cross-language is a named section 8 deliverable that requires a matched-language control.

**Pre-registered primary hypotheses.** Two, named before any labeling, with their metrics
fixed in advance:

1. **The compound mechanism.** `BM25+Compound` − `BM25` on compound queries, primary metric
   **paired pooled-Recall@20**. Recall rather than nDCG because the claim is about
   *reaching* documents that conventional stemming cannot, not about ordering them.

2. **Balanced abstention** — *pre-registered but exploratory.* The no-match decision is
   judged on both halves together: correct-abstention rate on absent queries **and**
   false-abstention rate across all answerable queries. Reported as a pair, never
   separately — correct abstention alone rewards a system that refuses everything, which is
   the degenerate solution this metric exists to catch.

   **This result is descriptive, not confirmatory.** Ten absent test queries, with a
   threshold chosen from five development positives, cannot support a confirmatory claim,
   and the writeup will not make one. Pre-registering it is still worth doing: fixing the
   metric and the selection rule in advance prevents metric-shopping after the fact, even
   where the sample is too small to conclude anything. Pre-registration and confirmatory
   status are separable, and conflating them is how underpowered results get oversold.

**Pre-registration buys honesty, not statistical power.** At n=10 per primary stratum these
are still small samples. Effect sizes and intervals are reported; significance is not
promised, claimed, or implied. Hypothesis 1 is the only result treated as confirmatory, and
even it is reported as an effect size with an interval rather than as a significance test.
**Hypothesis 2 and every other stratum are explicitly descriptive** — point estimates,
labeled as such, carrying no inferential claim.

**Pooling:** union the **top-20 from every scored system** per query, deduplicate, strip
provenance, shuffle with a seed derived from the query id. The labeler sees a flat list —
no system, no rank.

**Pool depth is 20, and equals both the truncation cap and the deepest reported metric.**
An earlier version pooled to depth 10 while reporting Recall@20, leaving ranks 11-20 of
every *current* system unjudged and silently scored as irrelevant — not a hypothetical
future-system problem but a live defect in the headline number.

**Every scored system contributes. No exceptions.** A later revision briefly restricted
contributors to four "mechanically diverse" systems to halve labeling cost. That reasoning
was self-defeating. Deduplication already makes overlap free, so a heavily-overlapping
system costs almost nothing to include; and a system contributing *many* unique documents
is contributing precisely the documents that most need judging. The saving only
materialises in exactly the case where the exclusion does the most damage.

Concretely it would have sabotaged primary hypothesis 1. `BM25+Compound` exists to reach
documents conventional stemming cannot, so its finds are unique to it almost by definition.
Excluding it would have left those documents unjudged and scored them irrelevant —
measuring the compound mechanism as weaker than it is, through a defect introduced by the
measurement itself.

`Hybrid+Rerank+Truncate` is the one system that provably adds nothing: its output is a
prefix of `Hybrid+Rerank`'s by construction rather than by empirical overlap. It contributes
anyway, because dedup makes doing so free.

**Volume:** six mechanically distinct systems at depth 20 yield roughly 50-65 unique
products per query. Across 70 queries that is **~3,500-4,500 judgements, 7-9 hours.** This
is the third upward revision of this estimate, and it is the honest cost of a pool deep
enough and wide enough to support the metrics computed from it.

**Rubric:** graded 0-3. 3 = what was asked for; 2 = valid substitute satisfying the intent;
1 = related but wrong; 0 = irrelevant. Written with worked examples and committed before
labeling begins.

**Self-labeling bias:** the builder is also the labeler. Blind pooling handles provenance,
not personal opinion or drift. Mitigation: re-label a 10% random subsample after a gap of
days and **publish intra-annotator agreement (Cohen's kappa) against yourself.** That figure
is a hard ceiling on how much precision anyone should read into the comparison.

**Pooling's residual bias, disclosed:** a product no system retrieved is never judged, and
would be scored irrelevant if a future system found it.

**Metrics:** nDCG@10 (ranking), **Recall@20 against pooled qrels** (finding), F1 at each
system's own cutoff (stopping), correct-abstention rate (adversarial stratum).

**"Recall" means recall against the pooled judgement set, never exhaustive catalog
recall**, and is labeled that way everywhere it appears — table headers included. No pooled
evaluation can measure the latter without judging the entire catalog against every query.

**Statistics.** Independent per-system confidence intervals answer the wrong question. The
comparison is *paired* — every system answers the same queries — so the headline figures
are **bootstrapped paired per-query differences** between systems, stratified by query
type. The difference and its interval are reported directly, rather than two overlapping
intervals left for the reader to eyeball.

**Stratum weighting is fixed in advance.** The headline score weights the eight strata
equally *by stratum*, not by query count — otherwise adding three more compound queries
silently changes what the benchmark optimises for. Per-stratum figures are reported
alongside, since that is where the findings actually live.

Effect sizes and intervals are what the table reports. At these sample sizes many
differences will not reach significance; the table shows that plainly rather than hiding it
behind point estimates, and nothing outside the two pre-registered hypotheses carries an
inferential claim at all.

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
    artifacts/    COMMITTED: query set + split, qrels, taxonomy, prompts, every
                  RunSpec and RunArtifact, scorecard, model revisions, env lock
    data/         RETAINED PRIVATELY, git-ignored: raw catalog snapshot,
                  captured native responses
    docs/         methodology, limitations, the writeup

### What "reproducible" is allowed to mean here

Committing a hash while git-ignoring the bytes lets a reader verify a file they already
possess and reconstruct nothing. Once the storefront changes, the benchmark becomes
unrebuildable and the hash proves only that something once existed. The earlier version of
this spec made exactly that mistake.

Hence the split above. **Everything the project itself produces is committed** — query set
and split, qrels, taxonomy, prompts, every `RunSpec` and `RunArtifact`, the scorecard,
model revisions and the environment lock. That is enough to recompute every number in the
table offline, with no network and no storefront access.

**The raw catalog snapshot and captured native responses are retained but not
republished**, because they are the merchant's data and invariant 7 governs them. The
consequence is stated rather than finessed: **the metric computation is publicly
reproducible; the crawl is not. The scorecard is auditable from a retained private
snapshot.** Anyone who wants to inspect the snapshot can ask.

## 8. Build order and submittable checkpoints

Timeline is open-ended, which makes silence the live risk. Each checkpoint is a point where
the work could be sent as-is.

1. **Query set + rubric committed and timestamped; dev/test split and stratum allocation fixed; two primary hypotheses pre-registered.** Invariant 3 becomes structurally true.
2. **Ingestion + sync, twice-run test passing.** First defensible claim.
3. **Enrichment + human accuracy sample (per-field macro-F1).** First published number.
4. **Development labeling; ladder tuned and calibrated against dev only.**
5. **RunSpecs frozen, test RunArtifacts written and hashed, then the test seal is broken -> the comparison table.** *Submittable: this is the project.*
6. **Truncation successes and failure case documented.**
7. **Deployment + latency/cost table.**
8. **The writeup.**

## 9. Disclosures to publish (invariant 5)

- We tuned on the catalog we benchmark.
- Our system is specialised; the comparison is general-purpose.
- The builder is the labeler; intra-annotator agreement is published as the ceiling.
- Pooling cannot judge what no system retrieved. Every scored system contributes its top-20,
  so no system is disadvantaged relative to another.
- Only two hypotheses are pre-registered, and only one of them is confirmatory. Every other
  stratum is descriptive and carries no inferential claim; at n=3-4 per descriptive stratum,
  none could.
- The abstention result is descriptive: 10 absent test queries, with a threshold chosen from
  5 development positives, cannot support a confirmatory claim.
- A relevance score is called a probability only where a published calibration check
  supports it.
- Reported recall is recall against pooled qrels, never exhaustive catalog recall.
- The baseline is a black box. Exact snapshot equality with our crawl cannot be proven —
  only audited for overlap and disclosed.
- The crawl is not publicly reproducible; the scorecard is auditable from a retained
  private snapshot.
- At 40 test queries, many differences are not statistically significant.

## 10. Open questions

- Anchor storefront unconfirmed (Zoovillage pending overlay + language verification).
- English-language Nordic storefront unfilled.
- Depict reference store unfilled.
- Public-demo product imagery: hotlink from the merchant CDN, or omit images entirely.
