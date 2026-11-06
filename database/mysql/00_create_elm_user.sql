-- Optional: a dedicated MySQL / MariaDB account for ADA-ELM instead of root.
-- Run as an administrator (XAMPP: C:\xampp7410\mysql\bin\mysql.exe -u root -P 3309), after replacing the password.
-- ELM needs to create/alter its own elm_* tables during upgrades, so it gets DDL rights on proflow_uat.
-- It never touches the legacy PMS tables; for extra safety you can later replace the grant below with grants on elm\_% only.
CREATE USER IF NOT EXISTS 'elm'@'localhost' IDENTIFIED BY 'change-me-db-password';
CREATE USER IF NOT EXISTS 'elm'@'127.0.0.1' IDENTIFIED BY 'change-me-db-password';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX, REFERENCES ON proflow_uat.* TO 'elm'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX, REFERENCES ON proflow_uat.* TO 'elm'@'127.0.0.1';
FLUSH PRIVILEGES;
