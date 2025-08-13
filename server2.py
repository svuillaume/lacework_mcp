# server.py — Lacework MCP: Alerts + AWS Compliance (loads .env, quiet stdout)
# Python 3.10+

import os, sys
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

# Silence FastMCP banner/logs on stdout for MCP stdio hosts
os.environ["FASTMCP_NO_BANNER"] = "1"
os.environ["FASTMCP_LOG_LEVEL"] = "error"

# --- load .env BEFORE reading env vars ---
from dotenv import load_dotenv
load_dotenv()

import httpx
from fastmcp import FastMCP

# ----------------- Config -----------------
LW_ACCOUNT     = (os.getenv("LW_ACCOUNT") or "").strip()         # e.g., partner-demo
LW_KEY_ID      = (os.getenv("LW_KEY_ID") or "").strip()
LW_SECRET      = (os.getenv("LW_SECRET") or "").strip()
LW_EXPIRY      = int(os.getenv("LW_EXPIRY") or "3600")
LW_SUBACCOUNT  = (os.getenv("LW_SUBACCOUNT") or "").strip()      # optional

# Optional TLS/proxy knobs (use if you’re behind corporate proxy)
LW_CA_BUNDLE   = (os.getenv("LW_CA_BUNDLE") or "").strip()       # path to PEM file
LW_TRUST_ENV   = os.getenv("LW_TRUST_ENV", "1").strip()          # "1" honors system proxies; "0" ignores

VERIFY_OPT     = LW_CA_BUNDLE if LW_CA_BUNDLE else True
TRUST_ENV_OPT  = (LW_TRUST_ENV != "0")

if not (LW_ACCOUNT and LW_KEY_ID and LW_SECRET):
    print("Missing required environment variables LW_ACCOUNT, LW_KEY_ID, LW_SECRET", file=sys.stderr)
    sys.exit(1)

BASE_URL = f"https://{LW_ACCOUNT}.lacework.net/api/v2"

def _client(timeout_s: float = 30.0) -> httpx.AsyncClient:
    transport = httpx.AsyncHTTPTransport(retries=2)
    return httpx.AsyncClient(
        timeout=timeout_s,
        verify=VERIFY_OPT,
        transport=transport,
        trust_env=TRUST_ENV_OPT,
        headers={"Content-Type": "application/json"},
    )

# ----------------- Auth -----------------
async def get_token() -> str:
    url = f"{BASE_URL}/access/tokens"
    headers = {"X-LW-UAKS": LW_SECRET, "Content-Type": "application/json"}
    if LW_SUBACCOUNT:
        headers["X-LW-Sub-Account"] = LW_SUBACCOUNT
    payload = {"keyId": LW_KEY_ID, "expiryTime": LW_EXPIRY}

    async with _client(30.0) as client:
        r = await client.post(url, headers=headers, json=payload)
        if r.status_code >= 400:
            print(f"TOKEN {r.status_code}: {r.text}", file=sys.stderr)
        r.raise_for_status()
        data = r.json()
        return (data.get("data") or {}).get("token") or data.get("token")

def _auth_headers(token: str) -> Dict[str, str]:
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if LW_SUBACCOUNT:
        h["X-LW-Sub-Account"] = LW_SUBACCOUNT
    return h

async def _post_json(url: str, headers: Dict[str, str], body: Dict[str, Any], timeout_s: float = 60.0) -> Dict[str, Any]:
    async with _client(timeout_s) as client:
        r = await client.post(url, headers=headers, json=body)
        if r.status_code >= 400:
            print(f"POST failed: {url} {r.status_code} {r.text}", file=sys.stderr)
        r.raise_for_status()
        return r.json()

# ----------------- MCP Server (init BEFORE decorators) -----------------
mcp = FastMCP("lacework")

# ----------------- Tools -----------------
@mcp.tool()
async def ping() -> dict:
    """Simple auth check (fetches a token)."""
    try:
        tok = await get_token()
        return {"ok": True, "token_preview": (tok[:10] + "...") if tok else None}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@mcp.tool()
