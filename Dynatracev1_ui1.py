# dynatrace_app.py
# Streamlit Dynatrace Explorer with logging, app prefetch, and save-to-folder workflow.
# Run:
#   pip install streamlit requests pandas python-dateutil
#   streamlit run dynatrace_app.py

import os
import json
import math
import time
import logging
import requests
import pandas as pd
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta, timezone
from dateutil import parser as dtparser

import streamlit as st

# =========================
# Folders & Logging
# =========================
LOG_DIR = "dynatrace_logs"
SAVE_DIR = "requested_files"
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(SAVE_DIR, exist_ok=True)

def setup_logger():
    logger = logging.getLogger("dynatrace_ui")
    if logger.handlers:
        return logger  # already configured
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        os.path.join(LOG_DIR, "app.log"),
        maxBytes=1_000_000,
        backupCount=5,
        encoding="utf-8"
    )
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s"
    )
    handler.setFormatter(fmt)
    logger.addHandler(handler)
    # Also log to a per-run file
    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_handler = logging.FileHandler(os.path.join(LOG_DIR, f"run_{run_ts}.log"), encoding="utf-8")
    run_handler.setFormatter(fmt)
    logger.addHandler(run_handler)
    logger.propagate = False
    return logger

log = setup_logger()
log.info("===== Streamlit Dynatrace Explorer started =====")

# =========================
# Page / Theme (Blue & White)
# =========================
st.set_page_config(page_title="Dynatrace Explorer", layout="wide", page_icon="📈")

BLUE = "#1f6feb"
BLUE_SOFT = "#eaf2ff"
WHITE = "#ffffff"

