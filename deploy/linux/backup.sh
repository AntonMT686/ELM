#!/usr/bin/env bash
# ADA-ELM backup on Linux: elm_* tables of proflow_uat + the file store (data/). Usage: deploy/linux/backup.sh [target-dir]
# Uses MYSQL_PWD from the environment (or prompts). Restore: mysql ... proflow_uat < elm-db-<stamp>.sql ; tar -xzf elm-files-<stamp>.tgz -C <repo>
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd); T=${1:-$ROOT/backups}; mkdir -p "$T"; S=$(date +%Y%m%d-%H%M%S)
URL=$(grep -E '^ELM_DATABASE_URL=' "$ROOT/.env" | cut -d= -f2-)
U=$(echo "$URL" | sed -E 's|.*://([^:]+):.*|\1|'); H=$(echo "$URL" | sed -E 's|.*@([^:/]+).*|\1|'); P=$(echo "$URL" | sed -nE 's|.*@[^:/]+:([0-9]+)/.*|\1|p'); D=$(echo "$URL" | sed -E 's|.*/([^/?]+)(\?.*)?$|\1|')
[ -n "${MYSQL_PWD:-}" ] || { read -rsp "MySQL password for $U: " MYSQL_PWD; echo; export MYSQL_PWD; }
TABLES=$(mysql -h "$H" -P "${P:-3306}" -u "$U" -N -e "SELECT table_name FROM information_schema.tables WHERE table_schema='$D' AND table_name LIKE 'elm\\_%'")
mysqldump -h "$H" -P "${P:-3306}" -u "$U" --single-transaction --default-character-set=utf8mb4 "$D" $TABLES > "$T/elm-db-$S.sql"
[ -d "$ROOT/data" ] && tar -C "$ROOT" -czf "$T/elm-files-$S.tgz" data
(cd "$T" && sha256sum elm-db-$S.sql $( [ -f elm-files-$S.tgz ] && echo elm-files-$S.tgz ) > elm-$S.sha256)
echo "Backup written to $T ($S)"
