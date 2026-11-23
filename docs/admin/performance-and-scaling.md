# Performance & Scaling

Evidence Lab's API serves every request from a **single process with a single event loop**. That design is fine for work that waits on a database or an LLM, but it means one request that *blocks* the process delays every other request, including the small ones the interface fires while someone is reading a page. This page covers the settings that control how much work the API does at once, and the one change that looks like an obvious speed-up but is not.

All of these are environment variables set in `.env`. **Every one has a default, and leaving it unset uses that default** — a stock deployment needs none of them. A variable set to an *empty* value is not the same as unset: the API stops at startup rather than guessing.

## Concurrency

| Variable | Default | What it controls |
|----------|---------|------------------|
| `MAX_CONCURRENT_SEARCHES` | `8` | Searches running at once. Lower it if embedding or reranking models run inside the API process and memory is tight. |
| `MAX_CONCURRENT_RERANKS` | `1` | **Local** reranker inferences at once. A local reranker holds a model in the API process, so running several at once multiplies memory and has stopped the API outright. Raise with care. |
| `MAX_CONCURRENT_REMOTE_RERANKS` | `8` | **Hosted** reranker calls at once (Azure Foundry, Google Vertex, Amazon Bedrock, a Cohere-compatible endpoint). These are ordinary HTTP requests and cost no local memory, so they are bounded separately — by the provider's rate limit rather than by this process's memory. |
| `VERTEX_RERANK_BATCH_SIZE` | `200` | Records in one Google Vertex Ranking API request. A search that reranks more candidates than this is scored in slices of this size, one after another, inside a single remote-rerank slot; the scores are comparable across slices. A heatmapper cell can send up to 1000 documents (5000 chunks with wide search), which is why one request per search is not an option. The API accepts at most 1000 records per request. |

If your model combo reranks through a hosted service, `MAX_CONCURRENT_RERANKS` does not apply to it, and leaving that value at `1` costs you nothing.

A model combo's `rerank_model_page_size` in `config.json` caps how many of a search's candidates are reranked at all; the rest keep their search order behind the reranked ones. Without it every candidate is scored, so a heatmapper grid of broad queries can mean several Vertex requests per cell. See the combo settings in the README.

## Request size limits

These bound how much one request can ask for. The web interface stays well inside them; they stop a scripted request from exhausting memory or the model budget.

| Variable | Default | What it controls |
|----------|---------|------------------|
| `SEARCH_MAX_LIMIT` | `10000` | The largest `limit` a search may ask for (`/search`, `/search/facet-values`). An empty-query search loads that many passages into memory. Keep it at or above `application.search.heatmap_cell_limit` in `config.json`, which the heatmapper asks for per cell (see [Search response size](#search-response-size)). |
| `HIGHLIGHT_MAX_TEXT_CHARS` | `50000` | The longest text a highlight request may send. The app sends one passage at a time; the longest measured passage in the UNEG corpus is 42,604 characters. |

AI requests are also limited by `config.json`: a request may only name a model listed under `supported_llms`, and may ask for at most as many output tokens as `config.json` sets for that model (the largest `max_tokens` among its own entry and the model combo settings that use it). A request outside those limits gets a 400 that names the limit.

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

The Cohere reranker on Azure Foundry is much smaller per unit: each unit of capacity allows 1 request and 1,000 tokens a minute. One search reranks several documents in one request, so a reranker at capacity `1` fails searches with HTTP 429. The [Azure example deployment](cloud-deployment.md#example-azure) gives it 20 units. Its quota is shared by every Foundry resource in a subscription and region.

## Search response size

A search result is a chunk joined to its document's record. The record is sent once per result, so a response's size is set by the number of results, not of documents, and a request for many results can be large: before v1.6.6 one Heatmap cell with wide search on, which returned 1600 results, measured 264 MB (52 MB compressed), and some hosts refuse a response that big. Google Cloud Run, for one, fails a non-streamed response above 32 MiB with HTTP 500 and the system log line "Response size was too large" ([Cloud Run quotas](https://cloud.google.com/run/quotas)); the api itself neither fails nor restarts. Three things keep a response small.

**Results carry only what readers use.** A result's `metadata` holds the data source's `metadata_panel_fields`, the core and `map_*` fields, the unpacked `src_*` fields, paths, ids and URLs. It no longer repeats the raw pipeline record (`sys_data`), the table of contents, the taxonomies, the raw source metadata or the `sys_*` copies of the summary and classified contents. The Documents tab and the `/documents` endpoint still return the whole record.

**Lean results for callers that never open a result.** `GET /search?lean=true` leaves out each result's chunk elements, tables, images and bounding boxes, and the document summary and classified contents from its metadata. The Heatmap sends it: a cell lists results and exports their text, but opening one happens in the Search tab. The same cell measured 82 MB (17 MB compressed) with the trimmed metadata alone, and 10 MB (1.3 MB compressed) lean.

**Two limits.** `SEARCH_MAX_LIMIT` (above) is the largest `limit` the API accepts from anyone; a larger one is rejected with HTTP 422. `heatmap_cell_limit` in `config.json`, next to `page_size` under `application.search`, is how many results one Heatmap cell asks for (default `1000`, at most `SEARCH_MAX_LIMIT`). It replaces the `REACT_APP_HEATMAP_LIMIT` environment variable and, like `page_size`, is baked into the web app at build time, so rebuild the ui after changing it.

With wide search on, a cell's `wide_limit` is the cell limit and the response holds up to `wide_group_size` chunks per document, so a cell that matches many documents can hold several times `heatmap_cell_limit` results; the lean shape keeps each one small. If a host has a response limit, size the two limits for it: about 6 KB per lean result and 50 KB per full result, before compression.

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
