# Scenario 1: Slow DB Queries — Human SRE vs Agent Cost & Time Comparison (GCP)

| Source | Reference |
|---|---|
| Token usage | `triage_results/agent.py` — Cloud Trace `dfa55460d7d8ad039a0a85c90fd4805d` |
| LLM pricing | Anthropic pricing docs (`https://platform.claude.com/docs/en/about-claude/pricing`) |
| Agent Engine pricing | Gemini Enterprise Agent Platform pricing page (`https://cloud.google.com/products/gemini-enterprise-agent-platform/pricing`) |
| Cloud Run pricing (used by Functions Gen 2) | `https://cloud.google.com/run/pricing` |
| Secret Manager pricing | `https://cloud.google.com/secret-manager/pricing` |
| Wall-clock | Cloud Trace span tree — `invocation` root span: `start=2026-06-11T11:39:36.938Z end=2026-06-11T11:40:38.288Z` → **61.35 s** |

The chosen run is **KAN-11**, the first Jira-triggered investigation against a
cold Memory Bank. Later KAN-* tickets short-circuit on a memory hit and are not
representative of the full agent execution path.

---

## Agent — Actual Token Usage

5 ADK cycles, 7 tool calls (6 × Cloud Logging MCP, 1 × `post_jira_comment`),
no prompt caching applied (Vertex Anthropic supports it but the ADK Anthropic
adapter does not enable cache writes by default).

```
Cycle  Tool action                                      Input    Output  Cost
  1    initial prompt + load tools                       6,806      236  $0.023958
  2    list_log_names + list_log_entries                36,055      383  $0.113910
  3    2× list_log_entries (parallel)                   43,013      387  $0.134844
  4    2× list_log_entries (parallel)                   44,776    1,577  $0.157983
  5    post_jira_comment + final reply                  46,404      355  $0.144537
       ────────────────────────────────────────────────────────────────
       Total                                          177,054    2,938  $0.575232
```

- **Wall-clock:** 61.350 s
- **Tool calls:** 7 — `list_log_names` → `list_log_entries` ×5 (mostly parallel) → `post_jira_comment`
- **Cycles:** 5

Input tokens grow each cycle because the entire conversation history is
re-sent — there is no cache hit credit on this run.

---

## Infrastructure Costs Per Incident

### 1. Jira webhook → Cloud Function Gen 2 (HTTPS trigger)

**Pricing source:** Cloud Run (Cloud Functions Gen 2 uses Cloud Run billing) —
`https://cloud.google.com/run/pricing`, us-east1 (Tier 1), request-based.

Config from `scripts/deploy_jira_webhook.sh`: **512 MiB memory, default 1 vCPU,
540 s timeout**. The function blocks until the agent's `streamQuery` finishes
(stream is fully drained), so CF wall-clock ≈ agent wall-clock ≈ 61.35 s.

| Item | Calculation | Cost |
|---|---|---|
| vCPU active | 1 vCPU × 61.35 s × $0.000024 | $0.001472 |
| Memory active | 0.5 GiB × 61.35 s × $0.0000025 | $0.0000767 |
| Request | 1 × $0.40 / 1,000,000 | $0.0000004 |
| **Cloud Function total** | | **$0.001549** |

Free tier: 180,000 vCPU-s + 360,000 GiB-s + 2 M requests / month — covers this
incident in practice.

### 2. Secret Manager (jira-webhook secret)

**Pricing source:** `https://cloud.google.com/secret-manager/pricing`.

Two accesses per incident (Cloud Function for HMAC verify + Jira creds, agent's
`post_jira_comment` for Jira creds).

| Item | Calculation | Cost |
|---|---|---|
| Access operations | 2 ops, first 10,000 / month free | **$0.0000000** |
| Active version | $0.06 / version / month → ≪ $0.001 amortised | negligible |

### 3. Vertex AI Agent Engine — Runtime