async def list_alerts(
    start_time: Optional[str] = None,
    end_time:   Optional[str] = None,
    limit: int = 50
) -> dict:
    """
    GET /api/v2/Alerts with optional time window.
    times must be ISO8601 UTC: YYYY-MM-DDTHH:MM:SSZ
    Defaults to the last 7 days if not provided.
    """
    try:
        now = datetime.now(timezone.utc)
        if not end_time:
            end_time = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        if not start_time:
            start_time = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")

        token = await get_token()
        headers = _auth_headers(token)
        params = {"startTime": start_time, "endTime": end_time, "limit": limit}

        async with _client(30.0) as client:
            r = await client.get(f"{BASE_URL}/Alerts", headers=headers, params=params)
            if r.status_code >= 400:
                return {"error": f"HTTP {r.status_code}", "details": r.text}
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}", "details": e.response.text}
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
async def search_aws_compliance(
    start_time: Optional[str] = None,
    end_time:   Optional[str] = None,
    statuses: Optional[List[str]] = None,        # e.g. ["NonCompliant","PartiallyCompliant"]
    account_ids: Optional[List[str]] = None,     # e.g. ["123456789012"]
    returns: Optional[List[str]] = None,         # e.g. ["account","id","recommendation","severity","status"]
    limit: int = 1000
) -> dict:
    """
    POST /api/v2/Configs/ComplianceEvaluations/search
    Required shape per docs:
      {
        "timeFilter": {...},
        "dataset": "AwsCompliance",
        "filters": [ {"field": "...", "expression": "eq|in|...", "value|values": ...}, ... ],
        "returns": [ ... ],
        "paging": {"limit": N}
      }
    Note: Max recommended time slice is 7 days; longer ranges are chunked automatically.
    """
    try:
        # Parse/default time window
        now = datetime.now(timezone.utc)
        end_dt = datetime.strptime(end_time, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) if end_time else now
        start_dt = datetime.strptime(start_time, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) if start_time else (end_dt - timedelta(days=7))

        # Build filters array per spec
        filters: List[Dict[str, Any]] = []
        if statuses:
            if len(statuses) == 1:
                filters.append({"field": "status", "expression": "eq", "value": statuses[0]})
            else:
                filters.append({"field": "status", "expression": "in", "values": statuses})
        if account_ids:
            if len(account_ids) == 1:
                filters.append({"field": "account.AccountId", "expression": "eq", "value": account_ids[0]})
            else:
                filters.append({"field": "account.AccountId", "expression": "in", "values": account_ids})

        if returns is None:
            returns = ["account", "id", "recommendation", "severity", "status"]

        token = await get_token()
        headers = _auth_headers(token)
        url = f"{BASE_URL}/Configs/ComplianceEvaluations/search"

        # helper: fetch one ≤7-day chunk
        async def fetch_chunk(s_dt, e_dt, page_limit):
            body = {
                "timeFilter": {
                    "startTime": s_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "endTime":   e_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                },
                "dataset": "AwsCompliance",
                "filters": filters,      # ARRAY of {field, expression, value(s)}
                "returns": returns,
                "paging":  {"limit": min(page_limit, 5000)}
            }
            first = await _post_json(url, headers, body, timeout_s=60.0)
            data = list(first.get("data") or [])
            paging = first.get("paging") or {}
            cursor = paging.get("nextPage") or paging.get("nextToken") or paging.get("cursor")
            while cursor and len(data) < page_limit:
                body["paging"] = {"cursor": cursor, "limit": min(page_limit - len(data), 5000)}
                nxt = await _post_json(url, headers, body, timeout_s=60.0)
                nd = nxt.get("data") or []
                data.extend(nd)
                paging = nxt.get("paging") or {}
                cursor = paging.get("nextPage") or paging.get("nextToken") or paging.get("cursor")
            return data

        # chunk longer ranges into ≤7-day slices
        all_rows: List[Dict[str, Any]] = []
        chunk_start = start_dt
        while chunk_start < end_dt and len(all_rows) < limit:
            chunk_end = min(chunk_start + timedelta(days=7), end_dt)
            rows = await fetch_chunk(chunk_start, chunk_end, min(limit - len(all_rows), 5000))
            all_rows.extend(rows)
            chunk_start = chunk_end

        return {"data": all_rows[:limit]}

    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}", "details": e.response.text}
    except Exception as e:
        return {"error": str(e)}

# ----------------- Run -----------------
if __name__ == "__main__":
    mcp.run()
