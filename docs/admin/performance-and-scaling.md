# Performance & Scaling

Evidence Lab's API serves every request from a **single process with a single event loop**. That design is fine for work that waits on a database or an LLM, but it means one request that *blocks* the process delays every other request, including the small ones the interface fires while someone is reading a page. This page covers the settings that control how much work the API does at once, and the one change that looks like an obvious speed-up but is not.

All of these are environment variables set in `.env`. **Every one has a default, and leaving it unset uses that default** — a stock deployment needs none of them. A variable set to an *empty* value is not the same as unset: the API stops at startup rather than guessing.

## Concurrency

| Variable | Default | What it controls |
|----------|---------|------------------|
| `MAX_CONCURRENT_SEARCHES` | `8` | Searches running at once. Lower it if embedding or reranking models run inside the API process and memory is tight. |
| `MAX_CONCURRENT_RERANKS` | `1` | **Local** reranker inferences at once. A local reranker holds a model in the API process, so running several at once multiplies memory and has stopped the API outright. Raise with care. |
| `MAX_CONCURRENT_REMOTE_RERANKS` | `8` | **Hosted** reranker calls at once (Azure Foundry, Google Vertex). These are ordinary HTTP requests and cost no local memory, so they are bounded separately — by the provider's rate limit rather than by this process's memory. |
| `VERTEX_RERANK_BATCH_SIZE` | `200` | Records in one Google Vertex Ranking API request. A search that reranks more candidates than this is scored in slices of this size, one after another, inside a single remote-rerank slot; the scores are comparable across slices. A heatmapper cell can send up to 1000 documents (5000 chunks with wide search), which is why one request per search is not an option. The API accepts at most 1000 records per request. |

If your model combo reranks through a hosted service, `MAX_CONCURRENT_RERANKS` does not apply to it, and leaving that value at `1` costs you nothing.

A model combo's `rerank_model_page_size` in `config.json` caps how many of a search's candidates are reranked at all; the rest keep their search order behind the reranked ones. Without it every candidate is scored, so a heatmapper grid of broad queries can mean several Vertex requests per cell. See the combo settings in the README.

## Connection pools

| Variable | Default | What it controls |
|----------|---------|------------------|
| `POSTGRES_POOL_MAX` | `16` | Connections for the search and document queries, **per data source**. This pool raises an error rather than queueing when it is empty, so it must cover the request concurrency the API serves. |
| `POSTGRES_POOL_MIN` | `4` | Connections kept open when returned. Below this number the driver closes them, so a low value means reconnecting to Postgres on every request under load. |
| `AUTH_DB_POOL_SIZE` | `10` | Connections for accounts, activity and briefs. Unlike the pool above, this one waits rather than failing. |
| `AUTH_DB_MAX_OVERFLOW` | `20` | Extra connections this pool may open temporarily beyond `AUTH_DB_POOL_SIZE`. |

There is **one pool per process, per data source**, shared by every client object inside that process. That makes the budget below predictable, but it also means the count scales with processes, not just with settings.

**Budget the total.** `POSTGRES_POOL_MAX` × (data sources actually queried) × (processes talking to the database), plus `AUTH_DB_POOL_SIZE` + `AUTH_DB_MAX_OVERFLOW`, must stay below the Postgres server's `max_connections` (100 by default).

**The pipeline is the easy one to forget.** A `--workers N` run is **N + 1** processes, each holding its own pools, and it runs *alongside* the API. A `--workers 7` run therefore keeps 8 × `POSTGRES_POOL_MIN` connections open at idle — 32 with the default — before the API's share is counted. If a run reports `FATAL: sorry, too many clients already`, lower `--workers` or `POSTGRES_POOL_MIN`, or raise the server's `max_connections`.

Check with:

```sql
SHOW max_connections;
SELECT count(*) FROM pg_stat_activity;
```

## Reranker preload

| Variable | Default | What it controls |
|----------|---------|------------------|
| `PRELOAD_RERANK_MODEL` | `true` | Whether the reranker named in `config.json` is loaded into the API process at startup. |

The model stays in memory for the life of the process. If your deployment reranks through a hosted service, or does not rerank, set this to `false`: the memory is saved and the API starts faster. The model still loads on first use if something asks for it. See [Pipeline Configuration](pipeline-configuration.md) for choosing the reranker.

## LLM rate limits and retries

Hosted model providers limit how many **tokens per minute** a deployment may consume. Exceed it and the provider returns `HTTP 429` with a `Retry-After` header. That condition is temporary, and the right response is to wait — but if the pipeline gives up too quickly, a temporary throttle becomes a *permanently failed document*.

Evidence Lab always honours `Retry-After` when the provider sends one, and otherwise backs off exponentially with jitter so that many workers throttled at the same moment do not all retry in the same instant.

| Variable | Default | What it controls |
|----------|---------|------------------|
| `LLM_MAX_RETRIES` | `5` | Total attempts, **not** retries after the first. |
| `LLM_RETRY_BASE_DELAY_SECONDS` | `1` | The first backoff step; doubles on each subsequent attempt. |
| `LLM_RETRY_MAX_DELAY_SECONDS` | `30` | Ceiling on any single wait, including one the provider asks for. |

The defaults suit the API, where a request must not hang for minutes. **Bulk ingestion wants a larger budget**, because there a throttled call should slow the run down rather than drop a document:

```bash
LLM_MAX_RETRIES=8
LLM_RETRY_MAX_DELAY_SECONDS=60
```

### Match pipeline concurrency to the deployment's quota

Retries cope with brief throttling. They cannot rescue a run that asks for several times the provisioned rate indefinitely — that run will simply be slow, and some documents will still exhaust their budget. The demand comes from two multiplied settings:

> pipeline workers (`--workers`) **x** per-document summary workers (`llm_workers` in `config.json`)

Seven workers against six summary workers is **42 concurrent LLM calls**. A deployment provisioned well below that will throttle most of them. If you see sustained 429s, either raise the deployment's quota or lower one of the two numbers — raising retries alone only converts the failures into a very slow run.

On Azure OpenAI, a `GlobalStandard` deployment's capacity is quoted in thousands of tokens per minute, so capacity `200` is 200,000 TPM. Capacity sets the rate ceiling; billing stays per-token, so raising it does not create a standing cost.

## Do not add uvicorn workers to go faster

Running the API with more than one worker looks like the obvious fix for a busy deployment. It is not safe here, and it weakens a security control:

**Rate limits are counted in each process's own memory.** With *N* workers, every configured limit effectively becomes *N* times larger — including `AUTH_RATE_LIMIT_MAX`, which limits password attempts. Four workers means four times as many login attempts before an address is throttled.

The same applies to running several *instances* behind a load balancer: each instance counts its own limits. If you scale horizontally, treat the configured limits as per-instance and set them accordingly, and keep in mind that an attacker's requests may be spread across instances.

Moving the rate-limit counters to shared storage is the prerequisite for either, and until that is in place the safer lever is the concurrency settings above.

Account lockout is not affected — it is recorded against the user in the database, so it is already consistent across workers and instances. See [User Administration](user-administration.md).

## Checking whether the API is keeping up

A healthy API answers a trivial request quickly even while expensive ones are running. Compare the two:

```bash
# While a heavy request (a large document's highlights, a facet query) is running:
time curl -s -o /dev/null http://localhost:8000/health
```

If `/health` takes noticeably longer while heavy requests are in flight, the process is being held up rather than merely busy. Container CPU is the tell-tale: if latency is high while CPU is low, requests are queueing rather than computing, and the concurrency and pool settings above are where to look. [System Monitoring](system-monitoring.md) shows request activity and token usage.
