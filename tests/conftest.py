"""Configure isolated API tests with an in-memory SDK and MongoDB doubles.

The SDK replacement and test environment are installed before application
imports. MCP warm-up is disabled to prevent external server startup.
"""

import importlib
import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

load_dotenv(REPO_ROOT / "tests/settings.env", override=True)

from internal.shared import event_tracking
from tests import fake_aeko

sys.modules.setdefault("aeko", fake_aeko)

os.environ["MONGO_URI"] = "mongodb://fake-host:27017"
os.environ["DB_NAME"] = "aeko_test"
os.environ["REDIS_URI"] = "redis://fake-host:6379/0"
os.environ["GEMINI_API_KEY"] = "test-gemini-key"
os.environ["AEKO_FAST_MODEL"] = "fast-model"
os.environ["AEKO_SLOW_MODEL"] = "slow-model"
os.environ["AEKO_MAX_TOKENS"] = "512"
os.environ["AEKO_REPORT_MAX_TOKENS"] = "4096"
os.environ["AEKO_TEMPERATURE"] = "0.2"
os.environ["AEKO_TOP_P"] = "0.9"
os.environ["AEKO_TOP_K"] = "40"


os.environ["AEKO_MCP_WARM_UP"] = "false"


os.environ.pop("AEKO_MODEL_LIST", None)
os.environ.pop("AEKO_API_KEY_LIST", None)


class FakeCollection:
    def __init__(self, documents=None):
        self.documents = list(documents or [])

    def find(self, query=None, projection=None):
        """Return scripted documents for the recorded collection query."""
        return list(self.documents)

    def find_one(self, query=None, projection=None):
        """Return the scripted document for a collection lookup."""
        return self.documents[0] if self.documents else None

    def insert_one(self, document):
        """Record a document insertion and return a simulated insert result."""
        self.documents.append(document)
        return type("InsertOneResult", (), {"inserted_id": "fake-inserted-id"})()

    def update_one(self, query, update):
        """Record a document update and return a simulated update result."""
        return None

    def replace_one(self, query, replacement, upsert=False):
        """Replace the first stored document and return a simulated replace result."""
        self.documents = [replacement]
        return type("UpdateResult", (), {"matched_count": 1, "upserted_id": None})()


class FakeDatabase:
    def __init__(self):
        self.collections = {}
        self.commands = []

    def __getitem__(self, name):
        return self.collections.setdefault(name, FakeCollection())

    def __getattr__(self, name):
        if name in {"collections", "commands"}:
            raise AttributeError(name)
        return self[name]

    def command(self, name):
        """Record a database command and return a simulated success response."""
        self.commands.append(name)
        return {"ok": 1}


class FakeMongoClient:
    """Drop-in replacement for `pymongo.MongoClient` in the app lifespan."""

    instances = []

    def __init__(self, uri=None, *args, **kwargs):
        self.uri = uri
        self.database = FakeDatabase()
        self.closed = False
        FakeMongoClient.instances.append(self)

    def __getitem__(self, name):
        return self.database

    def close(self):
        """Record closure of the simulated resource."""
        self.closed = True


class FakeRedis:
    """Drop-in replacement for `redis.Redis` in the app lifespan."""

    instances = []

    def __init__(self, url=None):
        self.url = url
        self.values = {}
        self.expirations = {}
        self.closed = False
        FakeRedis.instances.append(self)

    @classmethod
    def from_url(cls, url):
        """Create a simulated Redis client from a connection URI."""
        return cls(url)

    def ping(self):
        """Report that the simulated Redis instance is reachable."""
        return True

    def get(self, key):
        """Return the stored value for a key."""
        return self.values.get(key)

    def set(self, key, value, ex=None):
        """Store a value and optionally mark it for expiry simulation."""
        self.values[key] = value
        if ex is None:
            self.expirations.pop(key, None)
        else:
            self.expirations[key] = ex

    def exists(self, key):
        """Return whether a key is present."""
        return 1 if key in self.values else 0

    def delete(self, key):
        """Remove a key from the simulated store."""
        self.values.pop(key, None)
        self.expirations.pop(key, None)

    def scan_iter(self, match=None, count=None):
        """Yield keys that match the supplied pattern."""
        prefix, suffix = match.split("*", 1)
        for key in list(self.values):
            if key.startswith(prefix) and key.endswith(suffix):
                yield key

    def close(self):
        """Record closure of the simulated resource."""
        self.closed = True


@pytest.fixture(autouse=True)
def no_event_sink():
    """Clear metric sinks around each test."""
    event_tracking.set_event_sink(None)
    yield
    event_tracking.set_event_sink(None)


@pytest.fixture(autouse=True)
def reset_aeko_runtime():
    """Reset SDK runtime state around each test."""
    fake_aeko.Aeko.reset()
    yield
    fake_aeko.Aeko.reset()


@pytest.fixture
def fake_sdk():
    """Provide the reset SDK double to the test."""
    return fake_aeko


@pytest.fixture
def configured_sdk(reset_aeko_runtime):
    """Configure the SDK double for the test."""
    fake_aeko.Aeko.config("test-gemini-key")
    return fake_aeko


@pytest.fixture
def api_main(monkeypatch):
    """Import the API entry point with isolated database and SDK dependencies."""
    FakeMongoClient.instances = []
    FakeRedis.instances = []
    module = importlib.import_module("cmd.api.main")
    module = importlib.reload(module)
    monkeypatch.setattr(module, "MongoClient", FakeMongoClient)
    monkeypatch.setattr(module, "Redis", FakeRedis)
    return module
