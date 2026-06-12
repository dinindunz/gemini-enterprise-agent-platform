# type: ignore
"""
KAN-11 — automated Jira-triggered SRE agent run.

Reconstructed from Cloud Trace span tree
(trace id: dfa55460d7d8ad039a0a85c90fd4805d), 28 spans, 5 ADK cycles.

This run is the first KAN-* issue against a cold Memory Bank, so the agent
executed the full investigation path; KAN-12 onwards short-circuit on a
PreloadMemoryTool hit and use far fewer tokens.

The full prompt-response content was not captured to GCS for this run
(the OTel upload hook wasn't yet wired). All numbers below come from
Cloud Trace span labels and Cloud Logging stderr.
"""

# ---------------------------------------------------------------------------
# Wall-clock
# ---------------------------------------------------------------------------
# Jira webhook → Cloud Function received: 2026-06-11 11:39:35.x UTC
# Agent runtime first span:                2026-06-11 11:39:36.938 UTC
# Final call_llm complete:                 2026-06-11 11:40:38.288 UTC
# Wall-clock from invocation start:        61.35s

# ---------------------------------------------------------------------------
# Cycle / cost breakdown
# ---------------------------------------------------------------------------
# Vertex AI Anthropic, regional endpoint us-east5:
#   Input  : $3.00 / 1M tok
#   Output : $15.00 / 1M tok
# (regional endpoints on Claude Sonnet 4.5+ carry a 10% premium per
#  https://platform.claude.com/docs/en/about-claude/pricing — the cost column
#  below uses base rates; multiply by 1.1 for the regional-actual figure.)

CYCLE_TOKENS = [
    # cycle, label,                              in_tok,  out_tok,  in_cost,    out_cost,   final
    (1, "initial prompt + load tools",            6_806,    236, 0.020418, 0.003540, 0.023958),
    (2, "list_log_names + list_log_entries",     36_055,    383, 0.108165, 0.005745, 0.113910),
    (3, "2x list_log_entries (parallel)",        43_013,    387, 0.129039, 0.005805, 0.134844),
    (4, "2x list_log_entries (parallel)",        44_776,  1_577, 0.134328, 0.023655, 0.157983),
    (5, "post_jira_comment + final reply",       46_404,    355, 0.139212, 0.005325, 0.144537),
]

TOTAL_IN  = sum(r[2] for r in CYCLE_TOKENS)   # 177_054
TOTAL_OUT = sum(r[3] for r in CYCLE_TOKENS)   #   2_938
TOTAL_COST = sum(r[6] for r in CYCLE_TOKENS)  # $0.575232

# ---------------------------------------------------------------------------
# Tool calls observed in the span tree
# ---------------------------------------------------------------------------
# 7 tool calls in total, all via the Cloud Logging MCP server except the last:
TOOL_CALLS = [
    "11:39:41  logging_googleapis_com_list_log_names    (MCP)",
    "11:39:41  logging_googleapis_com_list_log_entries  (MCP, parallel)",
    "11:39:48  logging_googleapis_com_list_log_entries  (MCP)",
    "11:39:48  logging_googleapis_com_list_log_entries  (MCP, parallel)",
    "11:39:56  logging_googleapis_com_list_log_entries  (MCP)",
    "11:39:56  logging_googleapis_com_list_log_entries  (MCP, parallel)",
    "11:40:29  post_jira_comment                        (local tool)",
]

# ---------------------------------------------------------------------------
# Final action
# ---------------------------------------------------------------------------
# stderr proves the agent posted a Jira comment back at 11:40:29.583 UTC:
JIRA_COMMENT_POSTED = (
    "[12]      INFO:     [Jira] Comment posted: issue=KAN-11 id=10013"
)

# ---------------------------------------------------------------------------
# Run summary (paste-friendly)
# ---------------------------------------------------------------------------
SUMMARY = f"""
Trace      : dfa55460d7d8ad039a0a85c90fd4805d
Wall-clock : 61.35s
Spans      : 28
Cycles     : 5
Tool calls : 7 (6 x Cloud Logging MCP, 1 x post_jira_comment)
Tokens     : in={TOTAL_IN:,}  out={TOTAL_OUT:,}
Claude cost: ${TOTAL_COST:.6f}   (base rates, no caching, no regional premium)
"""

if __name__ == "__main__":
    print(SUMMARY)
    print("Per-cycle:")
    for c, label, ti, to, ic, oc, tot in CYCLE_TOKENS:
        print(f"  Cycle {c}: {label:40} in={ti:>6} out={to:>5}  cost=${tot:.6f}")
    print()
    print("Tool calls:")
    for t in TOOL_CALLS:
        print(f"  {t}")
    print()
    print(f"Jira: {JIRA_COMMENT_POSTED}")
