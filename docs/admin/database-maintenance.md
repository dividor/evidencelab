## Database Maintenance

Evidence Lab uses PostgreSQL (document metadata, chunks) and Qdrant (vector search) as its primary databases. Both benefit from periodic maintenance, especially after large ingestion runs.

---

### Postgres: Autovacuum Tuning

Alembic migration `0020` automatically configures aggressive autovacuum on all `chunks_*` and `docs_*` tables:

| Setting | Value | Default | Purpose |
|---------|-------|---------|---------|
| `autovacuum_vacuum_scale_factor` | 0.02 | 0.20 | Trigger vacuum at 2% dead rows |
| `autovacuum_analyze_scale_factor` | 0.02 | 0.10 | Re-analyze at 2% changes |
| `autovacuum_vacuum_cost_limit` | 1000 | 200 | More work per vacuum cycle |

These settings are applied automatically when running `alembic upgrade head`. No manual configuration needed for new deployments.

To verify settings on an existing database:

```sql
SELECT relname, reloptions
FROM pg_class
WHERE relname LIKE 'chunks_%' OR relname LIKE 'docs_%';
```

---

### Postgres: VACUUM FULL

After large bulk deletions (e.g. removing duplicate documents, pruning orphans), dead rows accumulate and the table grows on disk even though autovacuum marks rows as reusable. `VACUUM FULL` rewrites the table to reclaim disk space.

**When to run:** After any operation that deletes a significant fraction (>10%) of rows in a table.

**Impact:** Locks the table for the duration. The pipeline and API will block on writes/reads to the affected table. Schedule during maintenance windows.

```bash
# Connect to the database
docker compose exec -T postgres psql -U evidencelab -d evidencelab

# Check bloat before running
SELECT relname,
       pg_size_pretty(pg_total_relation_size(oid)) as total_size,
       n_dead_tup as dead_rows,
       n_live_tup as live_rows
FROM pg_stat_user_tables
JOIN pg_class ON relname = pg_class.relname AND relkind = 'r'
WHERE relname LIKE 'chunks_%' OR relname LIKE 'docs_%'
ORDER BY pg_total_relation_size(oid) DESC;

# Run VACUUM FULL (locks table)
VACUUM FULL docs_uneg;
VACUUM FULL chunks_uneg;
```

---

### Qdrant: Optimizer Configuration

Qdrant write performance degrades as collections grow because it rebuilds the HNSW index after each small segment flush. Two environment variables control when indexing kicks in:

| Variable | Default | Purpose |
|----------|---------|---------|
| `INDEXING_THRESHOLD` | 20000 | Delay HNSW indexing until segments reach this many points |
| `MEMMAP_THRESHOLD` | 20000 | Delay mmap conversion until segments reach this size |

Higher values improve write throughput during bulk ingestion at the cost of temporarily un-indexed segments (which fall back to brute-force search).

These are applied automatically when creating new collections. To update an existing collection:

```bash
curl -X PATCH "http://localhost:6333/collections/chunks_uneg" \
  -H "Content-Type: application/json" \
  -d '{"optimizers_config": {"indexing_threshold": 20000, "memmap_threshold": 20000}}'
```

---

### Qdrant: Snapshot Backups

Qdrant snapshots capture the full state of a collection. Use the dump/restore scripts:

```bash
# Dump (set QDRANT_HOST=localhost when running outside Docker)
QDRANT_HOST=localhost python scripts/sync/db/dump_qdrant.py \
  --output /path/to/backups/ --prefix my-backup-

# Restore
QDRANT_HOST=localhost python scripts/sync/db/restore_qdrant.py \
  --input /path/to/backups/my-backup-qdrant_dump_*/
```

---

### Maintenance Scripts

| Script | Purpose |
|--------|---------|
| `scripts/fixes/prune_orphaned_docs.py` | Remove DB records for documents whose files no longer exist on disk |
| `scripts/maintenance/update_uneg_data.py` | Deduplicate PDFs, align metadata, stage new files |
| `scripts/sync/db/dump_postgres.py` | Dump Postgres to backup directory |
| `scripts/sync/db/dump_qdrant.py` | Dump Qdrant collections to snapshots |
