# type: ignore
"""
  Step 1 - Start with the alert: jira.md

  The Jira ticket says:
  Summary: [ALERT] api-service CPU utilization above 85% - production
  Current value: 91% / Threshold: 85%
  Triggered: 2026-06-12 01:38:14 UTC

  SRE thinks: CPU spike on api-service. Could be a traffic surge, a slow
  dependency, GC pressure, or a runaway process. A CPU alert alone gives no
  clue that this is a DB issue - that has to be discovered.

  First instincts (before touching any logs):
  - Was there a recent deployment? Check Cloud Build / Cloud Deploy history.
  - Is traffic volume up? Check request rate metrics in Cloud Monitoring.
  - Is it just api-service or cluster-wide? Quick check on other services.
  - Is the host healthy? Check memory, disk, swap on the node.

  This initial triage burns 5-10 minutes before logs are even opened.

  ---
  Step 2 - Check Cloud Monitoring dashboards

  SRE opens the observability dashboard (Cloud Monitoring / Grafana):
  - CPU: 91% and climbing
  - Request rate: normal (not a traffic spike)
  - Error rate: spiking - 500s on /orders endpoints
  - Latency p99: jumped from ~200ms to 5000ms+

  SRE thinks: Not a traffic surge. CPU is high because request latency exploded -
  threads are piling up waiting on something. The 500s on /orders are the symptom.
  Need to check api-service logs to find what is slow.

  ---
  Step 3 - api-service logs in Logs Explorer

  Filter:
      resource.type="k8s_container"
      resource.labels.container_name="api-service"
      severity>=WARNING

  First sign something changed:
  {"offset_seconds": 361, "level": "WARN", "message": "Slow request detected",
   "path": "/orders", "duration_ms": 3241, "threshold_ms": 2000}
  ▎ Normal requests were 142-188ms. Suddenly 3241ms. Something changed.

  Getting worse over time:
  {"offset_seconds": 374, "duration_ms": 4817}
  {"offset_seconds": 402, "duration_ms": 5103}
  ▎ Escalating latency - not a one-off spike, it's a sustained degradation.

  DB is struggling:
  {"offset_seconds": 389, "message": "DB connection pool pressure",
   "active_connections": 17, "waiting_requests": 2}
  {"offset_seconds": 431, "active_connections": 19, "waiting_requests": 5}
  {"offset_seconds": 521, "message": "DB connection pool exhausted",
   "active_connections": 20, "waiting_requests": 12}
  ▎ Connections piling up. Queries aren't finishing fast enough to free connections.
  ▎ This explains the CPU spike - threads blocked on DB connections, request queue
  ▎ growing, CPU consumed by thread scheduling and retry loops.

  Users starting to hit errors:
  {"offset_seconds": 445, "message": "QueryTimeoutError: statement timeout after 30000ms",
   "query": "SELECT * FROM orders WHERE customer_id=?", "db_host": "db-primary"}
  {"offset_seconds": 446, "message": "Retrying DB call", "attempt": 1, "max_attempts": 3}
  {"offset_seconds": 476, "attempt": 2}
  {"offset_seconds": 508, "message": "All retry attempts exhausted", "db_host": "db-primary"}
  {"offset_seconds": 509, "message": "HTTP 500 returned to client", "path": "/orders"}
  ▎ Queries timing out after 30 seconds, retries failing, users getting 500s.

  Key observation: Every timeout is the same query - SELECT * FROM orders
  WHERE customer_id=?. Not random failures. One specific query is broken.

  SRE concludes: CPU is high because threads are blocked waiting on db-primary.
  The query SELECT * FROM orders WHERE customer_id=? is taking 30+ seconds.
  Go look at the DB.

  ---
  Step 4 - db-primary logs

  Filter:
      resource.labels.container_name="db-primary"
      severity>=WARNING

  First slow query logged:
  {"offset_seconds": 358, "level": "WARN",
   "message": "duration: 3104 ms  execute <unnamed>: SELECT * FROM orders WHERE customer_id = $1 ORDER BY created_at DESC",
   "application_name": "api-service"}
  ▎ Postgres log_min_duration_statement fired - this query exceeded threshold.
  ▎ 3 seconds for a simple lookup by customer_id is very wrong.

  Immediately followed by the query plan:
  {"offset_seconds": 359, "level": "WARN",
   "message": "duration: 3104 ms  plan: Seq Scan on orders  (cost=0.00..284739.52 rows=1284901 width=312) (actual time=0.032..2847.123 rows=1284901 loops=1)"}
  ▎ This is the smoking gun. auto_explain logged the execution plan.
  ▎ - Seq Scan on orders - reading every row in the table
  ▎ - rows=1284901 - scanned 1.28 million rows
  ▎ - There is no Index Scan or Index Cond - no index is being used

  Getting worse with each query:
  {"offset_seconds": 371, "duration_ms": 4892, "rows=1284901"}
  {"offset_seconds": 391, "duration_ms": 5812, "rows=1284901"}
  {"offset_seconds": 429, "duration_ms": 7341, "rows=1284901"}
  {"offset_seconds": 462, "duration_ms": 9103, "rows=1284901"}
  {"offset_seconds": 601, "duration_ms": 11203, "rows=1284901"}
  ▎ Every query scans the same 1.28M rows. Duration climbs because the table is
  ▎ being hammered by concurrent connections all doing the same full scan.

  Lock contention starting:
  {"offset_seconds": 412, "level": "ERROR", "message": "canceling statement due to lock timeout",
   "detail": "Process 4824 waits for ShareLock on transaction 87423; blocked by process 4821.
              Query: SELECT * FROM orders WHERE customer_id = $1 ORDER BY created_at DESC"}
  ▎ Concurrent full scans holding locks, blocking each other. Cascade begins.

  Connection saturation:
  {"offset_seconds": 384, "message": "connection count: 142 active of 200 max (71%)"}
  {"offset_seconds": 421, "message": "connection count: 168 active of 200 max (84%)"}
  {"offset_seconds": 451, "message": "connection count: 187 active of 200 max (93%)"}
  {"offset_seconds": 503, "message": "connection count: 196 active of 200 max (98%)"}
  {"offset_seconds": 564, "message": "connection count: 199 active of 200 max (99%)"}
  ▎ Each slow query holds a connection for 10+ seconds instead of milliseconds. At
  ▎ 200 max connections the entire DB becomes unreachable.

  SRE concludes: orders table has no index on customer_id. Every query does a full
  table scan of 1.28M rows. Fix is CREATE INDEX CONCURRENTLY on
  orders(customer_id, created_at).

  ---
  Step 5 - Check the other services - Red herrings

  A CPU alert naturally makes the SRE wonder: is this isolated to api-service or
  is something else also affected? They check the other services.

  notification-service:
  {"offset_seconds": 225, "level": "WARN", "message": "Email queue lag detected",
   "queue_depth": 18, "threshold": 15, "lag_seconds": 42}
  {"offset_seconds": 258, "queue_depth": 24, "lag_seconds": 71}
  {"offset_seconds": 455, "queue_depth": 43, "lag_seconds": 187}
  ▎ WARN level, looks alarming. But:
  ▎ - db_host is db-replica-1, not db-primary
  ▎ - Query times are 17-22ms (completely healthy)
  ▎ - Queue lag started before the orders incident at offset 225
  ▎ - This is an SMTP backlog, unrelated to the DB issue

  Dismissed. Email queue has its own independent backlog problem.

  db-replica-1:
  {"offset_seconds": 320, "level": "WARN", "message": "Replication lag elevated",
   "lag_seconds": 3.2, "threshold_seconds": 3}
  {"offset_seconds": 462, "lag_seconds": 5.8}
  {"offset_seconds": 566, "lag_seconds": 7.1}
  ▎ Replication lag is increasing. Looks related - but:
  ▎ - notification-service queries against replica are still 11-16ms (fast, indexed)
  ▎ - Replication lag increasing is a symptom of db-primary being overloaded, not a cause
  ▎ - Nobody is querying orders on the replica

  Dismissed. Replica lag is a downstream effect of the primary being hammered.

  payment-service:
  {"offset_seconds": 271, "level": "WARN", "message": "Stripe API latency elevated",
   "stripe_latency_ms": 1842, "threshold_ms": 1500}
  {"offset_seconds": 99,  "status": 404}
  {"offset_seconds": 325, "status": 404}
  ▎ All payment endpoints are fast (54-428ms). 404s are for non-existent order
  ▎ IDs - normal. Stripe latency is external, not DB-related.

  Dismissed. Payment service is completely healthy.

  ---
  The full chain: why CPU is at 91%

  Missing index on orders(customer_id)
    → Every SELECT * FROM orders WHERE customer_id=? does a Seq Scan of 1.28M rows
    → Queries take 3-13 seconds instead of <1ms
    → DB connections held open 1000x longer than normal
    → Connection pool exhausted (199/200 on DB, 20/20 on app)
    → Application threads blocked waiting for DB connections
    → Thread queue grows, CPU consumed by scheduling + retry loops
    → CPU spikes to 91%
    → Cloud Monitoring alert fires
    → Webhook creates Jira ticket

  ---
  Realistic timeline for a competent SRE

  ┌─────────────────────────────────────────────────────┬───────────┐
  │                       Phase                         │   Time    │
  ├─────────────────────────────────────────────────────┼───────────┤
  │ Alert triage - check deploys, rule out traffic spike│ 5-10 min  │
  ├─────────────────────────────────────────────────────┼───────────┤
  │ Check metrics dashboard - discover error rate spike │ 3-5 min   │
  ├─────────────────────────────────────────────────────┼───────────┤
  │ Pull and read api-service logs                      │ 5 min     │
  ├─────────────────────────────────────────────────────┼───────────┤
  │ Realise DB is the bottleneck, pull db-primary logs  │ 5 min     │
  ├─────────────────────────────────────────────────────┼───────────┤
  │ Investigate notification-service red herring        │ 5-10 min  │
  ├─────────────────────────────────────────────────────┼───────────┤
  │ Understand auto_explain Seq Scan output             │ 5-10 min  │
  ├─────────────────────────────────────────────────────┼───────────┤
  │ Confirm diagnosis with EXPLAIN ANALYZE              │ 5 min     │
  ├─────────────────────────────────────────────────────┼───────────┤
  │ Decide on safe fix, get approval                    │ 5-10 min  │
  ├─────────────────────────────────────────────────────┼───────────┤
  │ Total                                               │ 38-60 min │
  └─────────────────────────────────────────────────────┴───────────┘

  When the human identifies the missing index: Step 4 - reading the auto_explain
  Seq Scan output in db-primary logs. They still need to confirm with \\d orders
  before declaring root cause in the incident channel.

  The extra 3-5 minutes vs a "500 error" alert comes from the indirection: a CPU
  alert doesn't point at the DB. The SRE must first discover that CPU is high
  BECAUSE of the DB issue, not the other way around.
"""
