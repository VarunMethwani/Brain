# Retrieval benchmark

Run the deterministic fixture benchmark from the repository root:

```bash
python benchmarks/context_benchmark.py
```

It reports 50 cases, Recall@5, approximate serialized response tokens, and
p95 local recall latency. The fixture is created under a temporary directory
and is removed automatically. It does not inspect or modify the current
project.

For meaningful release evaluation, replace the synthetic cases with at least
50 anonymized tasks from the target coding workflow. Keep the expected memory
IDs/titles outside the model prompt and compare baseline versus optimized
branches using the same fixture. Track Recall@5, nDCG@5, full MCP payload
tokens, p95 latency, unchanged-file refresh counts, and stale-memory exposure.
