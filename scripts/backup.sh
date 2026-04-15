#!/bin/bash
# Avito Autoload — daily backup script
# Usage: PGPASSWORD=yourpassword bash scripts/backup.sh
# Cron: PGPASSWORD=yourpassword 0 3 * * * /home/claude2/avito-autoload/scripts/backup.sh >> /var/log/avito-backup.log 2>&1
# Or create ~/.pgpass: localhost:5433:avito_autoload:avito_user:yourpassword

set -euo pipefail

DATE=$(date +%Y-%m-%d_%H-%M)

if [ -z "${PGPASSWORD:-}" ]; then
    echo "[$DATE] WARNING: PGPASSWORD not set — relying on ~/.pgpass"
fi

BACKUP_DIR="/home/claude2/backups/avito-autoload"
KEEP_DAYS=14

mkdir -p "$BACKUP_DIR"

# Dump main DB
pg_dump -h localhost -p 5433 -U avito_user avito_autoload \
  | gzip > "$BACKUP_DIR/db_$DATE.sql.gz"

# Dump CRM DB (different credentials: postgres:postgres)
PGPASSWORD=postgres pg_dump -h localhost -p 5432 -U postgres avito_crm \
  | gzip > "$BACKUP_DIR/crm_$DATE.sql.gz"

# Copy latest XML feeds (keep originals safe)
FEEDS_DIR="/home/claude2/avito-autoload/feeds"
if [ -d "$FEEDS_DIR" ]; then
  tar -czf "$BACKUP_DIR/feeds_$DATE.tar.gz" -C "$FEEDS_DIR" .
fi

# Remove backups older than KEEP_DAYS
find "$BACKUP_DIR" -name "*.gz" -mtime +$KEEP_DAYS -delete

echo "[$DATE] Backup complete. Files in $BACKUP_DIR:"
ls -lh "$BACKUP_DIR" | tail -5
