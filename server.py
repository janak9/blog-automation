# FastAPI entry point — run with: python server.py

import logging
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
    run_fastapi(
        agencies={
            # you must export your create agency function here
            "open-swarm": create_agency,
        },
        port=8080,
        enable_logging=True,
        allowed_local_file_dirs=[
            "./uploads",
        ],
    )
