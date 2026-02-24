import asyncio
import aiohttp
import streamlit as st
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from dateutil import parser

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Base directory for server-side storage
BASE_SAVE_DIR = "dynatrace_distributed_traces"

# ────────────────────────────────────────────────
# Core Fetcher Logic
# ────────────────────────────────────────────────
class DynatraceServerSaver:
    def __init__(self, tenant_url, bearer_token):
        self.tenant_url = tenant_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {bearer_token}",
            "Content-Type": "application/json"
        }
        self.semaphore = asyncio.Semaphore(10)

    async def get_trace_ids(self, session, app, endpoint, start, end):
        """Uses DQL to find trace IDs in Grail."""
        url = f"{self.tenant_url}/platform/storage/query/v1/query:execute"
        query = f"""
        fetch spans, from: "{start}", to: "{end}"
        | filter matchesValue(service.name, {json.dumps(app)})
        | filter matchesValue(span.name, {json.dumps(endpoint)})
        | fields `trace.id`
        | limit 100
        """
        async with session.post(url, headers=self.headers, json={"query": query}) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            
            # Simple polling logic for DQL
            if data.get("state") != "SUCCEEDED":
                token = data.get("requestToken")
                poll_url = f"{self.tenant_url}/platform/storage/query/v1/query:poll/{token}"
                for _ in range(10):
                    await asyncio.sleep(2)
                    async with session.get(poll_url, headers=self.headers) as pr:
                        pd = await pr.json()
                        if pd.get("state") == "SUCCEEDED":
                            return [r["trace.id"] for r in pd["result"]["records"]]
                return []
            return [r["trace.id"] for r in data["result"]["records"]]

    async def fetch_full_trace(self, session, tid):
        """Fetches the actual trace detail from the v2 API."""
        async with self.semaphore:
            url = f"{self.tenant_url}/api/v2/traces/{tid}"
            async with session.get(url, headers=self.headers) as resp:
                return await resp.json() if resp.status == 200 else None

    def save_to_disk(self, data, app, endpoint):
        """Creates folders and saves the file."""
        # Sanitize folder names to prevent path errors
        clean_app = re.sub(r'[^\w\-]', '_', app)
        clean_end = re.sub(r'[^\w\-]', '_', endpoint)
        
        path = os.path.join(BASE_SAVE_DIR, clean_app, clean_end)
        os.makedirs(path, exist_ok=True)
        
        filename = f"traces_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        full_path = os.path.join(path, filename)
        
        with open(full_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return full_path

# ────────────────────────────────────────────────
# Streamlit Interface
# ────────────────────────────────────────────────
st.set_page_config(page_title="Trace Server-Saver", page_icon="💾")
st.title("💾 Server-Side Trace Archiver")

with st.sidebar:
    st.header("Auth Configuration")
    t_url = st.text_input("Tenant URL", placeholder="https://abc12345.live.dynatrace.com")
    c_id = st.text_input("Client ID")
    c_secret = st.text_input("Client Secret", type="password")

# Input Fields
col1, col2 = st.columns(2)
with col1:
    app_input = st.text_input("Service/Application Name")
with col2:
    end_input = st.text_input("Endpoint/Web Request URL")

if st.button("Fetch and Archive to Server", type="primary"):
    if not all([t_url, c_id, c_secret, app_input, end_input]):
        st.error("Please fill in all fields.")
    else:
        async def execute_workflow():
            # 1. Get OAuth Token
            token_url = "https://sso.dynatrace.com/as/token.oauth2"
            auth_data = {
                "grant_type": "client_credentials",
                "client_id": c_id,
                "client_secret": c_secret,
                "scope": "storage:read trace.read"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(token_url, data=auth_data) as r:
                    if r.status != 200:
                        st.error(f"Auth Failed: {await r.text()}")
                        return
                    token = (await r.json()).get("access_token")

                # 2. Initialize Fetcher
                saver = DynatraceServerSaver(t_url, token)
                
                # 3. Get Traces
                st.info("Querying Grail for Trace IDs...")
                start = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
                end = datetime.now(timezone.utc).isoformat()
                
                tids = await saver.get_trace_ids(session, app_input, end_input, start, end)
                
                if not tids:
                    st.warning("No traces found for this timeframe.")
                    return

                st.info(f"Found {len(tids)} traces. Downloading details...")
                tasks = [saver.fetch_full_trace(session, tid) for tid in tids]
                results = await asyncio.gather(*tasks)
                valid_data = [r for r in results if r]

                # 4. Save to Server
                final_payload = {
                    "app": app_input,
                    "endpoint": end_input,
                    "count": len(valid_data),
                    "data": valid_data
                }
                
                file_loc = saver.save_to_disk(final_payload, app_input, end_input)
                st.success(f"Archived {len(valid_data)} traces to the server!")
                st.code(f"Saved at: {file_loc}")

        asyncio.run(execute_workflow())
