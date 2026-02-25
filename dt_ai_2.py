import asyncio
import aiohttp
import streamlit as st
import json
import os
import re
import logging
from datetime import datetime, timedelta, timezone

# ────────────────────────────────────────────────
# BACKEND CONFIGURATION (HARD-CODED)
# ────────────────────────────────────────────────
DT_TENANT_URL = "https://your-env-id.live.dynatrace.com" 
DT_API_TOKEN  = "dt0c01.YOUR_TOKEN_HERE" 
BASE_SAVE_DIR = "dynatrace_distributed_traces"

# FIXED: Initializing the logger properly
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

    async def fetch_and_filter_trace(self, session, tid, search_query):
        """
        Fetches full trace and checks if the user's input (Endpoint or URL)
        matches any part of the trace metadata or spans.
        """
        async with self.semaphore:
            url = f"{self.tenant_url}/api/v2/traces/{tid}"
            async with session.get(url, headers=self.headers) as resp:
                if resp.status == 200:
                    trace_data = await resp.json()
                    # Deep search for the endpoint/URL keyword
                    trace_content = json.dumps(trace_data).lower()
                    if search_query.lower() in trace_content:
                        return trace_data
                return None

    def save_data(self, data, app, identifier):
        """Saves JSON to server in the requested folder hierarchy."""
        # Sanitize folder names (remove slashes/special characters)
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
st.title("📂 Trace Archiver (Personal Token)")

app_name = st.text_input("Application Name", help="Used to create the primary folder")
search_val = st.text_input("Endpoint Name or Web Request URL", help="The script will save traces matching this value")

if st.button("Fetch and Save to Server", type="primary"):
    if not app_name or not search_val:
        st.warning("Both Application Name and Endpoint/URL are required.")
    else:
        async def run_extraction():
            fetcher = ClassicTraceFetcher(DT_TENANT_URL, DT_API_TOKEN)
            async with aiohttp.ClientSession() as session:
                with st.spinner("Scanning for recent traces..."):
                    tids = await fetcher.fetch_recent_trace_ids(session)
                
                if not tids:
                    st.error("No traces found. Check your token scopes (Read traces).")
                    return

                with st.spinner(f"Filtering {len(tids)} traces for matching content..."):
                    tasks = [fetcher.fetch_and_filter_trace(session, tid, search_val) for tid in tids]
                    results = await asyncio.gather(*tasks)
                    valid_traces = [r for r in results if r]

                if valid_traces:
                    path = fetcher.save_data({"traces": valid_traces}, app_name, search_val)
                    st.success(f"Successfully archived {len(valid_traces)} traces.")
                    st.info(f"File saved at: `{os.path.abspath(path)}`")
                else:
                    st.warning(f"No traces found containing the value: '{search_val}'")

        asyncio.run(run_extraction())
