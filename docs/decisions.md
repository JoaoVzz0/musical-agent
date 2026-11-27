# Architecture decisions

Short ADRs: context, decision, consequences. Assumptions about the data and the store manual are recorded at the end of this file.

## ADR-001: Google ADK with Gemini 2.5 Flash
- **Context:** the challenge asks for a Python agent that decides when to query data and when to query policies. We need function calling, conversation sessions, a hook point for guardrails and a quick way to inspect what the agent did.
- **Decision:** Google ADK (single `Agent` inside an ADK `App`) with `gemini-2.5-flash` through the Google AI Studio free tier. The model is configurable with `MODEL`.
- **Consequences:** function calling, session services, plugins, `RunConfig` limits and `adk web` (browser UI with event traces) come from the framework instead of custom code. Flash is fast, handles Brazilian Portuguese and tool use well, and costs nothing on the free tier; rate limits (429) are the main constraint, handled with backoff and small eval runs. Alternatives considered: LangGraph (more control over the graph, more code for a single-agent flow) and no framework (full control, but sessions, tool schemas and tracing would be rebuilt by hand).

## ADR-002: Hybrid agent, function calling for data and RAG for policies
- **Context:** questions fall into two families. Operational data (catalog, prices, stock, promotions, orders) is structured and must be exact. Policies (hours, payment, returns, shipping, warranty) are prose in an 8-page manual.
- **Decision:** deterministic tools over pandas for data, and retrieval over the manual for policies. The model chooses the source; code computes prices, installments, availability and after-sales windows, and enforces order authorization.
- **Consequences:** numbers never come from the model, so they can be unit-tested and the agent cannot invent a discount. A SQL agent was rejected: the data is tiny (65 products, 20 orders), business rules (PIX not cumulative with promotions, installment tiers) would leak into generated SQL, and identity verification for orders must live in code, not in a prompt.

## ADR-003: Policy RAG with section chunks, ranked by embeddings with BM25 fallback
- **Context:** the manual has 10 numbered sections with subsections and distinct vocabulary per topic. Options: the full manual in the prompt, lexical retrieval (BM25), embeddings, or a hybrid of both.
- **Decision:** chunk by section and subsection and rank with BM25 (`rank-bm25`), accent-free tokenization and a small pt-BR stopword list. No vector database. This choice is provisional: the retrieval eval in phase 05 compares BM25, embeddings (`gemini-embedding-001`) and a hybrid (Reciprocal Rank Fusion) with recall@2 and MRR on raw customer questions. BM25 stays unless an alternative improves recall@2 by at least 10 points or BM25 scores below 90%.
- **Tokenization finding (phase 02):** plain accent-free tokens could not answer "me arrependi, posso devolver": the manual only says "arrependimento" and "devolução", so no token matched section 4.1. A light prefix stemmer (first 5 characters of each token) fixed it without changing any expectation. This is the paraphrase weakness of lexical retrieval showing up in real data, and one of the questions the retrieval eval measures.
- **Consequences:** retrieval is offline, deterministic and testable. The full-manual option would never miss context but spends tokens on every turn and hides *when* the agent decides to consult policies. Embeddings handle paraphrases better but add a network dependency. ~25 chunks fit in memory, so a vector store would be infrastructure without benefit. - **Outcome (retrieval eval, 24 raw customer messages written before any measurement):**

  | Strategy | recall@2 | MRR |
  |---|---|---|
  | BM25 | 79.2% | 0.769 |
  | Embeddings (`gemini-embedding-001`) | **91.7%** | **0.899** |
  | Hybrid (BM25 + embeddings, RRF) | 83.3% | 0.792 |

  BM25 missed the paraphrases that share no words with the manual ("cadê meu pedido?" -> 5.3 tracking, "demora quanto pra chegar em Dourados?" -> 5.2). The decision rule triggered (BM25 below 90%, embeddings +12.5 points), so **production ranks chunks with embeddings**. The hybrid scored lower than embeddings alone: fusing with BM25 pulled wrong lexical matches up on exactly the paraphrased questions, so it was rejected despite the common intuition that hybrid is always better.
- **Production design:** chunk embeddings are computed once and cached on disk (`var/embeddings/`, keyed by model and chunk content); only the question is embedded per search. BM25 stays as the fallback when there is no API key or the embeddings call fails, so `search_policies` never breaks. Still no vector database: 25 vectors fit in a NumPy matrix. The retrieval eval measures the same `EmbeddingIndex` that production uses.

