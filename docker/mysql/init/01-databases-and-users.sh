#!/bin/sh
# Creates the application and test databases plus two least-privilege users (B16):
#   manuflow_app      - DML only; the API connects with this user.
#   manuflow_migrator - DDL on the same schemas; only Alembic uses it.
# Runs automatically on the first start of the MySQL container, and is reused by CI
# against the MySQL service container (set MYSQL_HOST=127.0.0.1 there).
: "${MYSQL_ROOT_PASSWORD:?}" "${MYSQL_APP_PASSWORD:?}" "${MYSQL_MIGRATOR_PASSWORD:?}"

MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --host="${MYSQL_HOST:-localhost}" --user=root <<SQL
CREATE DATABASE IF NOT EXISTS manuflow CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE DATABASE IF NOT EXISTS manuflow_test CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE USER IF NOT EXISTS 'manuflow_app'@'%' IDENTIFIED BY '${MYSQL_APP_PASSWORD}';
CREATE USER IF NOT EXISTS 'manuflow_migrator'@'%' IDENTIFIED BY '${MYSQL_MIGRATOR_PASSWORD}';

GRANT SELECT, INSERT, UPDATE, DELETE ON manuflow.* TO 'manuflow_app'@'%';
GRANT SELECT, INSERT, UPDATE, DELETE ON manuflow_test.* TO 'manuflow_app'@'%';
GRANT ALL PRIVILEGES ON manuflow.* TO 'manuflow_migrator'@'%';
GRANT ALL PRIVILEGES ON manuflow_test.* TO 'manuflow_migrator'@'%';
SQL
