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
DT_TENANT_URL = "https://your-env-id.live.dynatrace.com" # Your URL
DT_API_TOKEN  = "dt0c01.XXXXX..."                       # Your Token from Photo 2
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
                return []
            data = await resp.json()
            return [t["traceId"] for t in data.get("traces", [])]

    async def fetch_and_filter_trace(self, session, tid, endpoint_filter):
        """Fetches full trace and checks if it matches the endpoint name."""
        async with self.semaphore:
            url = f"{self.tenant_url}/api/v2/traces/{tid}"
            async with session.get(url, headers=self.headers) as resp:
                if resp.status == 200:
                    trace_data = await resp.json()
                    # Look for the endpoint name in the span names
                    trace_str = json.dumps(trace_data).lower()
                    if endpoint_filter.lower() in trace_str:
                        return trace_data
                return None

    def save_data(self, data, app, endpoint):
        clean_app = re.sub(r'[^\w\-]', '_', app)
        clean_end = re.sub(r'[^\w\-]', '_', endpoint)
        dir_path = os.path.join(BASE_SAVE_DIR, clean_app, clean_end)
        os.makedirs(dir_path, exist_ok=True)
        filename = f"traces_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        full_path = os.path.join(dir_path, filename)
        with open(full_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return full_path

# ────────────────────────────────────────────────
# Streamlit UI
# ────────────────────────────────────────────────
st.set_page_config(page_title="Classic Trace Archiver", layout="centered")
st.title("📂 Trace Archiver (Classic Token)")

service_name = st.text_input("Service Name (for folder naming)")
endpoint_keyword = st.text_input("Endpoint Keyword (e.g., /api/login)")

if st.button("Fetch and Archive", type="primary"):
    async def main():
        fetcher = ClassicTraceFetcher(DT_TENANT_URL, DT_API_TOKEN)
        async with aiohttp.ClientSession() as session:
            with st.spinner("Scanning recent traces..."):
                tids = await fetcher.fetch_recent_trace_ids(session)
            
            if not tids:
                st.warning("No recent traces found. Check your token scopes.")
                return

            with st.spinner(f"Filtering {len(tids)} traces for keyword '{endpoint_keyword}'..."):
                tasks = [fetcher.fetch_and_filter_trace(session, tid, endpoint_keyword) for tid in tids]
                results = await asyncio.gather(*tasks)
                valid_results = [r for r in results if r]

            if valid_results:
                path = fetcher.save_data({"traces": valid_results}, service_name, endpoint_keyword)
                st.success(f"Saved {len(valid_results)} matching traces to {path}")
            else:
                st.warning("No traces matched your endpoint keyword.")

    asyncio.run(main())
