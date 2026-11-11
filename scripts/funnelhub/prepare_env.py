#!/usr/bin/env python3
"""Create a private test-stack configuration; never overwrite an existing file."""
import os
import secrets
from pathlib import Path

path = Path(".env")
values = {
    "COMPOSE_PROJECT_NAME": "funnelhub-salescompel-test",
    "FUNNELHUB_BIND": "127.0.0.1", "FUNNELHUB_PORT": "3051",
    "POSTGRES_PASSWORD": secrets.token_hex(32),
    "RECORDS_PASSWORD": secrets.token_hex(32),
    "IDENTITY_PASSWORD": secrets.token_hex(32),
    "MARKETING_PASSWORD": secrets.token_hex(32),
    "SECRET_KEY": secrets.token_hex(48),
    "SALESCOMPEL_TOKEN": secrets.token_hex(48),
    "EXTERNAL_PUBLISH_ENABLED": "false", "PUBLIC_MEDIA_ENABLED": "false",
    "SYNC_SCHEDULER": "false", "MAX_UPLOAD_BYTES": "1073741824",
}
fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
with os.fdopen(fd, "w") as f:
    f.write("# Private test configuration. Keep out of Git.\n")
    f.writelines(f"{k}={v}\n" for k, v in values.items())
print("Created .env with private permissions. Existing files are never overwritten.")
