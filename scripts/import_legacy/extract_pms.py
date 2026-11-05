#!/usr/bin/env python
"""Step 1 of the PMS → ADA-ELM migration: read PMS (Yii2 / MySQL) and write a portable JSON bundle.

Read-only by construction: the session is set to READ ONLY, and only SELECT / SHOW statements are issued. Password
hashes, auth keys, reset tokens, dates of birth, addresses, phone and ID numbers are never selected.

Run on any machine that can reach the PMS database. It needs only `pip install -r requirements.txt` (PyMySQL), not ELM.

    python extract_pms.py --port 3309 --database proflow_uat --yii-config D:/Projects/products/PMS/config/db.php --out pms_bundle.json

The password comes from the PMS_DB_PASSWORD environment variable, or from the Yii config file with --yii-config.
It is never accepted on the command line, where it would show up in process lists and shell history.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pymysql

BUNDLE_FORMAT = 1

# Table → (columns, optional WHERE). Tables absent from the source are recorded as missing rather than failing the run,
# because older PMS databases and backups do not have all of them.
TABLES: dict[str, tuple[str, str | None]] = {
    "department": ("id, name, enabled", None),
    "user": ("id, first_name, last_name, username, email, designation, department_id, user_level, status, employment_status, lastLogin, dateCreated", None),
    "auth_item": ("id, name, description", None),
    "project": ("id, name, description, status_id, short_code, start_date, end_date, enabled, dateCreated", None),
    "project_user_role": ("id, project_id, user_id, role_id, status", None),
    "user_project_mapping": ("id, user_id, project_id, record_status", None),
    "projectteam": ("id, project_id, user_id", None),
    "system": ("id, name, short_code", None),
    "subsystem": ("id, name, short_code", None),
    "project_mapping": ("id, project_id, system_id, subsys_id, record_status", None),
    "project_milestone": ("id, project_id, milestone_name, description, start_date, end_date, status, created_by", None),
    "milestone": ("id, project, subsys_id, milestone, code, description, status, start_date, end_date, completed_date, record_status, created_by", None),
    "project_plans": ("id, project_id, name, description, version, status, created_by, created_at, updated_at", None),
    "plan_activities": ("id, plan_id, project_id, phase_id, title, description, assigned_to, start_date, end_date, estimated_hours, actual_hours, priority, status, progress, sort_order, created_by, created_at", None),
    "masterdata_main": ("id, name, code, record_status", "code = 'PLANPHASE'"),
    "act_masterdata": ("id, name, code", "code = 'PRIORITY'"),
    "act_task_main": ("id, name, description, task_id, state, task_type_id, record_status, act_system, sub_system, req_id, created_by, created_on, modified_on, holding_reason, shortclose_reason, paret_task_id, plan_activity_id, mile_stone", None),
    "act_schedule": ("id, task_id, assigned_to, plan_start_date, plan_end_date, exp_dev_complete, priority, estimation_hr, record_status", None),
    "task_dependency": ("id, task_id, predecessor_id, type, lag_days, created_by", None),
    "task_completion_rule": ("id, task_type_id, rule_key, required, enabled, description", None),
    "states": ("state_id, name, record_type_id, state_status, state_display_value", None),
    "record_types": ("record_type_id, record_type, description", None),
    "workflow": ("workflow_id, object_id, record_type_id, current_state, from_user, to_user, created_date", None),
    "act_dailystatus": ("id, activity_id, remarks, review_remarks, record_status, created_by, created_on, availed_work_hr", None),
    "requirements": ("id, name, description, project, requirement_tag, states, priority, type_of_development, reason, tag, document, csci_version, req_version, delete_ver, dateCreated, dateUpdated", None),
    "baselined_requirements": ("id, baseline_name, name, description, project, requirement_tag, priority, csci_version, tag, req_baseline_version, dateCreated", None),
    "requirement_review": ("id, requirement_id, user_id, approver, status, created_at", None),
    "log_requirements": ("id, requirement_id, states, action, trigger_date", None),
    "audit_log": ("id, user_id, username, project_id, module, entity_type, entity_id, action, old_value, new_value, remarks, created_at", None),
    "log_activity": ("id, activity, activity_id, description, user_id, created_at", None),
}


def to_json(v):
    if isinstance(v, datetime):
        return v.isoformat(sep=" ")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, timedelta):
        return str(v)
    if isinstance(v, bytes):
        return None
    raise TypeError(f"Cannot serialise {type(v)}")


def password_from_args(args) -> str:
    env = os.environ.get("PMS_DB_PASSWORD")
    if env is not None:
        return env
    if args.yii_config:
        text = open(args.yii_config, encoding="utf-8").read()
        # The first uncommented 'password' entry; commented-out alternatives must not be picked up.
        text = re.sub(r"^\s*//.*$", "", text, flags=re.M)
        m = re.search(r"'password'\s*=>\s*'([^']*)'", text)
        if not m:
            sys.exit(f"No 'password' entry found in {args.yii_config}.")
        return m.group(1)
    return getpass.getpass("PMS database password: ")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=3309)
    ap.add_argument("--user", default="root")
    ap.add_argument("--database", default="proflow_uat")
    ap.add_argument("--yii-config", help="PMS config/db.php to read the password from")
    ap.add_argument("--out", default="pms_bundle.json")
    args = ap.parse_args()

    conn = pymysql.connect(host=args.host, port=args.port, user=args.user, password=password_from_args(args), database=args.database, charset="utf8mb4", read_timeout=300, cursorclass=pymysql.cursors.DictCursor)
    cur = conn.cursor()
    cur.execute("SET SESSION TRANSACTION READ ONLY")
    cur.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")  # all tables as of one moment

    cur.execute("SELECT table_name AS t FROM information_schema.tables WHERE table_schema = %s AND table_type = 'BASE TABLE' ORDER BY table_name", (args.database,))
    all_tables = [r["t"] for r in cur.fetchall()]
    inventory: dict[str, int] = {}
    for t in all_tables:
        cur.execute(f"SELECT COUNT(*) AS n FROM `{t}`")
        inventory[t] = cur.fetchone()["n"]

    data: dict[str, list[dict]] = {}
    missing: list[str] = []
    for table, (columns, where) in TABLES.items():
        if table not in inventory:
            missing.append(table)
            data[table] = []
            continue
        quoted = ", ".join(f"`{c.strip()}`" for c in columns.split(","))
        cur.execute(f"SELECT {quoted} FROM `{table}`" + (f" WHERE {where}" if where else ""))
        data[table] = cur.fetchall()
    cur.execute("SELECT VERSION() AS v")
    server = cur.fetchone()["v"]
    conn.rollback()
    conn.close()

    bundle = {
        "format": BUNDLE_FORMAT,
        "source": {"system": "PMS", "database": args.database, "host": args.host, "server_version": server, "extracted_at": datetime.now(timezone.utc).isoformat()},
        "inventory": inventory,
        "missing_tables": missing,
        "data": data,
    }
    text = json.dumps(bundle, default=to_json, ensure_ascii=False, sort_keys=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    with open(args.out + ".sha256", "w", encoding="ascii", newline="\n") as f:
        f.write(f"{digest}  {os.path.basename(args.out)}\n")

    print(f"Source: {args.database} on {args.host}:{args.port} (MariaDB/MySQL {server}), {len(all_tables)} tables")
    for table in TABLES:
        print(f"  {table:<24} {len(data[table]):>7} row(s)" + ("  (table not present)" if table in missing else ""))
    print(f"Wrote {args.out}\nSHA-256 {digest}")
    print("This file holds names and e-mail addresses. Handle it as ADA data, and delete it after sign-off.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
