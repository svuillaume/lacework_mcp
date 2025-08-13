# server.py — Lacework LQL MCP (beginner-friendly)
# Python 3.10+

import os, sys
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

# Keep stdout quiet so MCP stdio hosts stay connected
os.environ["FASTMCP_NO_BANNER"] = "1"
os.environ["FASTMCP_LOG_LEVEL"] = "error"

from dotenv import load_dotenv
import httpx
from fastmcp import FastMCP

# --- Load .env before reading variables ---
load_dotenv()

# --- Required config from .env ---
LW_ACCOUNT = (os.getenv("LW_ACCOUNT") or "").strip()           # e.g., partner-demo
LW_KEY_ID  = (os.getenv("LW_KEY_ID")  or "").strip()
LW_SECRET  = (os.getenv("LW_SECRET")  or "").strip()

# --- Optional ---
LW_SUBACCOUNT = (os.getenv("LW_SUBACCOUNT") or "").strip()     # e.g., fortinetcanadademo
LW_EXPIRY = int(os.getenv("LW_EXPIRY") or "3600")

if not (LW_ACCOUNT and LW_KEY_ID and LW_SECRET):
    print("Missing LW_ACCOUNT, LW_KEY_ID, or LW_SECRET in .env", file=sys.stderr)
    sys.exit(1)

BASE_URL = f"https://{LW_ACCOUNT}.lacework.net/api/v2"

# ---------- Helpers ----------
async def get_token() -> str:
    """
    Get a short-lived API token. Works with 200 or 201, and both {data:{token}} or top-level {token}.
    """
    headers = {"X-LW-UAKS": LW_SECRET, "Content-Type": "application/json"}
    if LW_SUBACCOUNT:
        headers["X-LW-Sub-Account"] = LW_SUBACCOUNT

    body = {"keyId": LW_KEY_ID, "expiryTime": LW_EXPIRY}

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{BASE_URL}/access/tokens", headers=headers, json=body)
        if r.status_code not in (200, 201):
            raise RuntimeError(f"Auth failed HTTP {r.status_code}: {r.text}")
        js = r.json()
        token = (js.get("data") or {}).get("token") or js.get("token")
        if not token:
            raise RuntimeError(f"Auth response did not contain token: {js}")
        return token

def auth_headers(token: str) -> Dict[str, str]:
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if LW_SUBACCOUNT:
        h["X-LW-Sub-Account"] = LW_SUBACCOUNT
    return h

def ensure_utc_iso8601(ts: str) -> str:
    """
    Pass-through if already like 'YYYY-MM-DDTHH:MM:SSZ'.
    If user passes a date 'YYYY-MM-DD', convert to 'YYYY-MM-DDT00:00:00Z'.
    """
    if not ts:
        return ts
    if "T" in ts and ts.endswith("Z"):
        return ts
    # very small helper: accept YYYY-MM-DD and add midnight Z
    try:
        _ = datetime.strptime(ts, "%Y-%m-%d")
        return f"{ts}T00:00:00Z"
    except Exception:
        return ts

# ---------- MCP server ----------
mcp = FastMCP("lacework-lql")

@mcp.tool()
async def ping() -> dict:
    """Check authentication with Lacework."""
    try:
        token = await get_token()
        return {"ok": True, "token_preview": token[:10] + "..."}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@mcp.tool()
async def run_lql_query(
    query_id: str,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    args: Optional[List[Dict[str, str]]] = None
) -> dict:
    """
    Execute a saved LQL query by ID:
      POST /api/v2/Queries/{queryId}/execute

    Params:
      - query_id: the saved LQL query ID (e.g., "samv_out_of_canada")
      - start_time/end_time: optional; if provided, added as StartTimeRange/EndTimeRange arguments
        (must be UTC ISO8601 'YYYY-MM-DDTHH:MM:SSZ'; 'YYYY-MM-DD' is accepted and coerced)
      - args: optional extra arguments as a list of {"name": "...", "value": "..."}

    Returns: raw JSON from the API (or {"error": "..."} on failure)
    """
    try:
        if not query_id:
            return {"error": "query_id is required"}

        # Build arguments array
        arguments: List[Dict[str, str]] = []
        if args:
            # shallow-validate shape
            for item in args:
                if isinstance(item, dict) and "name" in item and "value" in item:
                    arguments.append({"name": str(item["name"]), "value": str(item["value"])})

        # If user passed times, add/override StartTimeRange/EndTimeRange
        if start_time:
            start_time = ensure_utc_iso8601(start_time)
            # remove any existing StartTimeRange in provided args
            arguments = [a for a in arguments if a.get("name") != "StartTimeRange"]
            arguments.append({"name": "StartTimeRange", "value": start_time})
        if end_time:
            end_time = ensure_utc_iso8601(end_time)
            arguments = [a for a in arguments if a.get("name") != "EndTimeRange"]
            arguments.append({"name": "EndTimeRange", "value": end_time})

        token = await get_token()
        headers = auth_headers(token)
        payload = {"arguments": arguments}  # per API: options is allowed, but timeFilter is NOT

        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(f"{BASE_URL}/Queries/{query_id}/execute", headers=headers, json=payload)

        if r.status_code >= 400:
            return {"error": f"HTTP {r.status_code}", "details": r.text}

        return r.json()

    except Exception as e:
        return {"error": str(e)}

# ---------- Run ----------
if __name__ == "__main__":
    mcp.run()