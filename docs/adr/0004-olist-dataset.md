# ADR-0004 — Brazilian Olist as the primary dataset

- **Status**: Accepted
- **Date**: 2026-05-08
- **Tags**: dataset, retail, e-commerce

## Context

The project is "AWS pipeline + Power BI dashboard". The dataset choice is not architectural in the AWS sense — but it determines:

1. The **narrative** of the dashboard (what KPIs make sense to compute).
2. The **shape of the data** (number of tables, joins, type complexity).
3. The **realism** of the demonstration (a recruiter senses immediately whether a project uses fake or real data).
4. The **alignment with Marianela's CV** (8 years in retail at Musimundo).

The dataset will be downloaded once from Kaggle, ingested to S3, and processed through the medallion pipeline. It does not need to be fresh, streamed, or live.

## Pre-decision review

- **Failure mode in 6 months**: Kaggle removes the dataset, or the license changes to something incompatible with portfolio use. Mitigation: download once, version the raw archive in our own S3 bucket; from that moment we are independent of Kaggle availability.
- **Prior art and divergence**: Olist is one of the **most popular** datasets in BI/data portfolio projects. We are explicitly not diverging — we are choosing a known-good signal that recruiters parse easily. The risk of "another Olist project" is real and addressed in the consequences.
- **Cost of reversal**: days. The pipeline architecture is dataset-agnostic; swapping Olist for, say, the UCI Online Retail dataset means rewriting the staging/curated transformations but reusing 100% of the AWS infra.
- **Early warning signal**: in the first 2 weeks of building, "this dataset doesn't have a column I need to compute KPI X" — that's the trigger to either compute X with what we have or pick a richer dataset.

## Decision

We will use the **Brazilian E-Commerce Public Dataset by Olist**, published on Kaggle at `olistbr/brazilian-ecommerce`. It contains ~100,000 orders placed between 2016 and 2018 across multiple Brazilian marketplaces, anonymised, in 9 related CSV tables: `orders`, `order_items`, `order_payments`, `order_reviews`, `customers`, `sellers`, `products`, `geolocation`, `product_category_name_translation`.

To compensate for the "another Olist" risk and add a real "multi-source" element, we will **enrich** the data with one external source: historical exchange rates from BRL to USD (and EUR), pulled from a free API (e.g., Frankfurter or exchangerate.host). This produces a `dim_currency` dimension and lets the dashboard show revenues in the currency of the viewer.

## Consequences

### Positive

- **Real, anonymised, 9-table relational structure.** Joins are non-trivial; orders ↔ items ↔ products ↔ sellers ↔ payments ↔ reviews ↔ customers all matter to compute interesting KPIs.
- **Aligns with Marianela's CV.** 8 years in retail, AWS Personalize on a customer base of millions — the dashboard can compute exactly the kind of KPIs she has shipped before (RFM, cohort retention, geographical breakdown, NPS from reviews, payment-method mix, freight efficiency).
- **Recruiter-recognisable.** A BI Lead who looks at the dashboard immediately understands what they are seeing without reading a 5-paragraph README.
- **License-clean for portfolio.** Published under CC BY-NC-SA 4.0 — non-commercial portfolio use is explicitly permitted, attribution is straightforward.
- **Stable.** The dataset is a snapshot of 2016–2018; it will not change under us.

### Negative

- **Heavily used in portfolios.** A recruiter who screens five "AWS data engineer" portfolios in a row may see five Olist projects. Mitigation: the **architecture story** (medallion + Glue + Athena + Power BI MCP) is what differentiates; the dataset is the substrate, not the showcase. Plus the FX-enrichment makes it visibly a step beyond "I downloaded one CSV".
- **Static dataset.** No real demonstration of "incremental pipeline" because all 100k orders arrive in one batch. **Mitigation:** the ingestion module simulates incremental loads by partitioning the upload by `order_purchase_timestamp` month, so the staging→curated steps process partition-by-partition as if data were arriving over time. The narrative in the README explicitly addresses this.
- **Portuguese product categories.** The dataset is Brazilian; product category names are in Portuguese. The `product_category_name_translation` table maps to English. We will use English in the curated layer.
- **No PII exposure** (data is anonymised). This is a pro, not a con — but it means we cannot demonstrate, say, GDPR-compliant pseudonymisation. **Honest production delta**: in a real-world dataset that demonstration is valuable; here, it is not necessary.

### Neutral / open questions

- Whether to add a second enrichment (e.g., Brazilian holidays calendar, weather data for the order date) is deferred. Single FX enrichment is enough to demonstrate the pattern; more is scope creep.
- The FX rates API has a rate limit. Our usage (one call per unique date, ~700 dates over the dataset) is well within free-tier limits, but we cache results to a `dim_currency.parquet` so we don't hit the API on every run.

## Alternatives considered

### NYC TLC Trip Records

The classic. 1+ TB of taxi rides, hosted on AWS Open Data so the ingestion is "S3 to S3" instead of "external to S3". **Rejected because** the dataset is over-saturated in portfolios (Olist is popular; NYC TLC is *the* default), the schema is narrow (one fact, no real dimensional joins), and it does not align with Marianela's retail CV. A "BI Lead from retail" showing taxi data is a weaker narrative.

### UCI Online Retail Dataset

Real UK e-commerce, ~500k transactions over 1 year. **Rejected because** it is a single flat CSV — no relational structure to model, no joins to demonstrate. The dashboard would be impressive but the pipeline would be trivial (no real medallion benefit when there's only one table). Also smaller (~40 MB), less interesting.

### CARSA / Musimundo data, anonymised by Marianela

Real data from her actual job, anonymised. **Rejected immediately** — the data is property of the employer, NDA likely applies, and even with anonymisation the legal and reputational risk is unacceptable for portfolio.

### Synthetic data generated with `sdv` or `faker`

Statistically realistic, fully owned, no license issues. **Rejected because** synthetic data does not fool a BI Lead reviewer. The "real data" tells; an experienced reviewer recognises the distributional weirdness of generated data within seconds. Synthetic data has its place (privacy-sensitive demos) but not for portfolio-vs-real-jobs comparison.

### AWS Open Data registry (any)

Many candidates: NOAA weather, Sentinel imagery, Common Crawl, etc. **Rejected because** none of them maps to "BI Lead in retail looking for jobs in Madrid". A clever portfolio piece on weather data would showcase data engineering but not the BI value-prop Marianela is selling.

### Multiple datasets combined

E.g., Olist + Spotify charts + GitHub PR data, demonstrating a true federation. **Rejected as scope creep** — the goal is one solid, well-narrated pipeline, not three thin ones.

## References

- [Brazilian E-Commerce Public Dataset by Olist on Kaggle](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)
- [Frankfurter API](https://www.frankfurter.app/) — free FX history with no key
- [Olist license: CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)
- Related: ADR-0002 (the medallion that this dataset flows through).