**Pricing source:** Gemini Enterprise Agent Platform pricing page →
*Agent Runtime* section: `vCPU $0.0864 / hour` and `RAM $0.009 / GiB-hour`
after the per-project free tier (50 vCPU-h + 100 GiB-h / month). **Idle time
is not billed.**

Engine config from runtime describe: **4 vCPU / 8 GiB**, `min_instances=1`,
`max_instances=10`.

Per-incident, billing is wall-clock (the runtime is "active" for the entire
invocation, including while waiting on LLM responses — Cloud Run-style):

| Item | Calculation | Cost |
|---|---|---|
| vCPU active | 4 × 61.35 s × ($0.0864 / 3600) | $0.005890 |
| Memory active | 8 GiB × 61.35 s × ($0.009 / 3600) | $0.001227 |
| **Agent Runtime total** | | **$0.007117** |

### 4. Memory Bank

**Pricing source:** same page → *Memory Bank* section (billing started
2026-02-11).

| Item | Calculation | Cost |
|---|---|---|
| Memory stored (1 memory written per invocation) | 1 × $0.25 / 1,000 | $0.000250 |
| Memory retrieved (PreloadMemoryTool) | 1 × $0.50 / 1,000, first 1000 / mo free | $0.000000 |
| **Memory Bank total** | | **~$0.000250** |

### 5. Cloud Logging MCP (managed MCP server) → Cloud Logging reads

**Pricing source:** `https://cloud.google.com/stackdriver/pricing`. The MCP
server is free; underlying log **reads / queries are free** (only ingestion
and beyond-30-day retention are billed). No ingestion side effect from the
agent's investigation.

**Cost: $0.**

### 6. Cloud Trace

28 spans per incident. Free tier covers the first 2.5 M spans / month.

**Cost: $0.**

### 7. Claude Sonnet 4.6 (Vertex AI Anthropic, us-east5 — regional endpoint)

**Pricing source:** `https://platform.claude.com/docs/en/about-claude/pricing`

```
Base input        $3.00 / MTok
Output            $15.00 / MTok
5-min cache write $3.75 / MTok    (not used)
1-h cache write   $6.00 / MTok    (not used)
Cache read        $0.30 / MTok    (not used)
```

Sonnet 4.6 + regional endpoint adds a **10 % premium** (per same pricing page).
The agent uses `claude-sonnet-4-6` on `us-east5` which is regional.

| Token type | Tokens | Base rate | Base cost | Cost (+10 % regional) |
|---|---|---|---|---|
| Input | 177,054 | $3.00 / MTok | $0.531162 | $0.584278 |
| Output | 2,938 | $15.00 / MTok | $0.044070 | $0.048477 |
| **Total Claude** | | | **$0.575232** | **$0.632755** |

---

## Total Per Incident

Using regional (actual) Claude pricing:

| Service | Cost | Source | % of total |
|---|---|---|---|
| Cloud Function Gen 2 (jira-webhook) | $0.001549 | Cloud Run pricing page | 0.24 % |
| Secret Manager | ~$0 (free tier) | Secret Manager pricing | 0.00 % |
| Vertex AI Agent Runtime (4 vCPU / 8 GiB, 61.35 s) | $0.007117 | Gemini Enterprise Agent Platform pricing | 1.10 % |
| Memory Bank | $0.000250 | Gemini Enterprise Agent Platform pricing | 0.04 % |
| Cloud Logging MCP + Cloud Logging | $0 | free reads | 0.00 % |
| Cloud Trace | $0 | free under 2.5 M spans/mo | 0.00 % |
| **Claude Sonnet 4.6 (us-east5)** | **$0.632755** | Anthropic pricing + 10 % regional premium | **98.6 %** |
| **Total** | **$0.641671** | | |

**Claude is ~99 % of the total. Agent Runtime adds ~$0.007 per incident (4 vCPU / 8 GiB, ~61 s wall-clock).**

---

## Human SRE — Realistic Timeline

*(from `human.py`)*

Alert: `[ALERT] api-service CPU utilization above 85% - production` (91 %, threshold 85 %).

