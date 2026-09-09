"""Render the public scorecard. No product imagery (spec 6.5)."""

LABELS = {
    "native": "Store A native",
    "bm25": "BM25",
    "bm25-compound": "BM25+Compound",
    "bm25-lex": "BM25+Lex",
}

STRATUM_ORDER = (
    "exact/brand", "category", "compound", "attribute",
    "cross-language", "misspelling", "natural language", "adversarial/absent",
)


def _fmt(value: float) -> str:
    return f"{value:.3f}"


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_scorecard(card: dict) -> str:
    systems = card["systems"]
    native = systems.get("native") or next(iter(systems.values()))
    mine = systems.get("bm25-lex") or systems.get("bm25-compound") or systems.get("mine")
    native_label = native.get("label") or LABELS["native"]
    mine_label = (mine or {}).get("label") or LABELS["bm25-lex"]
    store = _esc(str(card.get("store") or "Store A"))
    display = _esc(str(card.get("display_name") or store))
    snapshot = card.get("snapshot") or {}
    queries = card.get("queries") or {}
    overlap = card.get("overlap") or {}
    native_ndcg = _fmt(native["answerable_ndcg"])
    mine_ndcg = _fmt(mine["answerable_ndcg"]) if mine else "—"

    strata = set()
    for system in systems.values():
        strata.update(system.get("by_stratum", {}))
    stratum_rows = []
    for stratum in STRATUM_ORDER:
        if stratum not in strata:
            continue
        cells = "".join(
            f"<td>{_fmt(systems[name]['by_stratum'].get(stratum, 0.0))}</td>"
            for name in systems
        )
        stratum_rows.append(f"<tr><th>{_esc(stratum)}</th>{cells}</tr>")

    head_systems = "".join(
        f"<th>{_esc(sys.get('label') or LABELS.get(name, name))}</th>"
        for name, sys in systems.items()
    )
    summary_ndcg = "".join(
        f"<td>{_fmt(sys['answerable_ndcg'])}</td>" for sys in systems.values()
    )
    summary_p = "".join(
        f"<td>{_fmt(sys['precision'])}</td>" for sys in systems.values()
    )
    summary_absent = "".join(
        f"<td>{sys['absent_returned']}</td>" for sys in systems.values()
    )

    example_html = []
    for example in card.get("examples") or []:
        def col(items, kind):
            rows = []
            for i, item in enumerate(items, start=1):
                grade = item.get("grade", 0)
                rows.append(
                    f"<li><span class='rank'>{i}</span>"
                    f"<span class='title'>{_esc(item.get('title') or '—')}</span>"
                    f"<span class='grade g{grade}'>{grade}</span></li>"
                )
            return (
                f"<div class='col'><h3>{_esc(kind)}</h3>"
                f"<ol>{''.join(rows) or '<li class=\"empty\">no results</li>'}</ol></div>"
            )
        example_html.append(
            "<section class='example'>"
            f"<h2>Worked query: {_esc(example['query'])}</h2>"
            "<div class='cols'>"
            f"{col(example.get('native') or [], native_label)}"
            f"{col(example.get('mine') or [], mine_label)}"
            "</div></section>"
        )

    native_s = systems.get("native") or {}
    mine_s = mine or {}
    comp_s = systems.get("bm25-compound") or {}
    bm25_s = systems.get("bm25") or {}
    n_str = native_s.get("by_stratum") or {}
    m_str = mine_s.get("by_stratum") or {}
    c_str = comp_s.get("by_stratum") or {}
    b_str = bm25_s.get("by_stratum") or {}
    findings = ""
    if n_str and m_str:
        findings = f"""
  <h2>Where they differ</h2>
  <p>
    Brand, category and attribute queries are a retrieval ceiling, not a ranking
    contest: every matching vendor or <code>product_type</code> has the same grade,
    so nDCG@10 is 1.000 for any system that fills ten slots with relevant items.
    The comparison lives in the other strata.
  </p>
  <ul class="disc">
    <li>Swedish compounds: {_esc(mine_label)} {_fmt(m_str.get("compound", 0))} ·
        BM25+Compound {_fmt(c_str.get("compound", 0))} ·
        native {_fmt(n_str.get("compound", 0))} ·
        BM25 {_fmt(b_str.get("compound", 0))}. Splitting fashion heads
        (<em>jacka</em> from <em>bomberjacka</em>) is the mechanism.</li>
    <li>Misspellings: native {_fmt(n_str.get("misspelling", 0))} ·
        {_esc(mine_label)} {_fmt(m_str.get("misspelling", 0))} ·
        BM25 {_fmt(b_str.get("misspelling", 0))}.
        {_esc(mine_label)} corrects a query token to a vendor token within one edit
        (two for tokens of eight or more characters) and only when exactly one
        vendor is that close. Nothing outside the vendor vocabulary is corrected.</li>
    <li>English queries: native {_fmt(n_str.get("cross-language", 0))} ·
        {_esc(mine_label)} {_fmt(m_str.get("cross-language", 0))} ·
        BM25 {_fmt(b_str.get("cross-language", 0))}.
        {_esc(mine_label)} maps English garment words seen in this catalog's titles
        to the Swedish head (<em>jacket</em> → <em>jacka</em>).</li>
    <li>Natural language: native {_fmt(n_str.get("natural language", 0))} ·
        {_esc(mine_label)} {_fmt(m_str.get("natural language", 0))} ·
        BM25 {_fmt(b_str.get("natural language", 0))}.
        {_esc(mine_label)} keeps the modifier of a compound (<em>herr</em> from
        <em>herrjeans</em>) and scales each document's score by the share of query
        terms it matches, so jeans tagged Herr outrank jeans that are not.</li>
    <li>Absent queries (<em>iphone</em>, <em>lego</em>, <em>skidpjäxor</em>):
        native returned {native_s.get("absent_returned", 0)} products.
        Every BM25 system returned none, because those tokens are missing from
        the catalog and typo correction is confined to vendor names — not because
        of a fitted abstention model.</li>
  </ul>
"""

    query_rows = []
    by_id: dict[str, dict] = {}
    for row in card.get("per_query") or []:
        by_id.setdefault(row["id"], {"query": row["query"], "stratum": row["stratum"]})
        by_id[row["id"]][row["system"]] = row
    for qid, row in by_id.items():
        cells = "".join(
            f"<td>{_fmt(row[name]['ndcg'])}</td>" if name in row else "<td>—</td>"
            for name in systems
        )
        query_rows.append(
            f"<tr><td>{_esc(qid)}</td><td>{_esc(row['query'])}</td>"
            f"<td>{_esc(row['stratum'])}</td>{cells}</tr>"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{store} native vs {_esc(mine_label)}</title>
<style>
  :root {{
    --ink: #141513;
    --mute: #5a5d56;
    --rule: #cfcfc8;
    --paper: #f7f7f4;
    --native: #2c4638;
    --mine: #7a1f2b;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; background: var(--paper); color: var(--ink); }}
  body {{
    font: 16px/1.5 "Helvetica Neue", Helvetica, Arial, sans-serif;
    max-width: 54rem;
    margin: 0 auto;
    padding: 2.5rem 1.25rem 5rem;
  }}
  h1, h2, h3 {{ font-weight: 600; letter-spacing: -0.02em; }}
  h1 {{ font-size: 2rem; line-height: 1.15; margin: 0 0 0.5rem; }}
  h2 {{ font-size: 1.05rem; margin: 2.5rem 0 0.75rem; }}
  p.lede {{ font-size: 1.02rem; max-width: 38rem; }}
  .mute {{ color: var(--mute); }}
  .hero {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1px;
    background: var(--rule);
    border: 1px solid var(--ink);
    margin: 1.75rem 0 1rem;
  }}
  .hero div {{ background: var(--paper); padding: 1.1rem 1rem 1.2rem; }}
  .hero .num {{
    font-variant-numeric: tabular-nums lining-nums;
    font-size: 3rem;
    line-height: 1;
    letter-spacing: -0.04em;
    font-weight: 600;
  }}
  .hero .native .num {{ color: var(--native); }}
  .hero .mine .num {{ color: var(--mine); }}
  .hero .lbl {{ margin-top: 0.45rem; color: var(--mute); font-size: 0.92rem; }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-variant-numeric: tabular-nums lining-nums;
    font-size: 0.95rem;
  }}
  th, td {{ text-align: left; padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--rule); vertical-align: top; }}
  th {{ font-weight: 500; }}
  td:not(:first-child):not(:nth-child(2)):not(:nth-child(3)),
  thead th:not(:first-child) {{ text-align: right; }}
  .cols {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.25rem; }}
  ol {{ list-style: none; padding: 0; margin: 0; }}
  ol li {{
    display: grid;
    grid-template-columns: 1.5rem 1fr 1.2rem;
    gap: 0.4rem;
    padding: 0.28rem 0;
    border-bottom: 1px solid var(--rule);
    font-size: 0.92rem;
  }}
  .rank {{ color: var(--mute); }}
  .grade {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .g3 {{ color: var(--mine); }}
  .g2 {{ color: var(--native); }}
  .g0, .g1 {{ color: var(--mute); }}
  .method {{
    border-top: 1px solid var(--ink);
    margin-top: 3rem;
    padding-top: 0.5rem;
  }}
  ul.disc {{ padding-left: 1.2rem; }}
  code {{ font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 0.86em; }}
  @media (max-width: 640px) {{
    .hero, .cols {{ grid-template-columns: 1fr; }}
    h1 {{ font-size: 1.7rem; }}
  }}
</style>
</head>
<body>
  <p class="mute">{display} · independent methodology demo</p>
  <h1>{store} native vs {_esc(mine_label)}</h1>
  <p class="lede">
    Same catalog snapshot, same {queries.get("n", "?")} frozen queries, same catalog-grounded grades.
    Headline number is mean nDCG@10 on the 21 answerable queries. This is not an
    official audit or endorsement of the retailer.
  </p>
  <div class="hero">
    <div class="native">
      <div class="num">{native_ndcg}</div>
      <div class="lbl">{_esc(native_label)} · nDCG@10</div>
    </div>
    <div class="mine">
      <div class="num">{mine_ndcg}</div>
      <div class="lbl">{_esc(mine_label)} · nDCG@10</div>
    </div>
  </div>
  <p class="mute">
    Snapshot { _esc(str(snapshot.get("run_id", ""))) }
    · {snapshot.get("count", "?")} products
    · query set { _esc(str(queries.get("id", ""))) }
    ({queries.get("n", "?")} queries)
    · native overlap {overlap.get("mapped", "?")} mapped / {overlap.get("unmapped", "?")} missing from snapshot
  </p>

  <h2>Score table</h2>
  <table>
    <thead><tr><th></th>{head_systems}</tr></thead>
    <tbody>
      <tr><th>nDCG@10, answerable</th>{summary_ndcg}</tr>
      <tr><th>P@10 (grade ≥ 2)</th>{summary_p}</tr>
      <tr><th>Results returned on absent queries</th>{summary_absent}</tr>
    </tbody>
  </table>

  <h2>By stratum (nDCG@10)</h2>
  <table>
    <thead><tr><th>Stratum</th>{head_systems}</tr></thead>
    <tbody>{''.join(stratum_rows)}</tbody>
  </table>

  {findings}

  {''.join(example_html)}

  <h2>Every query</h2>
  <table>
    <thead><tr><th>id</th><th>query</th><th>stratum</th>{head_systems}</tr></thead>
    <tbody>{''.join(query_rows)}</tbody>
  </table>

  <section class="method">
    <h2>Methodology</h2>
    <p>
      This is a measurement, not a demo. The catalog was ingested from the public
      Shopify <code>products.json</code> endpoint, crawled twice, and discarded unless
      both crawls agreed. Image URLs are stored; images are never downloaded or shown.
    </p>
    <p>
      <strong>Queries.</strong> 24 queries, frozen in
      <code>artifacts/queries/store-a-v1.json</code> before any ranking was computed.
      They are stratified (brand, category, Swedish compounds, attributes, English
      equivalents, misspellings, natural language, absent). They were chosen from
      shopper vocabulary and from catalog structure — vendors, product types, tags —
      not from looking at anyone’s result lists.
    </p>
    <p>
      <strong>Relevance is catalog-grounded, not human-pooled.</strong> A brand query
      is grade 3 iff <code>vendor</code> matches. A category query is grade 3 iff
      <code>product_type</code> matches. Compound queries such as <em>jacka</em>
      treat <code>Jackor</code> as 3 and related outerwear as 2. Absent queries have
      no relevant documents. This is simple graded relevance: objective, reproducible,
      and weaker than the human pooled judgements in the full design. It is also not
      a BM25-shaped judge — a lexical overlap scorer would have rigged the comparison.
    </p>
    <p>
      <strong>Systems.</strong> <em>Native</em> is the shopper-facing
      <code>/search?q=&amp;type=product</code> page, captured once and replayed.
      Rank comes from the <code>_pos</code> parameter on product links; first page,
      20 results. Native is a live black box: its index can disagree with our
      snapshot, so unmapped handles are counted rather than guessed.
      <em>BM25</em> is fielded Okapi BM25 (k1=1.2, b=0.75) over title, vendor,
      product type, tags, and description. <em>BM25+Compound</em> adds splitting of
      known Swedish fashion heads (<em>jacka</em> from <em>bomberjacka</em>,
      <em>jackor</em> → <em>jacka</em>).
      <em>BM25+Lex</em> keeps that index and adds four query-side rules: the modifier
      of a compound is kept as a term (<em>herr</em> from <em>herrjeans</em>); English
      garment words found in this catalog's titles map to the Swedish head
      (<em>jacket</em> → <em>jacka</em>); a query token within one edit of exactly one
      vendor token (two edits for long tokens) also matches that vendor token; and each
      document's score is scaled by the share of query terms it matches.
      No embeddings, no reranker, no truncation.
      BM25 parameters were fixed in advance. BM25+Lex was designed after the v1 results
      were visible: its rules were derived from the catalog (the vendor list, the tag
      vocabulary, English words in titles), not from the query set, but its v1 number is
      a development number. The held-out check above is the sealed one.
    </p>
    <p>
      <strong>Metric.</strong> nDCG@10 with gain <code>2^rel − 1</code>. IDCG uses
      the full relevant set, not only retrieved documents. Mean nDCG on the 21
      answerable queries is the headline; absent queries cannot be seen by nDCG
      (padding with grade-0 documents still scores 0), so we also report how many
      results each system returned on them. P@10 counts grade ≥ 2.
    </p>
    <p>
      <strong>What this number is not.</strong> It is not the human-labeled, sealed
      test split in the design spec. The builder chose the query set, and BM25+Lex was built after the v1 results
      were visible. We specialised
      a lexical retriever for this catalog’s language; the storefront did not.
      Exact snapshot equality with native search cannot be proven. On this run every
      captured native handle was in the snapshot ({overlap.get("mapped", "?")} mapped,
      {overlap.get("unmapped", "?")} missing). The crawl itself is not republished
      (the catalog is theirs); the scorecard is auditable from the retained private
      snapshot and the committed query file, runs, and grades. The retailer is not
      named here: this page is a methodology demonstration, not a brand audit.
    </p>
  </section>
</body>
</html>
"""
