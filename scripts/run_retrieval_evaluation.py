"""Run the credential-backed retrieval benchmark and save raw RAGAS scores."""

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "evaluation" / "retrieval_eval_dataset.json"
OUTPUT_PATH = ROOT / "reports" / "ragas_retrieval_results.json"


def validate_configuration() -> None:
    load_dotenv(ROOT / ".env", override=True)
    required = [
        "GOOGLE_API_KEY",
        "ASTRA_DB_API_ENDPOINT",
        "ASTRA_DB_APPLICATION_TOKEN",
        "ASTRA_DB_KEYSPACE",
    ]
    provider = os.getenv("LLM_PROVIDER", "openai").strip().lower()
    provider_key = {
        "openai": "OPENAI_API_KEY",
        "google": "GOOGLE_API_KEY",
        "groq": "GROQ_API_KEY",
    }.get(provider)
    if provider_key is None:
        raise SystemExit(f"Unsupported LLM_PROVIDER: {provider}")

    missing = [name for name in [*required, provider_key] if not (os.getenv(name) or "").strip()]
    if missing:
        raise SystemExit(f"Missing required environment variables: {sorted(set(missing))}")


async def run() -> None:
    validate_configuration()

    # Import model-backed modules only after the fast configuration check.
    from prod_assistant.evaluation.ragas_eval import (
        evaluate_context_precision_async,
        evaluate_response_relevancy_async,
    )
    from prod_assistant.retriever.retrieval import (
        Retriever,
        build_grounded_response,
        format_docs_as_context_strings,
    )

    cases = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    retriever = Retriever()
    results = []
    request_delay = float(os.getenv("RAGAS_REQUEST_DELAY_SECONDS", "13"))

    for case in cases:
        documents = retriever.call_retriever(case["question"])
        contexts = format_docs_as_context_strings(documents)
        response = build_grounded_response(case["question"], documents)

        metric_errors = {}
        context_precision = None
        response_relevancy = None
        if contexts:
            try:
                context_precision = float(
                    await evaluate_context_precision_async(case["question"], response, contexts)
                )
            except Exception as exc:
                metric_errors["context_precision_without_reference"] = type(exc).__name__

            if request_delay:
                await asyncio.sleep(request_delay)

            try:
                response_relevancy = float(
                    await evaluate_response_relevancy_async(case["question"], response, contexts)
                )
            except Exception as exc:
                metric_errors["response_relevancy"] = type(exc).__name__

        results.append(
            {
                **case,
                "retrieved_context_count": len(contexts),
                "context_precision_without_reference": context_precision,
                "response_relevancy": response_relevancy,
                "response": response,
                "metric_errors": metric_errors,
            }
        )

        if request_delay:
            await asyncio.sleep(request_delay)

    context_scored = [
        row for row in results if row["context_precision_without_reference"] is not None
    ]
    response_scored = [row for row in results if row["response_relevancy"] is not None]
    summary = {
        "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": str(DATASET_PATH.relative_to(ROOT)),
        "case_count": len(results),
        "context_precision_scored_case_count": len(context_scored),
        "response_relevancy_scored_case_count": len(response_scored),
        "mean_context_precision_without_reference": (
            sum(row["context_precision_without_reference"] for row in context_scored)
            / len(context_scored)
            if context_scored
            else None
        ),
        "mean_response_relevancy": (
            sum(row["response_relevancy"] for row in response_scored) / len(response_scored)
            if response_scored
            else None
        ),
        "results": results,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "results"}, indent=2))
    print(f"Detailed results: {OUTPUT_PATH}")


if __name__ == "__main__":
    asyncio.run(run())
