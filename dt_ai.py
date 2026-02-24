import asyncio
import aiohttp
import streamlit as st
import json
import logging
from datetime import datetime, timedelta, timezone
from dateutil import parser

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────
# Async Dynatrace Trace Fetcher Class
# ────────────────────────────────────────────────
class AsyncDynatraceTraceFetcher:
    def __init__(self, tenant_url: str, api_token: str | None = None, bearer_token: str | None = None):
        self.tenant_url = tenant_url.rstrip("/")
        
        if bearer_token:
            self.headers = {
                "Authorization": f"Bearer {bearer_token}",
                "Content-Type": "application/json"
            }
        elif api_token:
            self.headers = {
                "Authorization": f"Api-Token {api_token}",
                "Content-Type": "application/json"
            }
        else:
            raise ValueError("Either api_token or bearer_token must be provided")

        self.semaphore = asyncio.Semaphore(10)

    def validate_timeframe(self, start_time: datetime, end_time: datetime):
        now = datetime.now(timezone.utc)
        limit = now - timedelta(days=7)

        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)

        if start_time > end_time:
            raise ValueError("Start time must be before or equal to end time.")
        if start_time > now:
            raise ValueError("Start time cannot be in the future.")
        if start_time < limit:
            raise ValueError("Start time cannot be older than 7 days (Classic Trace limit).")

    async def execute_dql_query(self, session: aiohttp.ClientSession, query: str):
        # Platform API uses the /platform prefix
        url = f"{self.tenant_url}/platform/storage/query/v1/query:execute"
        
        try:
            async with session.post(url, headers=self.headers, json={"query": query}) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"DQL Initial Request Failed ({resp.status}): {text}")
                
                data = await resp.json()
                if data.get("state") == "SUCCEEDED":
                    return data.get("result", {}).get("records", [])

                request_token = data.get("requestToken")
                if not request_token:
                    return []

            # Poll for result
            poll_url = f"{self.tenant_url}/platform/storage/query/v1/query:poll/{request_token}"
            for attempt in range(30):
                await asyncio.sleep(2)
                async with session.get(poll_url, headers=self.headers) as poll_resp:
                    poll_resp.raise_for_status()
                    poll_data = await poll_resp.json()
                    state = poll_data.get("state")

                    if state == "SUCCEEDED":
                        return poll_data.get("result", {}).get("records", [])
                    if state == "FAILED":
                        msg = poll_data.get("error", {}).get("message", "Unknown error")
                        raise RuntimeError(f"DQL query failed: {msg}")
            
            raise TimeoutError("DQL query timed out after 60 seconds")
        except Exception as e:
            logger.error(f"DQL execution error: {e}")
            raise

    async def fetch_trace_ids(self, session: aiohttp.ClientSession, app: str, method: str,
                             start_iso: str, end_iso: str, limit: int = 100):
        query = f"""
        fetch spans, from: "{start_iso}", to: "{end_iso}"
        | filter matchesValue(service.name, {json.dumps(app)})
        | filter matchesValue(span.name, {json.dumps(method)})
        | fields `trace.id`
        | limit {limit}
        """
        records = await self.execute_dql_query(session, query)
        return list({row["trace.id"] for row in records if "trace.id" in row})

    async def fetch_single_trace(self, session: aiohttp.ClientSession, trace_id: str):
        async with self.semaphore:
            # Note: The traces API is usually under /api/v2/
            url = f"{self.tenant_url}/api/v2/traces/{trace_id}"
            try:
                async with session.get(url, headers=self.headers) as resp:
                    if resp.status == 429:
                        wait = int(resp.headers.get("Retry-After", 5))
                        await asyncio.sleep(wait)
                        return await self.fetch_single_trace(session, trace_id)
                    resp.raise_for_status()
                    return await resp.json()
            except Exception as e:
                logger.error(f"Error fetching trace {trace_id}: {e}")
                return None

    async def fetch_traces(self, app: str, method: str, start_iso: str, end_iso: str, trace_limit: int = 100):
        self.validate_timeframe(parser.isoparse(start_iso), parser.isoparse(end_iso))

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
            trace_ids = await self.fetch_trace_ids(session, app, method, start_iso, end_iso, trace_limit)
            if not trace_ids:
                return None

            tasks = [self.fetch_single_trace(session, tid) for tid in trace_ids]
            results = await asyncio.gather(*tasks)
            valid_traces = [r for r in results if r is not None]

            return {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "tenant": self.tenant_url,
                "service": app,
                "endpoint": method,
                "trace_count": len(valid_traces),
                "traces": valid_traces
            }

# ────────────────────────────────────────────────
# Streamlit Interface
# ────────────────────────────────────────────────
st.set_page_config(page_title="Dynatrace Fixer", layout="wide")
st.title("🔍 Dynatrace Distributed Trace Fetcher")

with st.sidebar:
    st.header("Authentication")
    tenant_url = st.text_input("Tenant URL", placeholder="https://abc12345.live.dynatrace.com")
    use_oauth = st.checkbox("Use OAuth2 (Required for Grail)", value=True)

    if use_oauth:
        client_id = st.text_input("OAuth Client ID")
        client_secret = st.text_input("OAuth Client Secret", type="password")
        account_urn = st.text_input("Account URN (Optional)", placeholder="urn:dtaccount:...")
    else:
        api_token = st.text_input("Classic API Token", type="password")

col1, col2 = st.columns(2)
with col1:
    service_name = st.text_input("Service Name")
with col2:
    span_name = st.text_input("Span/Method Name")

col3, col4, col5 = st.columns(3)
with col3:
    start_str = st.text_input("Start (ISO)", value=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat())
with col4:
    end_str = st.text_input("End (ISO)", value=datetime.now(timezone.utc).isoformat())
with col5:
    limit = st.number_input("Max Traces", 10, 500, 100)

if st.button("Fetch Traces", type="primary"):
    async def run():
        bearer = None
        if use_oauth:
            # FIX: Use global SSO endpoint, not tenant-specific
            token_url = "https://sso.dynatrace.com/as/token.oauth2"
            data = {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "storage:read trace.read"
            }
            # Adding resource helps route to the correct environment
            if account_urn:
                data["resource"] = account_urn
            
            async with aiohttp.ClientSession() as s:
                async with s.post(token_url, data=data) as r:
                    if r.status != 200:
                        err = await r.text()
                        st.error(f"OAuth Failed: {err}")
                        return
                    res = await r.json()
                    bearer = res.get("access_token")

        fetcher = AsyncDynatraceTraceFetcher(tenant_url, api_token if not use_oauth else None, bearer)
        return await fetcher.fetch_traces(service_name, span_name, start_str, end_str, limit)

    try:
        with st.spinner("Processing..."):
            result = asyncio.run(run())
            if result:
                st.success(f"Found {result['trace_count']} traces.")
                st.json(result["traces"][:2]) # Preview
                st.download_button("Download Full JSON", json.dumps(result), "traces.json")
            else:
                st.warning("No traces found.")
    except Exception as e:
        st.error(f"Error: {e}")
