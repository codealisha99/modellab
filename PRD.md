# PRD — ModelLab (05-modellab)

## Problem

Fine-tune demos report fake accuracy. Agent memory is usually an unbounded list.

## Objective

A repeatable train → eval → registry → infer loop that answers “did fine-tuning justify its cost?” plus a three-tier memory with real scoring.

## Functional requirements

1. Validate, clean, shuffle (seeded), 80/20 split, token counts.
2. LoRA/QLoRA config + 3 checkpoint files on disk.
3. Compare base vs prompt-engineering vs tuned with exact-match on held-out split.
4. Report metric delta + mock cost; `justified` is false unless delta > 0.05.
5. Working (cap 20) / episodic / semantic; dedup, eviction, provenance.
6. Retrieval score = relevance × recency × importance. 20-query suite > 0.7.
7. Streaming interface (SSE) with simulated tokens: resumable via `Last-Event-ID` with no gaps or duplicates, heartbeats while idle, finished streams expire after a fixed TTL (410 Gone).

## Out of scope

Real GPU clusters, MLflow, distributed training.
