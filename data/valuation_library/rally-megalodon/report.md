# Megalodon Jaw
## Rally Terminal Valuation Report

**Asset ID:** `rally-megalodon`  
**Valuation date:** 2026-08-10  
**Methodology:** Rally Terminal valuation methodology v1.0 / `fossils_v1`  
**Valuation status:** `completed_with_limitations`  
**Confidence:** **75%**

---

## Valuation Summary

| Scenario | Fair Value |
|---|---:|
| Conservative | **$62,500** |
| Base | **$62,500** |
| Optimistic | **$74,500** |

Rally Terminal's base fair value for the Megalodon jaw is **$62,500**. The valuation is supported by **two eligible, verified reconstructed-jaw comparables**. The weighted comparable mean is **$68,247**, while the engine-selected base value is the weighted median of **$62,500**.

Comparable dispersion is approximately **19.2%**, which is well below the methodology's 75% extreme-dispersion threshold. The engine therefore did **not** apply an extreme-dispersion penalty.

The narrow $62,500-$74,500 valuation range should not be interpreted as unusually high certainty. It is largely a consequence of having only two direct realized-sale comparables and of the current `fossils_v1` model using neutral adjustment multipliers.

---

## Market Comparison

- **Initial Rally offering value:** $600,000
- **Last observed Rally market value:** $178,500
- **Base fair value:** $62,500
- **Discount to initial offering value:** **-89.6%**
- **Discount to last observed market value:** **-65.0%**

The model therefore places fair value materially below both Rally's original offering valuation and the latest observed secondary-market value.

This result should be treated cautiously. The subject is a very large composite fossil display containing **184 fossil teeth**, while the two direct comparables contain **138 teeth**. The current engine recognizes that mismatch in its warnings but does **not** presently apply a quantitative premium for the larger tooth count, unusually large constituent teeth, display dimensions, preparator reputation, or a sum-of-parts tooth valuation.

---

## Subject Asset

The subject is a reconstructed Megalodon jaw display consisting of **184 fossilized Megalodon teeth** mounted within a resin reconstruction. Rally's supplied materials identify:

- Taxon: **Otodus megalodon**  
- Legacy taxonomy used in offering materials: **Carcharocles megalodon**
- Excavation site: **Morgan River, Georgia**
- Presentation: **Mounted in a resin reconstruction**
- Dimensions: **8 ft x 9.5 ft**
- Number of fossil teeth: **184**
- Four stated teeth measuring approximately **6.25 inches each**
- Initial Rally offering value: **$600,000**

The offering materials indicate that the teeth were accumulated over time from multiple source organisms and arranged to recreate the dentition of a living Megalodon. Accordingly, the asset is best treated as a **composite fossil display**, not as a naturally associated fossilized jaw.

---

## Comparable Sales

### MEGALODON-COMP-001

**Realized value:** **$62,500**  
**Auction house:** Heritage Auctions  
**Sale date:** 2012-05-20  
**Evidence quality:** 0.99  
**Overall similarity:** 0.84  
**Final weight:** **52.1%**

This is a reconstructed Megalodon jaw containing **138 fossil teeth**. It is a strong category and presentation match, though the subject contains 46 additional teeth and may therefore have materially greater aggregate fossil content.

Key limitations:

- 138 teeth versus the subject's 184
- Subject restoration extent is unknown
- The current model does not explicitly monetize the larger tooth count

### MEGALODON-COMP-002

**Realized value:** **$74,500**  
**Auction house:** Bonhams  
**Sale date:** 2013-05-22  
**Evidence quality:** 0.91  
**Overall similarity:** 0.84  
**Final weight:** **47.9%**

This is another reconstructed Megalodon jaw containing **138 fossil teeth** and provides a second strong direct whole-object market anchor.

Key limitations:

- 138 teeth versus the subject's 184
- Buyer-premium treatment is not fully normalized
- Realized-price confirmation relies partly on a secondary source
- Subject restoration extent is unknown

---

## Comparable Diagnostics

| Comparable | USD Price | Similarity | Evidence Quality | Final Weight |
|---|---:|---:|---:|---:|
| MEGALODON-COMP-001 | $62,500 | 0.84 | 0.99 | 52.1% |
| MEGALODON-COMP-002 | $74,500 | 0.84 | 0.91 | 47.9% |

Both comparables passed the engine's eligibility thresholds and were included in the official valuation.

---

## Methodology Interpretation

This valuation exposes an important limitation of the current fossils methodology.

The engine is presently functioning primarily as a **whole-object comparable-sales model**. For ordinary fossils, that can be reasonable. For this asset, however, a large portion of economic value may reside in the **individual constituent teeth**.

The subject contains **184 fossil teeth**, compared with 138 in each direct comparable. It also reportedly contains four teeth measuring approximately **6.25 inches**, which may be unusually valuable if they are authentic, minimally restored, aesthetically strong, and well documented.

Yet the current engine applies:

- time adjustment: 1.0
- condition adjustment: 1.0
- rarity adjustment: 1.0
- provenance adjustment: 1.0
- liquidity adjustment: 1.0
- market adjustment: 1.0

In other words, the model currently sees the subject's superior tooth count but does not translate it into a valuation premium.

That makes the **$62,500 base value best interpreted as a direct-comparable floor or baseline**, not necessarily a complete appraisal of the asset's economic value.

---

## Recommended Secondary Valuation Method

For composite fossil displays such as reconstructed shark jaws, Rally Terminal should eventually supplement the whole-object comparable method with a **sum-of-parts model**.

A stronger methodology would estimate:

1. Value distribution of the 184 individual teeth
2. Premium attributable to the largest teeth
3. Restoration discounts by tooth
4. Provenance and locality premiums
5. Assembly / preparator premium
6. Display-scale premium
7. Whole-object liquidity discount
8. Cross-check against reconstructed-jaw auction sales

Conceptually:

**Composite Fair Value ≈ Tooth Portfolio Value + Assembly Premium - Liquidity Discount**

The current report does not calculate this secondary estimate because the supplied valuation engine does not yet contain that framework.

---

## Key Risks and Limitations

- Only **two** strong direct reconstructed-jaw sales were available.
- Both direct comparables are from **2012-2013**.
- The subject's individual tooth condition and restoration profile are not documented.
- The current model does not explicitly value tooth count or maximum tooth size.
- The current model does not assign a premium for preparator reputation.
- The resin jaw itself is a reconstruction rather than fossilized anatomical jaw material.
- Rally's original **$600,000** valuation remains difficult to reconcile with the located whole-jaw auction evidence using the current methodology alone.
- Current whole-object liquidity may differ substantially from Rally fractional-market liquidity.

---

## Analyst Conclusion

The current `fossils_v1` engine produces a defensible **direct-comparable valuation range of $62,500-$74,500**, centered on a **$62,500 base case**.

However, this should not be read as a definitive conclusion that the Megalodon asset is worth only $62,500. The model's largest weakness is that it does not yet quantify the subject's most unusual characteristic: a **184-tooth, museum-scale composite display with several exceptionally large teeth**.

For that reason, this asset is a strong candidate for a future **composite-fossil / sum-of-parts valuation module**. Until such a framework exists, the direct-comparable output is useful as a conservative market anchor but is likely incomplete as a total-value model.

---

## Engine Warnings

- Category model is provisional and requires methodological review.
- Valuation completed with optional evidence limitations.

---

*Research and valuation analysis only. This report is not an appraisal and does not constitute investment advice.*
