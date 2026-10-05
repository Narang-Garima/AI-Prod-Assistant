# Retrieval evaluation

I created a small five-case benchmark to evaluate ShopBuddy against the product data I ingested locally. The dataset is stored at `evaluation/retrieval_eval_dataset.json`.

## What I evaluate

My final benchmark covers:

- sunscreen evidence for sensitive skin
- wireless-mouse comfort, controls, battery, and value
- a comparison of moisturizer and face-serum evidence
- an evidence comparison across earbuds, smartwatch, and wireless keyboards
- a negative-control question for a product that is not in the collection

The evaluation runner retrieves real Astra contexts, builds an evidence-only response, and attempts two RAGAS metrics:

- `LLMContextPrecisionWithoutReference`
- `ResponseRelevancy`

I write detailed output to the ignored local file `reports/ragas_retrieval_results.json`. I review the individual cases before using an average because an aggregate score can hide missing-evidence failures.

## How I run it

After configuring Astra DB, Google embeddings, and the selected chat provider:

```powershell
python scripts/run_retrieval_evaluation.py
```

I added request pacing through `RAGAS_REQUEST_DELAY_SECONDS`; its default is 13 seconds for low-quota accounts.

## Dataset used for the completed run

I expanded the initial sample by scraping 14 additional raw product rows. After excluding six no-review placeholders and removing one duplicate product ID across all runs, I produced a curated local dataset with:

```text
Products: 10
Usable review documents: 17
Duplicate product IDs: 0
New Astra inserts: 13
Stored Astra documents after expansion: 18
```

The stored count includes one placeholder from the first five-document ingestion. Retrieval cleanup removes that placeholder before evaluation.

## Latest result

I completed the benchmark on 2026-10-04 local time (2026-10-05 UTC) with live Astra retrieval, Google embeddings, and `gemini-3.5-flash-lite`.

| Case | Contexts | Context precision | Response relevancy |
|---|---:|---:|---:|
| Sensitive-skin sunscreen | 4 | 0.0000 | 0.0000 |
| Wireless-mouse value | 4 | 0.8333 | 1.0000 |
| Skincare comparison | 4 | 0.5000 | 1.0000 |
| Accessory comparison | 4 | 0.5000 | 1.0000 |
| Insufficient-evidence control | 4 | 0.3333 | 1.0000 |
| **Mean** | **4** | **0.4333** | **0.8000** |

All five cases received both scores and recorded no metric errors. The detailed machine-readable result is written locally to the ignored file `reports/ragas_retrieval_results.json`.

## What this result tells me

The completed run confirms that embedding, Astra storage, vector search, grounded-response construction, and both RAGAS metrics work end to end. It also shows why I do not use the mean score alone.

The sunscreen query retrieved one sunscreen result alongside unrelated products and scored zero. More importantly, the negative control retrieved unrelated nearest neighbors and still received response relevancy `1.0`. Response relevancy measures whether the constructed answer stays aligned with the question; it is not by itself a reliable no-evidence detector.

My next evaluation improvements would be:

1. add a similarity/no-evidence threshold;
2. strengthen category-aware filtering before final context selection;
3. expand each category beyond one or two products;
4. keep comparing case-level results rather than relying on the mean;
5. turn these baseline results into regression thresholds after retrieval improves.

I describe RAGAS as implemented and successfully exercised on a small local benchmark. I do not describe the current scores as production-grade retrieval quality.
