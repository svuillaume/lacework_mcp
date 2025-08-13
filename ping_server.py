import os
os.environ["FASTMCP_NO_BANNER"]="1"
os.environ["FASTMCP_LOG_LEVEL"]="error"

from fastmcp import FastMCP
srv = FastMCP("ping")

@srv.tool()
def ping():
    return {"ok": True}

if __name__ == "__main__":
    srv.run()
