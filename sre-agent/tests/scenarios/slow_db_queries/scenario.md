---
  Scenario 1: Slow DB Queries Causing App Slowness

  Infrastructure (fictional)

  - 3 app servers: api-service, payment-service, notification-service
  - 2 DB servers: db-primary, db-replica-1

  The Real Issue

  api-service → db-primary has a missing index on the orders table, causing full table scans on high-traffic queries.

  ---
  Log Entry Types

  api-service (affected app)
  - Slow response time warnings: Slow request detected GET /orders duration_ms=5103 (threshold: 2000ms)
  - DB connection pool pressure: DB connection pool pressure pool_size=20 active_connections=19 waiting_requests=5
  - Query timeout errors: QueryTimeoutError: statement timeout after 30000ms
  - Downstream retries: Retrying DB call, attempt 2/3
  - User-facing 500s: HTTP 500 returned to client for GET /orders/export

  db-primary (affected DB)
  - Slow query log (log_min_duration_statement): duration: 5812 ms  execute <unnamed>: SELECT * FROM orders WHERE customer_id = $1 ORDER BY created_at DESC
  - Query plan (auto_explain): Seq Scan on orders  (cost=0.00..284739.52 rows=1284901 width=312) (actual time=0.038..6812.441 rows=1284901 loops=1)
  - Lock waits: canceling statement due to lock timeout
  - High connection count: connection count: 187 active of 200 max (93%)

  payment-service (noise - healthy)
  - Normal response times, occasional unrelated 404s
  - Periodic health check logs

  notification-service (noise - healthy but suspicious-looking)
  - Some WARN level logs about email queue lag (unrelated, red herring)
  - Normal DB query times against db-replica-1

  db-replica-1 (noise - healthy)
  - Normal query logs, replication lag warnings (minor, unrelated red herring)

  ---
  Agent Challenge

  The agent must correlate:
  1. Ignore notification-service queue warnings (red herring)
  2. Ignore db-replica-1 replication lag (red herring)
  3. Pinpoint api-service ↔ db-primary as the affected pair
  4. Identify the specific slow query and table

  ---