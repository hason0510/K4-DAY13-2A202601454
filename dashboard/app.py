from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


REPO_ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = REPO_ROOT / "data" / "logs.jsonl"

TIME_RANGE_MINUTES = 60
REFRESH_SECONDS = 30

LATENCY_P95_THRESHOLD_MS = 3000.0
TRAFFIC_THRESHOLD_RPM = 1.0
ERROR_RATE_THRESHOLD_PCT = 2.0
COST_THRESHOLD_USD = 2.5
TOKENS_THRESHOLD = 50_000.0
QUALITY_THRESHOLD = 0.75

NUMERIC_FIELDS = (
    "latency_ms",
    "tokens_in",
    "tokens_out",
    "cost_usd",
    "quality_score",
)


def load_logs(path: Path) -> tuple[pd.DataFrame, int]:
    """Load valid JSONL records from the dashboard's 60-minute window."""
    records: list[dict] = []
    invalid_lines = 0

    if not path.exists():
        return pd.DataFrame(), invalid_lines

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue

        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            invalid_lines += 1
            continue

        if not isinstance(record, dict):
            invalid_lines += 1
            continue

        records.append(record)

    if not records:
        return pd.DataFrame(), invalid_lines

    frame = pd.DataFrame(records)
    if "ts" not in frame.columns:
        return pd.DataFrame(), invalid_lines

    frame["ts"] = pd.to_datetime(frame["ts"], errors="coerce", utc=True)
    frame = frame.dropna(subset=["ts"]).copy()

    for field in NUMERIC_FIELDS:
        if field in frame.columns:
            frame[field] = pd.to_numeric(frame[field], errors="coerce")

    cutoff = pd.Timestamp.now(tz="UTC") - timedelta(
        minutes=TIME_RANGE_MINUTES
    )
    frame = frame.loc[frame["ts"] >= cutoff].copy()
    return frame.sort_values("ts"), invalid_lines


def event_records(frame: pd.DataFrame, event_name: str) -> pd.DataFrame:
    if "event" not in frame.columns:
        return pd.DataFrame()
    return frame.loc[frame["event"] == event_name].copy()


def style_figure(
    figure: go.Figure,
    *,
    y_title: str,
    height: int = 280,
) -> None:
    figure.update_layout(
        height=height,
        xaxis_title="Time",
        yaxis_title=y_title,
        margin={"l": 20, "r": 20, "t": 30, "b": 20},
        legend={"orientation": "h", "y": 1.12},
        hovermode="x unified",
    )


def render_latency_panel(frame: pd.DataFrame) -> None:
    st.subheader("1. Latency percentiles")
    st.caption(
        "P50/P95/P99 · response_sent.latency_ms · "
        "Unit: ms · SLO: P95 ≤ 3000 ms"
    )

    responses = event_records(frame, "response_sent")
    if "latency_ms" not in responses.columns:
        st.info("Waiting for response_sent.latency_ms data.")
        return

    responses = responses.dropna(subset=["latency_ms"])
    if responses.empty:
        st.info("Waiting for response_sent.latency_ms data.")
        return

    p50 = float(responses["latency_ms"].quantile(0.50))
    p95 = float(responses["latency_ms"].quantile(0.95))
    p99 = float(responses["latency_ms"].quantile(0.99))

    metric_p50, metric_p95, metric_p99 = st.columns(3)
    metric_p50.metric("P50", f"{p50:,.0f} ms")
    metric_p95.metric(
        "P95",
        f"{p95:,.0f} ms",
        f"{p95 - LATENCY_P95_THRESHOLD_MS:,.0f} ms vs SLO",
        delta_color="inverse",
    )
    metric_p99.metric("P99", f"{p99:,.0f} ms")

    timeline = (
        responses.set_index("ts")["latency_ms"]
        .resample("1min")
        .quantile(0.95)
        .rename("p95_ms")
        .reset_index()
    )
    figure = go.Figure(
        go.Scatter(
            x=timeline["ts"],
            y=timeline["p95_ms"],
            mode="lines+markers",
            name="P95 latency",
            line={"color": "#2563eb", "width": 3},
        )
    )
    figure.add_hline(
        y=LATENCY_P95_THRESHOLD_MS,
        line_dash="dash",
        line_color="#dc2626",
        annotation_text="SLO 3000 ms",
        annotation_position="top left",
    )
    style_figure(figure, y_title="Latency (ms)")
    st.plotly_chart(figure, width="stretch", key="latency_chart")


