# Spec 06: Final README

**Tracks:** single.

## Required sections
1. **Overview** and a short conversation demo (excerpt from `examples/04-arrependimento.md`).
2. **How to run:** start with a short **"What needs a key"** table: no key needed for `uv run pytest`, CI, reading `examples/` and the eval reports; a key is needed only to chat live or re-run the evals. Each reviewer uses **their own** free key (never committed), with step-by-step instructions to create it in AI Studio in a project **without billing**; `uv run musical-agent setup` saves it to `.env` (also the path for a temporary key received by e-mail). Then: `uv sync`, `.env`, `uv run musical-agent` (`--debug`, `--session`), `adk web src`, `uv run pytest`, `uv run pytest -m evals`, `uv run python evals/retrieval_eval.py`, `uv run python scripts/generate_examples.py`.
3. **Architecture:** mermaid diagram (CLI / `adk web` -> ADK `App` (Runner + SafetyPlugin + RunConfig limit) -> Gemini <-> 5 tools -> CSVs / BM25 policy index / complaints file; SQLite sessions).
4. **Technical decisions and trade-offs** (each with its reason):
   - ADK vs LangGraph vs no framework; Gemini 3.5 Flash (and why not 2.5 or 3.8).
   - **Hybrid architecture**: function calling for data + RAG for policies, as the challenge suggests; why not a SQL agent (small data, deterministic rules, authorization in code).
   - **Policy retrieval (RAG)**, with the comparison table:
     | Option | Pros | Cons |
     |---|---|---|
     | Full manual in the prompt | never misses context; manual is only 8 pages (~3-4k tokens) | does not scale; tokens every turn; hides *when* the agent decides to consult policies, which the challenge evaluates |
     | BM25 (fallback) | simple, no network, deterministic, testable | weak on paraphrases that share no words with the manual |
     | Embeddings (chosen) | handles paraphrases and informal language | external dependency, less predictable on exact terms (PIX, SEDEX) |
     | Hybrid (BM25 + embeddings, RRF) | best of both | extra complexity for a tiny corpus |
   - The plan started with BM25 as the simplest option (~25 chunks, distinct vocabulary per section, the model rewrites the question). The measurement contradicted it on raw customer paraphrases, so the decision rule switched production to embeddings with BM25 as offline fallback; the hybrid was measured and rejected.
   - **Decided by measurement**: retrieval eval results table (recall@2, MRR for BM25, embeddings, hybrid), the decision rule and the outcome.
   - No vector database: ~25 vectors fit in a `numpy` matrix; Chroma/FAISS/Vertex Vector Search would add infrastructure with no gain. Next step if the policy corpus grows (FAQ, product manuals).
   - **No custom REST API** (ADR-004). Always framed as a **scope decision for this prototype**, not as the right architecture for production:
     - **in a real project this would be different:** the agent would run behind an API (stateless workers, auth, per-customer rate limiting, horizontal scaling, channel webhooks such as WhatsApp), and the tools would be exposed through **MCP servers** owned by the systems of record (catalog/ERP, orders, policies, support desk) instead of in-process function calling. MCP decouples tools from the agent (independent deploy, versioning and access control per tool, reuse by other agents and by human-facing apps), and ADK consumes MCP tools natively (`McpToolset`), so the agent code would barely change;
     - in this prototype the data is static CSV/PDF in the same repo, there is a single consumer and a single agent, so an API and MCP servers would add network hops, deployment and auth with no benefit to what is being evaluated;
     - the challenge accepts CLI, notebook, API or simple UI and says the focus is the agent working correctly;
     - ADK already ships `adk web` (browser chat with event, tool and state traces) and `adk api_server` (a FastAPI REST server for the same agent): a custom API would duplicate framework features;
     - a production API is only meaningful with auth, rate limiting per customer and a channel integration (WhatsApp webhook, manual 7); a bare `/chat` endpoint would be a half feature;
     - time went to what the evaluation measures: evals, grounding, guardrails, retrieval decision;
     - `respond()` is interface-agnostic, so an API or WhatsApp adapter is a thin layer later.
   - Persistent sessions and state (SQLite file created automatically, no Docker; `--session` resume; LGPD: no email/phone in state). Framed as scope: production would use `FirestoreSessionService`, `VertexAiSessionService` or Postgres, swapped in one line through `BaseSessionService`.
   - Guardrails: tool-level authorization + `SafetyPlugin` with local screening; Model Armor optional because it needs a GCP project with billing.
   - Loop/cost limit with ADK native `RunConfig.max_llm_calls` instead of a custom plugin (use the framework before writing code).
   - Prompt strategy: persona, tool routing per intent, grounding rules, per-turn date and store-hours context.
5. **Cost:** everything runs on the Gemini free tier at zero cost (no billing = no charges, only 429 on limits); note that free-tier content may be used by Google to improve products (data here is fictional); reference paid prices for a full eval run (cents of a dollar).
6. **Data handling and assumptions** (summary + link to `docs/decisions.md`), including the online-purchase, delivery-date and partner-store assumptions.
7. **Evaluation and gates:** link to the latest successful manual `evals` run on GitHub Actions if one exists (found through the public API: `actions/runs?event=workflow_dispatch&status=success`); DoD traceability (every acceptance criterion maps to a test), unit tests, agent eval layers, coverage, red team, retrieval eval, CI gates and current results.
8. **Known limitations and next steps:** re-run the retrieval eval (and reconsider hybrid or a reranker) if the corpus grows; API layer for scale (auth, rate limiting, stateless workers) with WhatsApp channel; tools moved to MCP servers per system of record (consumed via ADK `McpToolset`); human handoff queue integrated with the team's tools; Langfuse/OpenTelemetry tracing; production session store (Firestore, Agent Engine sessions or Postgres); Model Armor enabled by default in a GCP deployment.
9. **AI coding assistants:** Claude Code with phased specs, DoD-driven TDD (each DoD row -> marked test, red before green, `test:` commit before `feat:`, enforced by `dod_check.py`), path-scoped rules, an implementation skill with parallel subagents per track, human review before each commit; how decisions (e.g. RAG strategy, no API) were discussed and challenged with the assistant.

## DoD
| ID | Criterion | Verified by |
|---|---|---|
| 06.X1 | README has all required sections (headings) | test |
| 06.X2 | Every relative link and file path in the README exists | test |
| 06.X3 | Every command in "How to run" works from a clean clone | command: `git clone` the local repo into a temp dir, copy `.env`, run `uv sync`, `uv run pytest`, a piped `uv run musical-agent` turn; summary in phase report |
| 06.X4 | Every decision states its reason; RAG and no-API justifications present as above | manual: review checklist |
| 06.X5 | Every "we did not build X" decision states that it is due to the prototype's scope and what a real project would need instead (API for scale, MCP for tools, Model Armor, production session store) | manual: review checklist |

## Commits
- `docs: finalize readme with decisions, limitations and workflow`