st.markdown(
    f"""
    <style>
      :root {{
        --primary: {BLUE};
        --accent: {BLUE};
      }}
      .stApp {{
        background: linear-gradient(180deg, {BLUE_SOFT} 0%, {WHITE} 40%);
      }}
      .app-title {{
        font-size: 2.0rem; font-weight: 700; margin-bottom: 0.2rem; color: #0a2540;
      }}
      .app-subtitle {{
        color: #4a5568; margin-bottom: 1.2rem;
      }}
      .kpi {{
        border-radius: 16px; padding: 16px; background: {WHITE};
        border: 1px solid #e6ecf2; box-shadow: 0 1px 3px rgba(0,0,0,0.06);
      }}
      .kpi h3 {{ margin: 0; font-size: 0.95rem; color: #475569; }}
      .kpi .value {{ font-size: 1.4rem; font-weight: 700; color: #111827; }}
      .small {{ font-size: 0.85rem; color: #64748b; }}
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div class="app-title">Dynatrace Interactive Explorer</div>', unsafe_allow_html=True)
st.markdown('<div class="app-subtitle">Enter your application name and time window to fetch metrics. Optional: filter by a specific name (e.g., a user action).</div>', unsafe_allow_html=True)

# =========================
# Sidebar Inputs
# =========================
with st.sidebar:
    st.header("🔧 Settings")

    # Prefer secrets if available
    default_base = st.secrets.get("dynatrace", {}).get("base_url", "")
    default_token = st.secrets.get("dynatrace", {}).get("api_token", "")

    base_url = st.text_input("Dynatrace Base URL", value=default_base, placeholder="https://<env>.live.dynatrace.com")
    api_token = st.text_input("API Token", value=default_token, type="password", placeholder="dt0c01...")

    st.caption("Token needs API v2 scopes: **Read entities** and **Read metrics**.")

    st.divider()
    st.header("🎯 Query")
    app_name = st.text_input("Application Name (exact or partial)", placeholder="e.g., My Web App")
    specific_name = st.text_input("Specific Name (optional)", placeholder="e.g., /checkout or Click Login")

    range_choice = st.selectbox(
        "Time Range",
        ["Last 15 minutes", "Last 1 hour", "Last 6 hours", "Last 24 hours", "Last 7 days", "Custom"],
        index=2
    )

    if range_choice == "Custom":
        colc1, colc2 = st.columns(2)
        with colc1:
            start_dt = st.datetime_input("From (local time)", value=datetime.now().astimezone() - timedelta(hours=6))
        with colc2:
            end_dt = st.datetime_input("To (local time)", value=datetime.now().astimezone())
    else:
        start_dt = None
        end_dt = None

    st.divider()
    st.header("📊 Metrics")
    metric_set = st.multiselect(
        "Choose Metrics",
        options=[
            "RUM: User action count",
            "RUM: JS errors per minute",
            "RUM: Apdex",
            "Service: Response time (50th)",
            "Service: Response time (95th)",
        ],
        default=["RUM: User action count", "RUM: Apdex"],
    )

    st.divider()
    st.header("🧭 Prefetch Applications")
    prefetch_count = st.slider("How many to preview", 5, 100, 25, 5)
    prefetch_btn = st.button("Fetch sample applications")

    run = st.button("Fetch Data", type="primary")

# =========================
# API Helpers
# =========================
def auth_headers(token: str):
    return {"Authorization": f"Api-Token {token}"}

def dt_iso(ts: datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).isoformat()

def window_to_from_to(choice: str, start_dt, end_dt):
    now = datetime.now(timezone.utc)
    if choice == "Custom":
        if start_dt is None or end_dt is None:
            return None, None
        return start_dt.astimezone(timezone.utc), end_dt.astimezone(timezone.utc)
    delta = {
        "Last 15 minutes": timedelta(minutes=15),
        "Last 1 hour": timedelta(hours=1),
        "Last 6 hours": timedelta(hours=6),
        "Last 24 hours": timedelta(hours=24),
        "Last 7 days": timedelta(days=7),
    }[choice]
    return now - delta, now

@st.cache_data(show_spinner=False, ttl=300)
def resolve_application_ids(base_url: str, token: str, name_query: str):
    if not name_query:
        return []
    selector = f'type(APPLICATION),entityName.contains("{name_query}")'
    params = {"entitySelector": selector, "pageSize": 200}
    url = f"{base_url.rstrip('/')}/api/v2/entities"
    r = requests.get(url, headers=auth_headers(token), params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    items = data.get("entities", [])
    apps = [{"id": it.get("entityId"), "name": it.get("displayName")} for it in items]
    return apps

@st.cache_data(show_spinner=False, ttl=300)
def list_applications(base_url: str, token: str, limit: int = 25):
    """
    Prefetch a simple list of APPLICATION entities (first page).
    """
    selector = "type(APPLICATION)"
    params = {"entitySelector": selector, "pageSize": max(1, min(200, limit))}
    url = f"{base_url.rstrip('/')}/api/v2/entities"
    r = requests.get(url, headers=auth_headers(token), params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    items = data.get("entities", [])
    apps = [{"id": it.get("entityId"), "name": it.get("displayName")} for it in items]
    return pd.DataFrame(apps)

def metric_selector_for(label: str, app_id: str, specific_name: str | None):
    mapping = {
        "RUM: User action count": "builtin:apps.web.actionCount",
        "RUM: JS errors per minute": "builtin:apps.web.jsErrorsPerMinute",
        "RUM: Apdex": "builtin:apps.web.apdex",
        "Service: Response time (50th)": "builtin:service.response.time:percentile(50)",
        "Service: Response time (95th)": "builtin:service.response.time:percentile(95)",
    }
    m = mapping[label]
    parts = [m]
    if label.startswith("RUM"):
        if app_id:
            parts.append(f'filter(eq(dt.entity.application,"{app_id}"))')
        if specific_name:
            parts.append(f'filter(eq("userActionName","{specific_name}"))')
    else:
        if specific_name:
            parts.append(f'filter(eq("service.name","{specific_name}"))')
    return ":".join(parts)

@st.cache_data(show_spinner=False, ttl=300)
def query_metric_series(base_url: str, token: str, metric_selector: str, t_from: datetime, t_to: datetime, resolution="Inf"):
    url = f"{base_url.rstrip('/')}/api/v2/metrics/query"
    params = {
        "metricSelector": metric_selector,
        "from": dt_iso(t_from),
        "to": dt_iso(t_to),
        "resolution": resolution,
        "pageSize": 500
    }
    r = requests.get(url, headers=auth_headers(token), params=params, timeout=60)
    r.raise_for_status()
    payload = r.json()
    return payload.get("result", []), payload.get("warnings", [])

def result_to_dataframe(result_list):
    rows = []
    for res in result_list:
        metric = res.get("metricId")
        ts = res.get("timestamps", [])
        for series in res.get("data", []):
            dims = series.get("dimensionMap", {})
            vals = series.get("values", [])
            for t, v in zip(ts, vals):
                rows.append({
                    "timestamp": datetime.fromtimestamp(t/1000, tz=timezone.utc),
                    "metric": metric,
                    "value": v,
                    **dims
                })
    df = pd.DataFrame(rows)
    if not df.empty:
        df.sort_values("timestamp", inplace=True)
    return df

def log_safe(msg: str):
    # Avoid logging secrets
    msg = msg.replace(api_token, "***") if api_token else msg
    log.info(msg)

# =========================
# Prefetch UI
# =========================
if prefetch_btn:
    if not base_url or not api_token:
        st.warning("Provide Base URL and API Token to prefetch sample applications.")
    else:
        try:
            df_apps = list_applications(base_url, api_token, prefetch_count)
            if df_apps.empty:
                st.info("No applications found.")
                log_safe("Prefetch: No applications returned.")
            else:
                st.success(f"Showing {len(df_apps)} application(s):")
                st.dataframe(df_apps, use_container_width=True, hide_index=True)
                log_safe(f"Prefetch: listed {len(df_apps)} applications.")
        except requests.HTTPError as e:
            detail = e.response.text if hasattr(e, "response") and e.response is not None else str(e)
            st.error(f"HTTP error while listing applications.\n\nDetails: {detail}")
            log_safe(f"Prefetch HTTPError: {detail}")
        except Exception as ex:
            st.error(f"Unexpected error while listing applications: {ex}")
            log_safe(f"Prefetch Exception: {ex}")

# =========================
# Main Action
# =========================
if run:
    if not base_url or not api_token:
        st.error("Please provide Dynatrace Base URL and API Token.")
        log_safe("Run blocked: missing base_url or api_token.")
    elif not app_name:
        st.error("Please enter an Application Name (exact or partial).")
        log_safe("Run blocked: missing app_name.")
    else:
        with st.spinner("Resolving application(s) and fetching metrics…"):
            try:
                t_from, t_to = window_to_from_to(range_choice, start_dt, end_dt)
                if not t_from or not t_to or t_from >= t_to:
                    st.error("Please provide a valid time window.")
                    log_safe("Invalid time window provided.")
                    st.stop()

                log_safe(f"Inputs -> app_name='{app_name}', specific_name='{specific_name}', range='{range_choice}', "
                         f"metrics={metric_set}, from={t_from}, to={t_to}")

                apps = resolve_application_ids(base_url, api_token, app_name)
                log_safe(f"Resolved {len(apps)} application(s) for query '{app_name}'.")

                if not apps:
                    st.warning("No applications matched your name query.")
                    st.stop()

                if len(apps) > 1:
                    st.info("Multiple matches found. Please pick one.")
                    names = [f'{a["name"]}  ({a["id"]})' for a in apps]
                    sel = st.selectbox("Matched Applications", names)
                    sel_idx = names.index(sel)
                    app_id = apps[sel_idx]["id"]
                    app_disp = apps[sel_idx]["name"]
                else:
                    app_id = apps[0]["id"]
                    app_disp = apps[0]["name"]

                st.success(f"Using application: **{app_disp}** (`{app_id}`)")
                log_safe(f"Using app_id={app_id}, app_name='{app_disp}'.")

                dfs = []
                warnings_all = []
                for label in metric_set:
                    ms = metric_selector_for(label, app_id, specific_name.strip() if specific_name else None)
                    result, warns = query_metric_series(base_url, api_token, ms, t_from, t_to)
                    df = result_to_dataframe(result)
                    df["label"] = label
                    df["application"] = app_disp
                    dfs.append(df)
                    warnings_all.extend(warns or [])
                    log_safe(f"Metric '{label}' -> rows={len(df)}; selector='{ms}'")

                if warnings_all:
                    with st.expander("API Warnings"):
                        for w in warnings_all:
                            st.write("•", w)
                    log_safe(f"API warnings: {warnings_all}")

                if not any([not d.empty for d in dfs]):
                    st.warning("No metric data returned for the selected inputs.")
                    log_safe("No data returned for all metrics.")
                    st.stop()

                # KPI Tiles
                k1, k2, k3, k4 = st.columns(4)
                k_cols = [k1, k2, k3, k4]
                for i, df in enumerate(dfs[:4]):
                    with k_cols[i]:
                        st.markdown('<div class="kpi">', unsafe_allow_html=True)
                        st.markdown(f"<h3>{df['label'].iloc[0] if not df.empty else 'Metric'}</h3>", unsafe_allow_html=True)
                        if not df.empty:
                            last = df.dropna(subset=["value"]).tail(1)
                            if not last.empty:
                                val = last["value"].values[0]
                                ts = last["timestamp"].values[0]
                                st.markdown(f'<div class="value">{val:.4g}</div>', unsafe_allow_html=True)
                                st.markdown(f'<div class="small">{ts}</div>', unsafe_allow_html=True)
                            else:
                                st.markdown(f'<div class="value">–</div>', unsafe_allow_html=True)
                        else:
                            st.markdown(f'<div class="value">–</div>', unsafe_allow_html=True)
                        st.markdown('</div>', unsafe_allow_html=True)

                # Charts
                for df in dfs:
                    if df.empty:
                        continue
                    title = df["label"].iloc[0]
                    st.markdown(f"### {title}")
                    pivot = df.pivot_table(
                        index="timestamp",
                        columns=[c for c in df.columns if c not in ["timestamp", "metric", "value", "label", "application"]],
                        values="value",
                        aggfunc="mean"
                    )
                    if isinstance(pivot.columns, pd.MultiIndex):
                        pivot.columns = [" | ".join(map(str, c)).strip() for c in pivot.columns]
                    pivot = pivot.sort_index()
                    st.line_chart(pivot)

                # Raw Data
                full = pd.concat([d for d in dfs if not d.empty], ignore_index=True)
                with st.expander("Show raw data"):
                    st.dataframe(full, use_container_width=True)

                # =========================
                # Save Workflow (button → prompt for user story → save files)
                # =========================
                st.divider()
                st.subheader("💾 Save Results")

                if "wants_save" not in st.session_state:
                    st.session_state["wants_save"] = False

                if not st.session_state["wants_save"]:
                    if st.button("Save these results…"):
                        st.session_state["wants_save"] = True
                        st.experimental_rerun()
                else:
                    user_story = st.text_input("Enter User Story number (e.g., US12345)", "")
                    col_save, col_cancel = st.columns([1,1])
                    with col_save:
                        if st.button("Confirm & Save"):
                            if not user_story.strip():
                                st.error("Please enter a valid User Story number.")
                            else:
                                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                                base_name = f"{user_story.strip()}__{timestamp}"
                                # Save data CSV and JSON
                                csv_path = os.path.join(SAVE_DIR, f"{base_name}.csv")
                                json_path = os.path.join(SAVE_DIR, f"{base_name}.json")
                                meta_path = os.path.join(SAVE_DIR, f"{base_name}__meta.json")

                                # Convert timestamps to ISO for JSON
                                full_to_save = full.copy()
                                if not full_to_save.empty:
                                    full_to_save["timestamp"] = full_to_save["timestamp"].astype(str)

                                full_to_save.to_csv(csv_path, index=False)
                                full_to_save.to_json(json_path, orient="records", force_ascii=False, indent=2)

                                meta = {
                                    "saved_at": datetime.now().isoformat(),
                                    "user_story": user_story.strip(),
                                    "inputs": {
                                        "base_url": base_url,  # do not include token
                                        "application_id": app_id,
                                        "application_name": app_disp,
                                        "specific_name": specific_name,
                                        "time_from": dt_iso(t_from),
                                        "time_to": dt_iso(t_to),
                                        "metrics": list(metric_set),
                                    },
                                    "files": {
                                        "csv": csv_path,
                                        "json": json_path
                                    }
                                }
                                with open(meta_path, "w", encoding="utf-8") as f:
                                    json.dump(meta, f, ensure_ascii=False, indent=2)

                                st.success(f"Saved to `{SAVE_DIR}` as:\n- {os.path.basename(csv_path)}\n- {os.path.basename(json_path)}\n- {os.path.basename(meta_path)}")
                                log_safe(f"Saved results for {user_story} -> {csv_path}, {json_path}, {meta_path}")
                                st.session_state["wants_save"] = False
                    with col_cancel:
                        if st.button("Cancel"):
                            st.session_state["wants_save"] = False
                            st.info("Save cancelled.")

            except requests.HTTPError as e:
                try:
                    detail = e.response.json()
                except Exception:
                    detail = e.response.text if hasattr(e, "response") and e.response is not None else str(e)
                st.error(f"HTTP error: {e}\n\nDetails: {detail}")
                log_safe(f"HTTPError: {detail}")
            except Exception as ex:
                st.error(f"Unexpected error: {ex}")
                log_safe(f"Exception: {ex}")

# =========================
# Footer Help
# =========================
with st.expander("ℹ️ Notes"):
    st.markdown(
        """
- **APIs:** Entities v2 (`/api/v2/entities`) and Metrics v2 (`/api/v2/metrics/query`).
- **Prefetch:** Use *Fetch sample applications* in the sidebar to preview available application names.
- **Saving:** When you click **Save these results…**, you'll be prompted for a **User Story** number.  
  Files are written into the `requested_files/` folder along with a metadata JSON.
- **Logging:** All actions/errors are written to `dynatrace_logs/` (`app.log` and per-run `run_*.log`).  
  API tokens are **never** written to logs.
        """
    )
