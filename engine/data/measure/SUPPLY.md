# Supply measurement

| Measure | Count |
|---|---:|
| Raw postings | 848 |
| Stage: early | 98 |
| Stage: unknown | 376 |
| Stage: senior | 374 |
| Early + unknown, technical | 288 |
| India-located among those | 26 |
| **Final: India + technical + (early or unknown)** | **26** |

Final breakdown: **early 0; unknown 26**. By platform: **Greenhouse 14, Lever 8, Keka 4**.

The old binary comparator was re-derived as “title contains an EARLY keyword.” It would retain **87/848 (10.3%)** raw rows. In the matched India+technical final scope it retains **0**, versus **26** for the new three-way classifier: **26:0**, so no finite ratio exists (26 rows recovered). Comparing the unscoped raw comparator directly to the final scoped number would be **26/87 = 0.30x**, which is not an apples-to-apples improvement ratio.

## Regex-only eligibility text

Of **570/848 (67.2%)** postings with non-empty descriptions, **206 (36.1%)** contain at least one machine-readable eligibility signal. Batch/graduation: **1 (0.2%)**; experience/fresher: **200 (35.1%)**; degree: **73 (12.8%)**; enrolment: **1 (0.2%)**. Categories overlap.

## Amazon

`amazon.jobs` is not a viable measured adapter source yet: the probe completed no network request, so the public JSON status, schema, descriptions, pagination, requisition lookup, and India volume are all **unverified/UNCLEAR**. No India total can honestly be reported.

## Verdict

The boards actually measured contain roughly **26 India-located early-career technical postings** in this sample, all classified as unknown-stage rather than explicit early-stage. Across description-bearing postings, **36.1%** carry at least one regex-detectable eligibility signal; this is a supply-wide rate, not a claim that all 26 final rows are eligibility-qualified.

This measurement does **not** cover boards not swept; platforms with no adapter (including Zoho Recruit and Darwinbox); off-campus drives; or Unstop. It is also limited to the collected Greenhouse, Keka, and Lever rows and does not establish total market supply.
