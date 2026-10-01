"""Generate local credentials once. Existing credentials are never overwritten."""
import os
import secrets
from pathlib import Path

path = Path(__file__).resolve().parent.parent / '.env'
if path.exists():
    print('.env already exists; keeping existing credentials.')
else:
    values = {
        'POSTGRES_PASSWORD': secrets.token_hex(24),
        'CLICKHOUSE_PASSWORD': secrets.token_hex(24),
        'REDIS_AUTH': secrets.token_hex(24),
        'MINIO_ROOT_PASSWORD': secrets.token_hex(24),
        'SALT': secrets.token_hex(32),
        'ENCRYPTION_KEY': secrets.token_hex(32),
        'NEXTAUTH_SECRET': secrets.token_hex(32),
        'LANGFUSE_INIT_PROJECT_PUBLIC_KEY': 'pk-lf-' + secrets.token_hex(16),
        'LANGFUSE_INIT_PROJECT_SECRET_KEY': 'sk-lf-' + secrets.token_hex(32),
        'LANGFUSE_INIT_USER_PASSWORD': secrets.token_urlsafe(18),
    }
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as file:
        file.write('# Generated local demo credentials. Keep this file private.\n')
        for key, value in values.items():
            file.write(f'{key}={value}\n')
    print('Created .env. Login email: demo@micro.local. Password: LANGFUSE_INIT_USER_PASSWORD in .env.')
