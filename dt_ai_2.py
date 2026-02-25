import asyncio
import aiohttp
import streamlit as st
import json
import os
import re
from datetime import datetime, timedelta, timezone

# ────────────────────────────────────────────────
# BACKEND CONFIGURATION (HARD-CODED)
# ────────────────────────────────────────────────
# Use the URL of the environment you are currently in
DT_TENANT_URL = "https://your-env-id.live.dynatrace.com" 

# Paste your Personal Access Token (dt0c01...) here
DT_API_TOKEN  = "dt0c01.YOUR_TOKEN_HERE" 

BASE_SAVE_DIR = "dynatrace_distributed_traces"

class ClassicTraceFetcher:
    def __init__(self, tenant_url, api_token):
        self.tenant_url = tenant_url.rstrip("/")
        self.headers = {
            "Authorization": f"Api-Token {api_token}",
            "Content-Type": "application/json"
        }
        self.semaphore = asyncio.Semaphore(5)

    async def fetch_recent_trace_ids(self, session):
        """Fetches latest 100 traces from the last 2 hours."""
        timestamp = int((datetime.now(timezone.utc) - timedelta(hours=2)).timestamp() * 1000)
        url = f"{self.tenant_url}/api/v2/traces"
        params = {"from": timestamp, "pageSize": 100}
        
        async with session.get(url, headers=self.headers, params=params) as resp:
            if resp.status != 200:
                logger.error(f"Failed to fetch trace list: {resp.status}")
                return []
            data = await resp.json()
            return [t["traceId"] for t in data.get("traces", [])]

    async def fetch_and_filter_trace(self, session, tid, user_query):
        """
        Fetches full trace and checks if the user's input (Endpoint or URL)
        exists anywhere in the trace data.
        """
        async with self.semaphore:
            url = f"{self.tenant_url}/api/v2/traces/{tid}"
            async with session.get(url, headers=self.headers) as resp:
                if resp.status == 200:
                    trace_data = await resp.json()
                    # Convert trace to string for a deep search of the URL/Endpoint
                    trace_content = json.dumps(trace_data).lower()
                    if user_query.lower() in trace_content:
                        return trace_data
                return None

    def save_data(self, data, app, identifier):
        """Saves JSON to server in a structured folder."""
        clean_app = re.sub(r'[^\w\-]', '_', app)
        clean_id = re.sub(r'[^\w\-]', '_', identifier)
        
        dir_path = os.path.join(BASE_SAVE_DIR, clean_app, clean_id)
        os.makedirs(dir_path, exist_ok=True)
        
        filename = f"traces_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        full_path = os.path.join(dir_path, filename)
        
        with open(full_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return full_path

# ────────────────────────────────────────────────
# Streamlit UI
# ────────────────────────────────────────────────
st.set_page_config(page_title="Trace Archiver", layout="centered")
st.title("📂 Trace Archiver (Classic)")

app_name = st.text_input("Service / Application Name", help="Used for folder naming")
target_input = st.text_input("Endpoint or Web Request URL", help="The specific URL or Span Name to search for")

if st.button("Fetch and Archive to Server", type="primary"):
    if not app_name or not target_input:
        st.warning("Please provide both a Service Name and a search parameter (URL/Endpoint).")
    else:
        async def run_extraction():
            fetcher = ClassicTraceFetcher(DT_TENANT_URL, DT_API_TOKEN)
            async with aiohttp.ClientSession() as session:
                with st.spinner("Scanning recent traces..."):
                    tids = await fetcher.fetch_recent_trace_ids(session)
                
                if not tids:
                    st.error("No recent traces found. Check your token and URL.")
                    return

                with st.spinner(f"Searching {len(tids)} traces for matches..."):
                    tasks = [fetcher.fetch_and_filter_trace(session, tid, target_input) for tid in tids]
                    results = await asyncio.gather(*tasks)
                    valid_traces = [r for r in results if r]

                if valid_traces:
                    path = fetcher.save_data({"traces": valid_traces}, app_name, target_input)
                    st.success(f"Archived {len(valid_traces)} matching traces.")
                    st.info(f"Saved to server: `{path}`")
                else:
                    st.warning(f"No traces found containing '{target_input}'.")

        asyncio.run(run_extraction())
