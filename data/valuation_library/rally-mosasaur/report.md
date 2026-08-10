# Mosasaur Skeleton
## Rally Terminal Valuation Report

**Asset ID:** `rally-mosasaur`  
**Valuation date:** 2026-08-10  
**Methodology:** Rally Terminal valuation methodology v1.0 / fossils_v1  
**Valuation status:** completed_with_limitations  
**Confidence:** 55%

---

## Valuation Summary

| Scenario | Fair Value |
|---|---:|
| Conservative | **$3,597** |
| Base | **$3,597** |
| Optimistic | **$11,290** |

Rally Terminal's current base fair value estimate for the Mosasaur skeleton is **$3,597**. The model identifies **3 eligible verified comparables**, with a weighted comparable mean of **$11,738** and a weighted-median base value of **$3,597**.

This output should be treated cautiously. Comparable dispersion is exceptionally high at **730.6%**, far above the methodology's 75% extreme-dispersion threshold. The fossil category model is also explicitly provisional.

---

## Market Comparison

| Metric | Value |
|---|---:|
| Initial offering value | **$30,000** |
| Last observed Rally market value | **$34,200** |
| Base fair value | **$3,597** |
| Fair value vs. initial offering | **-88.0%** |
| Fair value vs. last observed market value | **-89.5%** |
| Asset status | **Closed** |

Under the current model, the base valuation is dramatically below both the original Rally offering value and the last observed Rally market value.

That difference should not be interpreted as a clean statement that the Rally asset was mispriced. The present result is highly sensitive to the composition and weighting of a very small, heterogeneous comparable set.

---

## Comparable Sales

### MOSASAUR-COMP-001

**Adjusted USD price:** **$29,875**  
**Overall similarity:** **0.82**  
**Evidence quality:** **0.97**  
**Final weight:** **23.9%**  
**Verification:** Verified

This is one of the strongest available comparables by similarity. However, the accessible result did not establish specimen size, original-bone percentage, or restoration extent with enough precision to fully align it with the Rally subject.

Key warnings:

- original bone percentage unknown
- size not visible in accessible result
- subject restoration extent unknown

### MOSASAUR-COMP-002

**Adjusted USD price:** **$11,290**  
**Original reported price:** GBP 8,890  
**FX rate used:** 1.27 USD/GBP  
**Overall similarity:** **0.82**  
**Evidence quality:** **0.98**  
**Final weight:** **24.2%**  
**Verification:** Verified

This comparable also scores strongly on identity similarity, but again lacks sufficiently precise public evidence on size, restoration, and original-bone content.

Key warnings:

- FX conversion required
- original bone percentage unknown
- size not visible in accessible result
- subject restoration extent unknown

### MOSASAUR-COMP-003

**Adjusted USD price:** **$3,597**  
**Original reported price:** EUR 3,300  
**FX rate used:** 1.09 USD/EUR  
**Overall similarity:** **0.48**  
**Evidence quality:** **0.90**  
**Final weight:** **51.9%**  
**Verification:** Verified

This is the lowest-similarity comparable but receives the largest model weight because of its much stronger recency treatment. It is materially smaller than the Rally subject, was reconstructed, and was not species-specific in the accessible listing.

Key warnings:

- much smaller than subject
- reconstructed specimen
- not species-specific in accessible listing
- FX conversion required

This comparable is the principal reason the model's weighted median falls to **$3,597** despite the other two eligible comparables being approximately **$11,290** and **$29,875**.

---

## Calculation Diagnostics

The valuation engine parsed and retained all **3 of 3** research comparables. All three met the minimum evidence threshold and were included in the official valuation.

| Comparable | USD Price | Similarity | Evidence Quality | Final Weight |
|---|---:|---:|---:|---:|
| MOSASAUR-COMP-001 | $29,875 | 0.82 | 0.97 | 23.9% |
| MOSASAUR-COMP-002 | $11,290 | 0.82 | 0.98 | 24.2% |
| MOSASAUR-COMP-003 | $3,597 | 0.48 | 0.90 | 51.9% |

**Weighted comparable value:** $11,738  
**Weighted median comparable value:** $3,597  
**Dispersion:** 730.6%

The gap between the weighted mean and weighted median is unusually large and reflects the small sample size plus the heavy normalized weight assigned to the low-priced recent comparable.

---

## Methodology Interpretation

The current fossils model weights comparables using similarity, evidence quality, verification status, and recency. It does not presently apply explicit time, market, condition, rarity, provenance, or liquidity adjustment multipliers beyond 1.0.

For this asset, that design creates a notable methodological issue: **recency is overpowering specimen comparability**.

The EUR 3,300 reconstructed specimen has only **0.48 overall similarity**, yet receives approximately **52% of total weight** because its recency treatment is 1.0, while the two substantially stronger 0.82-similarity comparables are floored at a 0.25 recency treatment.

For a fossil skeleton, that may be economically inappropriate. Specimen-specific variables such as taxonomic identity, completeness, original-bone percentage, skull completeness, restoration and reconstruction, total mounted size, provenance, scientific importance, preparation quality, and display quality can matter far more than transaction recency alone.

This result therefore reads more as a **diagnostic of the current fossils methodology** than as a mature estimate of intrinsic value.

---

## Principal Risks and Limitations

The valuation carries a `completed_with_limitations` status for good reason.

The principal limitations are:

- only three eligible comparables were available
- comparable dispersion is extreme
- the fossil category model remains provisional
- original-bone percentage is not well established
- restoration extent is not fully known
- the strongest recent comparable is much smaller and reconstructed
- species-level comparability is incomplete
- historical foreign-currency transactions use configured static FX rates
- no explicit fossil-specific premiums or discounts are currently applied

The model therefore produces a mathematically valid result, but the economic interpretation remains fragile.

---

## Valuation Conclusion

### Current model output

**Conservative:** $3,597  
**Base:** $3,597  
**Optimistic:** $11,290  
**Confidence:** 55%

### Analytical interpretation

The present **$3,597 base value should not be treated as a robust standalone appraisal** of the Rally Mosasaur skeleton. The valuation is being pulled heavily toward a recent but substantially weaker comparable.

The stronger comparable evidence spans approximately **$11,000 to $30,000**, which is much closer to the asset's historical Rally valuation range. Before relying on the fossils model for additional assets, the weighting methodology should be reviewed so that severe differences in specimen completeness, scale, restoration, and taxonomic specificity cannot be overwhelmed by recency alone.

---

## Model Warnings

- Category model is provisional and requires methodological review.
- Extreme comparable dispersion.
- Valuation completed with optional evidence limitations.

---

*Rally Terminal research output. For research and analytical purposes only; not an appraisal or investment recommendation.*
