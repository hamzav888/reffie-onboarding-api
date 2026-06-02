import os

# Set required env vars before any reffie module is imported.
# reffie.auth imports reffie.config, which instantiates Settings() at module level.
# Without these, the test collection phase fails before any test runs.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("HUBSPOT_TOKEN", "test-token")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id.apps.googleusercontent.com")
os.environ.setdefault("HUBSPOT_WEBHOOK_SECRET", "test-webhook-secret")
os.environ.setdefault("HUBSPOT_CLOSED_WON_STAGE_IDS", "closedwon")
