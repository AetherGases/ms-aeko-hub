"""Memory-generator worker configuration.

Load configuration from the repository environment file without overriding process settings.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

from aeko_metrics.constants import MEMORY_WORKER_ID_REQUEST

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

SESSION_INACTIVITY_MINUTES = int(os.environ["SESSION_INACTIVITY_MINUTES"])

CONVERSATION_MEMORY_FIELD = os.environ["CONVERSATION_MEMORY_FIELD"]

REDIS_SCAN_COUNT = int(os.environ["REDIS_SCAN_COUNT"])
