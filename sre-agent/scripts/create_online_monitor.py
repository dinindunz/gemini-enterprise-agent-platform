"""Create an Agent Platform OnlineEvaluator (Online Monitor) for the SRE agent.

Runs on a fixed 10-min loop, samples live traces from Cloud Trace/Logging, and
scores them with the Gen AI Evaluation Service. Results land back in Cloud
Logging and as time-series in Cloud Monitoring; view per-trace results under
Agent Platform > Deployments > <agent> > Evaluation.

Prereqs (set on the deployed agent):
  OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental
  OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=EVENT_ONLY

Usage:
  uv run python scripts/create_online_monitor.py
  uv run python scripts/create_online_monitor.py \
      --display-name sre-agent-quality \
      --sampling-percent 25 \
      --max-samples 100 \
      --metric safety_v1 --metric instruction_following_v1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from google.cloud import aiplatform_v1beta1 as aip

OTEL_SEMCONV_VERSION = "1.39.0"
# Valid OnlineEvaluator predefined metrics (rejected by API if not in this set):
#   tool_use_quality_v1, final_response_quality_v1, hallucination_v1, safety_v1
DEFAULT_METRICS = ["tool_use_quality_v1", "final_response_quality_v1", "safety_v1"]


def _agent_resource_from_metadata() -> str | None:
    path = Path(__file__).parent.parent / "deployment_metadata.json"
    if not path.exists():
        return None
    return json.loads(path.read_text()).get("remote_agent_runtime_id")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"))
    parser.add_argument("--location", default=os.environ.get("GOOGLE_CLOUD_REGION", "us-east1"))
    parser.add_argument(
        "--agent-resource",
        default=os.environ.get("AGENT_RUNTIME_RESOURCE") or _agent_resource_from_metadata(),
        help="Full Reasoning Engine resource name. Defaults to deployment_metadata.json.",
    )
    parser.add_argument("--display-name", default="sre-agent-online-monitor")
    parser.add_argument(
        "--sampling-percent", type=int, default=10,
        help="Percent of matching traces to evaluate per run (1-100).",
    )
    parser.add_argument(
        "--max-samples", type=int, default=50,
        help="Cap on evaluations per 10-min run. 0 = unbounded.",
    )
    parser.add_argument(
        "--min-duration-seconds", type=float, default=None,
        help="Only evaluate traces longer than this. Unset = all traces.",
    )
    parser.add_argument(
        "--metric", action="append", default=None,
        help="Predefined metric_spec_name. Repeatable. Defaults: " + ",".join(DEFAULT_METRICS),
    )
    args = parser.parse_args()

    if not args.project:
        sys.exit("GOOGLE_CLOUD_PROJECT not set")
    if not args.agent_resource:
        sys.exit("Agent resource not found — pass --agent-resource or run `make deploy` first")

    metrics = args.metric or DEFAULT_METRICS

    client = aip.OnlineEvaluatorServiceClient(
        client_options={"api_endpoint": f"{args.location}-aiplatform.googleapis.com"},
    )

    trace_scope = aip.OnlineEvaluator.CloudObservability.TraceScope()
    if args.min_duration_seconds is not None:
        Pred = aip.OnlineEvaluator.CloudObservability.TraceScope.Predicate
        NumPred = aip.OnlineEvaluator.CloudObservability.NumericPredicate
        trace_scope.filter = [
            Pred(
                duration=NumPred(
                    comparison_operator=NumPred.ComparisonOperator.GREATER,
                    value=args.min_duration_seconds,
                ),
            ),
        ]

    evaluator = aip.OnlineEvaluator(
        display_name=args.display_name,
        agent_resource=args.agent_resource,
        cloud_observability=aip.OnlineEvaluator.CloudObservability(
            open_telemetry=aip.OnlineEvaluator.CloudObservability.OpenTelemetry(
                semconv_version=OTEL_SEMCONV_VERSION,
            ),
            trace_scope=trace_scope,
        ),
        metric_sources=[
            aip.MetricSource(
                metric=aip.Metric(
                    predefined_metric_spec=aip.PredefinedMetricSpec(metric_spec_name=name),
                ),
            )
            for name in metrics
        ],
        config=aip.OnlineEvaluator.Config(
            random_sampling=aip.OnlineEvaluator.Config.RandomSampling(
                percentage=args.sampling_percent,
            ),
            max_evaluated_samples_per_run=args.max_samples,
        ),
    )

    parent = f"projects/{args.project}/locations/{args.location}"
    print(f"Creating OnlineEvaluator in {parent}")
    print(f"  agent:     {args.agent_resource}")
    print(f"  metrics:   {metrics}")
    print(f"  sampling:  {args.sampling_percent}% (max {args.max_samples}/run)")

    op = client.create_online_evaluator(parent=parent, online_evaluator=evaluator)
    print("Waiting on LRO…")
    result = op.result(timeout=300)
    print(f"✓ Created: {result.name}")
    print(f"  state:   {result.state.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
