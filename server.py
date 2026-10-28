# FastAPI entry point — run with: python server.py

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from run_utils import _load_openswarm_dotenv

# Load the OpenSwarm state-root .env (official launcher path) AND the project-local
# .env. When running `python server.py` directly the state-root file usually does not
# exist, so the project .env is what supplies API keys and APP_TOKEN.
_load_openswarm_dotenv()
load_dotenv(Path(__file__).with_name(".env"))

# Configure logging
logging.basicConfig(level=logging.INFO)

from swarm import create_agency
from agency_swarm.integrations.fastapi import run_fastapi


if __name__ == "__main__":
    if not os.getenv("APP_TOKEN"):
        raise SystemExit(
            "Refusing to start: APP_TOKEN is not set, so the API would accept unauthenticated "
            "requests. Add it to .env."
        )
    # This API is what mcp_bridge.py exposes through a public tunnel, so agents built for it
    # never get code-execution tools (see config.allow_code_execution).
    os.environ["SWARM_DISABLE_CODE_EXEC"] = "1"
    run_fastapi(
        agencies={
            # you must export your create agency function here
            "open-swarm": create_agency,
        },
        host="127.0.0.1",  # loopback only; remote access goes through mcp_bridge.py
        port=8080,
        enable_logging=True,
        allowed_local_file_dirs=[
            "./uploads",
        ],
    )