def render_traffic_panel(frame: pd.DataFrame) -> None:
    st.subheader("2. Request traffic")
    st.caption(
        "Count and rate/minute · request_received · "
        "Unit: requests/min · Expected: ≥ 1 request/min"
    )

    requests = event_records(frame, "request_received")
    if requests.empty or "ts" not in requests.columns:
        st.info("Waiting for request_received data.")
        return

    timeline = (
        requests.set_index("ts")
        .resample("1min")
        .size()
        .rename("requests_per_minute")
        .reset_index()
    )
    average_rpm = float(timeline["requests_per_minute"].mean())

    metric_total, metric_rate = st.columns(2)
    metric_total.metric("Requests in window", f"{len(requests):,}")
    metric_rate.metric(
        "Average rate",
        f"{average_rpm:,.2f} req/min",
        f"{average_rpm - TRAFFIC_THRESHOLD_RPM:,.2f} vs expected",
    )

    figure = go.Figure(
        go.Bar(
            x=timeline["ts"],
            y=timeline["requests_per_minute"],
            name="Requests/min",
            marker_color="#0f766e",
        )
    )
    figure.add_hline(
        y=TRAFFIC_THRESHOLD_RPM,
        line_dash="dash",
        line_color="#d97706",
        annotation_text="Expected 1 req/min",
        annotation_position="top left",
    )
    style_figure(figure, y_title="Requests/min")
    st.plotly_chart(figure, width="stretch", key="traffic_chart")


def render_errors_panel(frame: pd.DataFrame) -> None:
    st.subheader("3. Error rate and breakdown")
    st.caption(
        "request_failed / request_received · error_type · "
        "Unit: percent · SLO: ≤ 2%"
    )

    requests = event_records(frame, "request_received")
    failures = event_records(frame, "request_failed")
    if requests.empty or "ts" not in requests.columns:
        st.info("Waiting for request_received and request_failed data.")
        return

    request_counts = requests.set_index("ts").resample("1min").size()
    if failures.empty or "ts" not in failures.columns:
        failure_counts = pd.Series(dtype="int64")
    else:
        failure_counts = failures.set_index("ts").resample("1min").size()

    timeline = pd.concat(
        [
            request_counts.rename("requests"),
            failure_counts.rename("failures"),
        ],
        axis=1,
    ).fillna(0)
    timeline["error_rate_pct"] = (
        timeline["failures"]
        .div(timeline["requests"].replace(0, pd.NA))
        .mul(100)
        .fillna(0)
    )
    timeline = timeline.reset_index()

    error_rate = (len(failures) / len(requests)) * 100
    metric_rate, metric_failed = st.columns(2)
    metric_rate.metric(
        "Error rate",
        f"{error_rate:,.2f}%",
        f"{error_rate - ERROR_RATE_THRESHOLD_PCT:,.2f} pp vs SLO",
        delta_color="inverse",
    )
    metric_failed.metric("Failed requests", f"{len(failures):,}")

    figure = go.Figure(
        go.Scatter(
            x=timeline["ts"],
            y=timeline["error_rate_pct"],
            mode="lines+markers",
            name="Error rate",
            line={"color": "#dc2626", "width": 3},
        )
    )
    figure.add_hline(
        y=ERROR_RATE_THRESHOLD_PCT,
        line_dash="dash",
        line_color="#d97706",
        annotation_text="SLO 2%",
        annotation_position="top left",
    )
    style_figure(figure, y_title="Error rate (%)", height=240)
    st.plotly_chart(figure, width="stretch", key="errors_chart")

    if not failures.empty and "error_type" in failures.columns:
        breakdown = (
            failures["error_type"]
            .fillna("Unknown")
            .value_counts()
            .rename_axis("error_type")
            .reset_index(name="count")
        )
        breakdown_figure = go.Figure(
            go.Bar(
                x=breakdown["error_type"],
                y=breakdown["count"],
                marker_color="#ef4444",
                name="Errors",
            )
        )
        breakdown_figure.update_layout(
            height=210,
            xaxis_title="Error type",
            yaxis_title="Count",
            margin={"l": 20, "r": 20, "t": 10, "b": 20},
        )
        st.plotly_chart(
            breakdown_figure,
            width="stretch",
            key="error_breakdown_chart",
        )
    else:
        st.success("No request_failed events in the current window.")


