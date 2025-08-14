## MCP Server
The server runs as an MCP (Model Context Protocol) tool that provides Lacework integration capabilities, in Claude AI Desktop

## Project Setup

### Pre requisite
Check for current venv

echo $VIRTUAL_ENV

### 1. Create and Setup Virtual Environment
```bash
# Create new virtual environment
python3.11 -m venv mcpvenv

# Activate the environment
source mcpvenv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Environment Configuration
Create a `.env` file with required Lacework credentials:
```
LW_ACCOUNT=your-account-name
LW_KEY_ID=your-key-id
LW_SECRET=your-secret-key
LW_SUBACCOUNT=optional-subaccount
LW_EXPIRY=3600
```

### 3. Run the Application
```bash
# Run your script
python your_script.py

# Or run MCP server directly
python server.py

# Or with full path
/Users/svuillaume/betamcp/.venv/bin/python3 server.py
```

### 4. Deactivate Environment
```bash
deactivate
```

## Project Structure
```
lacework_mcp/
├── .env                    # Environment variables (not in git)
├── .gitignore             # Git ignore file
├── requirements.txt       # Python dependencies
├── server.py             # Main MCP server
├── samvenv/              # Virtual environment (not in git)
│   ├── bin/
│   │   └── activate
│   └── lib/
└── README.md             # This file
```

## Development Workflow
1. Activate virtual environment
2. Make changes to code
3. Test mcp server
4. Deactivate when done: `deactivate`

## Generate Prompt using Claude AI

run LQL samv_out_of_canada and fetch all aws resources id