The CPU alert is deliberately ambiguous — high CPU could be a traffic surge, a
slow dependency holding connections open, or a runaway process. The human must
investigate to find the DB root cause.

| Phase | Time |
|---|---|
| Alert triage — check deploys, rule out traffic spike | 5–10 min |
| Check metrics dashboard — discover error rate spike | 3–5 min |
| Pull and read api-service logs | 5 min |
| Realise DB is the bottleneck, pull db-primary logs | 5 min |
| Investigate notification-service red herring | 5–10 min |
| Understand `auto_explain` Seq Scan output | 5–10 min |
| Confirm diagnosis with `EXPLAIN ANALYZE` | 5 min |
| Decide on safe fix, get approval | 5–10 min |
| **Total** | **38–60 min** |

The extra 3–5 minutes vs a "500 error" alert comes from the indirection: a CPU
alert doesn't point at the DB. The SRE must first discover that CPU is high
*because* of the DB issue.

### When the human knows it's a missing index

**Step 4** — reading the `auto_explain` Seq Scan output in `db-primary` logs.
Still requires one manual step (`\d orders` to confirm no index exists on
`customer_id`) before declaring root cause.

| Experience level | Time to diagnose |
|---|---|
| Junior SRE | 2–4 hours (doesn't recognise Seq Scan; may escalate to DBA) |
| Senior SRE | 38–60 min (recognises Seq Scan; still runs `EXPLAIN ANALYZE`) |
| With APM dashboards | 5–10 min (slow query surfaced before manual log digging) |

**SRE salary:** $150 K / yr ÷ 2,080 hrs = **$72 / hr**
**Cost of a 45-min incident:** $72 × 0.75 = **$54** (without on-call premium)

> On-call premium (nights / weekends) typically adds 1.5–2× to the hourly rate
> but is excluded here for a conservative comparison.

---

## Head-to-Head

| Dimension | Human SRE | Agent (GCP) |
|---|---|---|
| Time to diagnose | 38–60 min | **61.35 s** |
| Cost per incident | $46–72 (without on-call premium) | **$0.64** |
| Red herrings | Investigated (5–10 min lost) | Dismissed immediately |
| Availability | On-call rotation | Always on, no paging required |
| Consistency | Varies by shift | Same reasoning every invocation |
| Jira comment | Written after triage | Posted automatically as part of triage |
| Schema check | Ran `\d orders` manually | Inferred from `Seq Scan` + `rows=1284901` |

---

## Monthly Projection

SRE: $150 K / yr = $72 / hr, 45-min avg incident = $54 / incident (without on-call premium).
Agent: $0.641671 per incident (KAN-11 baseline — first run, cold Memory Bank).

| Incidents / month | GCP cost | Human SRE cost | Saving |
|---|---|---|---|
| 10 | $6.42 | $540 | ~$534 |
| 50 | $32.08 | $2,700 | ~$2,668 |
| 200 | $128.33 | $10,800 | ~$10,672 |
| 1,000 | $641.67 | $54,000 | ~$53,358 |

> Agent handles first-response triage only. Senior SRE still required for fix
> execution, change management, and post-mortems.

---

## Cost Reduction Levers

Claude = 98.6 % of the known bill. All meaningful optimisation is here.

| Lever | Potential saving | Status |
|---|---|---|
| Enable prompt caching on Vertex Anthropic | ~60–75 % of input cost (cycles 2–5 share history) | **Not enabled** — would drop per-incident cost from ~$0.64 to ~$0.20–0.25 |
| Memory Bank short-circuit (post-KAN-11) | ~50–80 % saving on repeat scenarios | Active — observed KAN-12 and onward use far fewer tokens |
| Switch to Claude Haiku 4.5 for first-pass triage | 67 % saving (Haiku $1/$5 vs Sonnet $3/$15) | Available, would require model routing |
| Global endpoint instead of us-east5 | 10 % saving on Claude bill (~$0.06 / incident) | Configuration change in `app/agent.py` |
| Tighter agent prompt + tool result truncation | Cuts cycle 2+ input growth | Not yet applied |

---