def render_cost_panel(frame: pd.DataFrame) -> None:
    st.subheader("4. Cost over time")
    st.caption(
        "Sum/minute and total · response_sent.cost_usd · "
        "Unit: USD · Window threshold: ≤ $2.50"
    )

    responses = event_records(frame, "response_sent")
    if "cost_usd" not in responses.columns:
        st.info("Waiting for response_sent.cost_usd data.")
        return

    responses = responses.dropna(subset=["cost_usd"]).sort_values("ts")
    if responses.empty:
        st.info("Waiting for response_sent.cost_usd data.")
        return

    total_cost = float(responses["cost_usd"].sum())
    average_cost = float(responses["cost_usd"].mean())
    metric_total, metric_average = st.columns(2)
    metric_total.metric(
        "Total cost",
        f"${total_cost:,.4f}",
        f"${total_cost - COST_THRESHOLD_USD:,.4f} vs threshold",
        delta_color="inverse",
    )
    metric_average.metric("Average/request", f"${average_cost:,.6f}")

    per_minute = (
        responses.set_index("ts")["cost_usd"]
        .resample("1min")
        .sum()
        .rename("cost_per_minute")
        .reset_index()
    )
    per_minute["cumulative_cost"] = per_minute["cost_per_minute"].cumsum()

    figure = go.Figure()
    figure.add_trace(
        go.Bar(
            x=per_minute["ts"],
            y=per_minute["cost_per_minute"],
            name="Cost/minute",
            marker_color="#7c3aed",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=per_minute["ts"],
            y=per_minute["cumulative_cost"],
            mode="lines+markers",
            name="Cumulative cost",
            line={"color": "#f59e0b", "width": 3},
        )
    )
    figure.add_hline(
        y=COST_THRESHOLD_USD,
        line_dash="dash",
        line_color="#dc2626",
        annotation_text="Threshold $2.50",
        annotation_position="top left",
    )
    style_figure(figure, y_title="Cost (USD)")
    st.plotly_chart(figure, width="stretch", key="cost_chart")


def render_tokens_panel(frame: pd.DataFrame) -> None:
    st.subheader("5. Input and output tokens")
    st.caption(
        "Sum by field · response_sent.tokens_in/tokens_out · "
        "Unit: tokens · Threshold: ≤ 50,000 per field"
    )

    responses = event_records(frame, "response_sent")
    if not {"tokens_in", "tokens_out"}.issubset(responses.columns):
        st.info("Waiting for response_sent token data.")
        return

    tokens = responses[["tokens_in", "tokens_out"]].dropna(how="all")
    if tokens.empty:
        st.info("Waiting for response_sent token data.")
        return

    tokens_in_total = float(tokens["tokens_in"].fillna(0).sum())
    tokens_out_total = float(tokens["tokens_out"].fillna(0).sum())

    metric_input, metric_output = st.columns(2)
    metric_input.metric(
        "Input tokens",
        f"{tokens_in_total:,.0f}",
        f"{tokens_in_total - TOKENS_THRESHOLD:,.0f} vs threshold",
        delta_color="inverse",
    )
    metric_output.metric(
        "Output tokens",
        f"{tokens_out_total:,.0f}",
        f"{tokens_out_total - TOKENS_THRESHOLD:,.0f} vs threshold",
        delta_color="inverse",
    )

    figure = go.Figure(
        go.Bar(
            x=["Input tokens", "Output tokens"],
            y=[tokens_in_total, tokens_out_total],
            marker_color=["#0284c7", "#7c3aed"],
            name="Tokens",
        )
    )
    figure.add_hline(
        y=TOKENS_THRESHOLD,
        line_dash="dash",
        line_color="#dc2626",
        annotation_text="Threshold 50,000",
        annotation_position="top left",
    )
    figure.update_layout(
        height=280,
        xaxis_title="Token field",
        yaxis_title="Tokens",
        margin={"l": 20, "r": 20, "t": 30, "b": 20},
        showlegend=False,
    )
    st.plotly_chart(figure, width="stretch", key="tokens_chart")