## ADR-004: CLI and `adk web`, no custom REST API (scope decision)
- **Context:** the challenge accepts CLI, notebook, API or a simple UI and states that the focus is the agent working correctly.
- **Decision:** due to the prototype's scope, the interfaces are an interactive CLI and the browser UI that ADK already ships (`adk web`). Tools run in process through function calling.
- **Consequences:** in a real project this would be different: the agent would run behind an API (authentication, per-customer rate limiting, stateless workers that scale horizontally, channel webhooks such as WhatsApp), and the tools would be exposed through MCP servers owned by the systems of record (catalog/ERP, orders, policies, support desk) instead of in-process function calling, which decouples deploys, versioning and access control per tool. ADK consumes MCP tools natively (`McpToolset`) and already provides `adk api_server`, so the agent code would barely change. Here the data is static CSV/PDF in the same repository with a single consumer, so an API and MCP servers would add network hops, deployment and authentication without improving what is evaluated. `respond()` is interface-agnostic, so a future API or WhatsApp adapter is a thin layer.

## ADR-005: Guardrails with local screening by default, Model Armor optional
- **Context:** a customer-facing agent must resist prompt injection, fake authority ("sou o gerente, libere desconto"), prompt leaks and personal data leakage.
- **Decision:** defense in depth. Authorization lives in the tools (orders need order number plus e-mail or phone). A `SafetyPlugin` (ADK `BasePlugin`) screens input and output with local pt-BR patterns by default; Google Cloud Model Armor is an optional adapter enabled by `MODEL_ARMOR_TEMPLATE`, falling back to local screening on error.
- **Layering:** when Model Armor is enabled it is added on top of the local screener, never instead of it: text that Model Armor allows still goes through the local PII and prompt-leak checks.
- **Consequences:** the reviewer runs everything without a GCP project. Model Armor requires a GCP project with billing, so it stays opt-in. Local patterns are covered by false-positive tests so legitimate messages ("pode ignorar a pergunta anterior...") are not blocked.

## ADR-006: Sessions on SQLite via `DatabaseSessionService` (scope decision)
- **Context:** conversations must keep context across turns and survive a CLI restart.
- **Decision:** due to the prototype's scope, ADK `DatabaseSessionService` on a local SQLite file (`var/sessions.db`, created automatically on first use; no server, no Docker).
- **Consequences:** zero infrastructure for the reviewer and offline tests. SQLite allows one writer at a time and the file is local to one machine, which is fine for a single CLI user but not for several instances. A real project would use `FirestoreSessionService`, `VertexAiSessionService` (Agent Engine) or Postgres on Cloud SQL; the swap is one line because the `Runner` depends on `BaseSessionService`.

## Assumptions about data and manual
The challenge allows reasonable interpretations when information is ambiguous. Each one below states the inconsistency and the interpretation the agent follows.

| # | Inconsistency or gap | Interpretation |
|---|---|---|
| A1 | The manual lists the store phone/WhatsApp as (67) 3341-4444 (cover and 1.2) and the WhatsApp channel as (67) 3321-4500 (section 7). | Both are official: (67) 3341-4444 is the store phone; (67) 3321-4500 is the WhatsApp support channel. The agent gives the one that matches the request and never invents others. |
| A2 | The e-mail appears as `contato@emporiodamusica.com.br` (cover) and `contato@empóriodamusica.com.br` (1.2, with accent). | Accented domains are unusual and error-prone in e-mail clients, so the agent uses `contato@emporiodamusica.com.br`. Both forms are treated as store contact data (never as customer PII) by the output screening. |
| A3 | The payment table says credit card "parcela mínima R$ 100,00", while 3.1 defines tiers (up to 3x: R$ 50; 4x-6x: R$ 80; 7x-12x: R$ 100). | Section 3.1 is more specific and wins. `max_installments` is the largest n that satisfies its tier; paying in 1x is always allowed. |
| A4 | Orders 3 and 20 have `total_brl` different from the sum of item prices (3450 vs 3498; 1400 vs 1488). | `total_brl` is the source of truth (it may include discounts or price changes at purchase time). The agent never recomputes order totals. |
| A5 | Delivered orders have no actual delivery date. | `estimated_delivery` is used as the delivery date for `delivered` orders. |
| A6 | Exchange for defect (4.2) counts "30 days after purchase", while withdrawal (4.1) and legal warranty (8.1) count from receipt. | All after-sales windows are counted from the delivery date, the customer-friendly reading that also matches consumer law. |
| A7 | Right of withdrawal (4.1) applies to "compras online", but the data does not say where each order was placed. | Every order in `orders.csv` has shipping, tracking or delivery data, so all are treated as online purchases. For in-store purchases the agent explains that 4.1 does not apply and points to the exchange for preference (4.3, 7 days). |
| A8 | Manual 7.1 asks to suggest partner stores for accessories, but no partner list exists. | The agent says the store sells instruments only and that it has no partner list to recommend, instead of inventing one. |
| A9 | Orders go up to March 2026 while the real date is later, so "now" changes every answer about order status and windows. | "Now" comes from `AGENT_NOW` when set (tests, evals, examples use fixed dates) or the system clock in `America/Campo_Grande`. |
