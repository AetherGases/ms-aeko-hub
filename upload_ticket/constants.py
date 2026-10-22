"""Upload ticket configuration."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

INVENTORY_UPLOAD_TICKET_TTL_SECONDS = int(
    os.environ["INVENTORY_UPLOAD_TICKET_TTL_SECONDS"]
)

STATE_WAITING_FOR_UPLOAD = "waiting_for_upload"
STATE_UPLOADED = "uploaded"
STATE_CONSUMED = "consumed"

VALID_FILE_TYPES = frozenset({"IMAGE", "XLSX"})

_CLOUDINARY_ALLOWED_HOSTS = frozenset({"res.cloudinary.com"})
