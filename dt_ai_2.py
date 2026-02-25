import asyncio
import aiohttp
import streamlit as st
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone

# ────────────────────────────────────────────────
# BACKEND CONFIGURATION (HARD-CODED)
# ────────────────────────────────────────────────
DT_TENANT_URL = "https://abc12345.live.dynatrace.com"  # Replace with your URL
DT_CLIENT_ID  = "dt0s01.XXXXX"                        # Replace with your Client ID
DT_CLIENT_SECRET = "dt0s01.XXXXX.YYYYY"               # Replace with your Secret
BASE_SAVE_DIR = "dynatrace_distributed_traces"

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────
# Backend Logic Class
# ────────────────────────────────────────────────
class DynatraceInternalManager:
    def __init__(self, tenant_url, client_id, client_secret):
        self.tenant_url = tenant_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.headers = None
        self.semaphore = asyncio.Semaphore(10)

    async def authenticate(self):
        """Internal OAuth2 authentication."""
        token_url = "https://sso.dynatrace.com/as/token.oauth2"
        auth_payload = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "storage:read trace.read"
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(token_url, data=auth_payload) as resp:
                if resp.status != 200:
                    err_text = await resp.text()
                    raise ConnectionError(f"OAuth Failed: {err_text}")
                data = await resp.json()
                token = data.get("access_token")
                self.headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                }

    async def get_trace_ids(self, session, app, endpoint):
        """Query Grail via DQL."""
        url = f"{self.tenant_url}/platform/storage/query/v1/query:execute"
        # Search window: Last 2 hours
        start = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        end = datetime.now(timezone.utc).isoformat()
        
        query = f"""
        fetch spans, from: "{start}", to: "{end}"
        | filter matchesValue(service.name, {json.dumps(app)})
        | filter matchesValue(span.name, {json.dumps(endpoint)})
        | fields `trace.id`
        | limit 100
        """
        async with session.post(url, headers=self.headers, json={"query": query}) as resp:
            resp.raise_for_status()
            data = await resp.json()
            
            # Simple Poll if not immediate
            if data.get("state") != "SUCCEEDED":
                token = data.get("requestToken")
                poll_url = f"{self.tenant_url}/platform/storage/query/v1/query:poll/{token}"
                for _ in range(5):
                    await asyncio.sleep(2)
                    async with session.get(poll_url, headers=self.headers) as pr:
                        pd = await pr.json()
                        if pd.get("state") == "SUCCEEDED":
                            return [r["trace.id"] for r in pd["result"]["records"]]
                return []
            return [r["trace.id"] for r in data["result"]["records"]]

    async def fetch_trace_detail(self, session, tid):
        """Fetch individual trace data."""
        async with self.semaphore:
            url = f"{self.tenant_url}/api/v2/traces/{tid}"
            async with session.get(url, headers=self.headers) as resp:
                return await resp.json() if resp.status == 200 else None

    def save_data(self, data, app, endpoint):
        """Server-side directory management."""
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
# Streamlit UI (Clean)
# ────────────────────────────────────────────────
st.set_page_config(page_title="Dynatrace Trace Archiver", layout="centered")
st.title("📂 Trace Archiver")
st.markdown("Enter details to fetch and store traces on the server.")

app_name = st.text_input("Application Name", help="e.g. Frontend-Service")
req_name = st.text_input("Web Request / Endpoint Name", help="e.g. /api/v1/order")

if st.button("Run Extraction", type="primary"):
    if not app_name or not req_name:
        st.warning("Please fill in both fields.")
    else:
        async def main():
            try:
                manager = DynatraceInternalManager(DT_TENANT_URL, DT_CLIENT_ID, DT_CLIENT_SECRET)
                
                with st.spinner("Authenticating with Dynatrace..."):
                    await manager.authenticate()

                async with aiohttp.ClientSession() as session:
                    with st.spinner("Searching for traces in Grail..."):
                        tids = await manager.get_trace_ids(session, app_name, req_name)
                    
                    if not tids:
                        st.error("No traces found for this timeframe.")
                        return

                    with st.spinner(f"Downloading {len(tids)} traces..."):
                        tasks = [manager.fetch_trace_detail(session, tid) for tid in tids]
                        results = await asyncio.gather(*tasks)
                        valid_results = [r for r in results if r]

                    # File saving
                    file_path = manager.save_data({
                        "metadata": {"service": app_name, "endpoint": req_name, "count": len(valid_results)},
                        "traces": valid_results
                    }, app_name, req_name)
                    
                    st.success(f"Archived {len(valid_results)} traces to the server.")
                    st.info(f"Storage path: `{file_path}`")

            except Exception as e:
                st.error(f"Execution Error: {str(e)}")

        asyncio.run(main())
