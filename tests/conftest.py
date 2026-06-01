import os

# Set required env vars before any reffie module is imported.
# reffie.auth imports reffie.config, which instantiates Settings() at module level.
# Without these, the test collection phase fails before any test runs.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("HUBSPOT_TOKEN", "test-token")
os.environ.setdefault("JWT_SECRET", "test-secret-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id.apps.googleusercontent.com")