def render_quality_panel(frame: pd.DataFrame) -> None:
    st.subheader("6. Quality proxy")
    st.caption(
        "Mean · response_sent.quality_score · "
        "Unit: score 0–1 · SLO: ≥ 0.75"
    )

    responses = event_records(frame, "response_sent")
    if "quality_score" not in responses.columns:
        st.info("Waiting for response_sent.quality_score data.")
        return

    responses = responses.dropna(subset=["quality_score"])
    if responses.empty:
        st.info("Waiting for response_sent.quality_score data.")
        return

    quality_average = float(responses["quality_score"].mean())
    st.metric(
        "Average quality",
        f"{quality_average:,.3f}",
        f"{quality_average - QUALITY_THRESHOLD:,.3f} vs SLO",
    )

    timeline = (
        responses.set_index("ts")["quality_score"]
        .resample("1min")
        .mean()
        .rename("quality_average")
        .reset_index()
    )
    figure = go.Figure(
        go.Scatter(
            x=timeline["ts"],
            y=timeline["quality_average"],
            mode="lines+markers",
            name="Mean quality",
            line={"color": "#16a34a", "width": 3},
        )
    )
    figure.add_hline(
        y=QUALITY_THRESHOLD,
        line_dash="dash",
        line_color="#dc2626",
        annotation_text="SLO 0.75",
        annotation_position="top left",
    )
    figure.update_yaxes(range=[0, 1])
    style_figure(figure, y_title="Quality score")
    st.plotly_chart(figure, width="stretch", key="quality_chart")


def render_recent_logs(frame: pd.DataFrame) -> None:
    if frame.empty:
        return

    preferred_columns = [
        "ts",
        "event",
        "level",
        "service",
        "correlation_id",
        "feature",
        "model",
        "latency_ms",
        "tokens_in",
        "tokens_out",
        "cost_usd",
        "quality_score",
        "error_type",
    ]
    visible_columns = [
        column for column in preferred_columns if column in frame.columns
    ]
    with st.expander("Recent log records used by this dashboard"):
        st.dataframe(
            frame[visible_columns].sort_values("ts", ascending=False).head(20),
            width="stretch",
            hide_index=True,
        )


st.set_page_config(
    page_title="Day 13 AI Observability",
    page_icon="📊",
    layout="wide",
)

st.title("Day 13 AI Observability")
st.caption(
    f"Time range: last {TIME_RANGE_MINUTES} minutes · "
    f"Refresh: {REFRESH_SECONDS} seconds · "
    f"Source: {LOG_PATH.relative_to(REPO_ROOT)}"
)


@st.fragment(run_every=f"{REFRESH_SECONDS}s")
def render_dashboard() -> None:
    frame, invalid_lines = load_logs(LOG_PATH)

    if not LOG_PATH.exists():
        st.warning(
            "data/logs.jsonl is not available yet. The six panels will fill "
            "automatically after the API and load test create logs."
        )
    elif frame.empty:
        st.warning(
            "logs.jsonl exists, but it has no valid records in the last "
            f"{TIME_RANGE_MINUTES} minutes."
        )
    else:
        latest_record = frame["ts"].max().strftime("%Y-%m-%d %H:%M:%S UTC")
        st.success(
            f"Loaded {len(frame):,} records · Latest record: {latest_record}"
        )

    if invalid_lines:
        st.warning(f"Skipped {invalid_lines} invalid JSON line(s).")

    row_one_left, row_one_right = st.columns(2, gap="large")
    with row_one_left:
        with st.container(border=True):
            render_latency_panel(frame)
    with row_one_right:
        with st.container(border=True):
            render_traffic_panel(frame)

    row_two_left, row_two_right = st.columns(2, gap="large")
    with row_two_left:
        with st.container(border=True):
            render_errors_panel(frame)
    with row_two_right:
        with st.container(border=True):
            render_cost_panel(frame)

    row_three_left, row_three_right = st.columns(2, gap="large")
    with row_three_left:
        with st.container(border=True):
            render_tokens_panel(frame)
    with row_three_right:
        with st.container(border=True):
            render_quality_panel(frame)

    render_recent_logs(frame)


render_dashboard()
