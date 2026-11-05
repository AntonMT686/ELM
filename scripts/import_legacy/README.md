# PMS → ADA-ELM data migration

Two steps, so the extract can run next to the PMS database and the load can run inside the isolated ELM network.

| Step | Script | Needs | Touches |
|---|---|---|---|
| 1. Extract | `scripts/import_legacy/extract_pms.py` | Python + PyMySQL, network to PMS | PMS: read-only session, SELECT/SHOW only |
| 2. Load | `python -m app.legacy_import.load` (in `backend/`) | The ELM backend | ELM only. Dry run unless you pass `--commit` |

PMS is never changed. Never point the loader at production without a dry run and a database backup.

## Which database

PMS uses `proflow_uat` on port 3309 (`C:\xampp7410\mysql`). Start it from XAMPP first. `adadb_dev` on port 3306 has the same tables but no rows, so do not use it. A later production dump can be restored somewhere and extracted the same way.

## 1. Extract

```bash
cd scripts/import_legacy
pip install -r requirements.txt
python extract_pms.py --port 3309 --database proflow_uat --yii-config D:/Projects/products/PMS/config/db.php --out pms_bundle.json
```

This writes `pms_bundle.json` and `pms_bundle.json.sha256`. The password comes from `--yii-config` or the `PMS_DB_PASSWORD` environment variable. Password hashes, tokens, dates of birth, addresses, phone and ID numbers are not extracted. The bundle still holds names and e-mail addresses: handle it as ADA data and delete it after sign-off.

## 2. Load

Local (backend on this PC):

```bash
cd backend
python -m app.legacy_import.load ../scripts/import_legacy/pms_bundle.json
```

Docker (rebuild first, so the image has this code and migration `0002_planning`):

```bash
docker compose up -d --build backend worker web
docker compose cp scripts/import_legacy/pms_bundle.json backend:/tmp/pms_bundle.json
docker compose cp scripts/import_legacy/pms_bundle.json.sha256 backend:/tmp/pms_bundle.json.sha256
docker compose exec backend python -m app.legacy_import.load /tmp/pms_bundle.json --report-dir /tmp/import_reports
```

Read the report, then repeat the same command with `--commit`. Copy the report out with `docker compose cp backend:/tmp/import_reports ./import_reports`, and delete the bundle from the container afterwards.

| Option | Effect |
|---|---|
| (none) | Full load and report, then rollback. Nothing is kept |
| `--commit` | Keeps the data, but only if the report passes |
| `--commit --accept-errors` | Keeps the data even though some rows were rejected. Reconciliation must still match |
| `--rollback <run-id>` | Removes exactly what that run created. Refused if imported records have been used since; `--force` overrides |

Running it again is safe: rows already imported are skipped, and ELM edits are never overwritten. For cutover, extract again and load, and only new rows are added.

## What is migrated

| PMS | ELM | Notes |
|---|---|---|
| `department` | `org_units` | Under the ELM root, coded `PMS-DEPT-n`. Move them under the right directorate |
| `user` | `users` | No password is carried over. Accounts cannot sign in until an administrator sets a password or LDAP is enabled. A matching ELM username is linked, not changed |
| `project` | `projects` + levels System, Subsystem | Directorates are not in PMS, so each project is listed for review |
| `project_mapping`, `system`, `subsystem` | `engineering_items` | One row per project/system/subsystem; PMS repeats these per version |
| `project_user_role`, `user_project_mapping`, `projectteam` | `project_members`, `role_assignments` (PROJECT scope) | See role mapping |
| `masterdata_main` (PLANPHASE) | `plan_phases` | Matched to the shared phases |
| `project_plans`, `plan_activities` | `project_plans`, `plan_activities` | |
| `project_milestone`, `milestone` | `milestones` | |
| `act_task_main` + `act_schedule` | `work_items` | New key `<PROJECT>-n`; the PMS key stays in `legacy_key` because it is not unique in PMS |
| `task_dependency` | `task_dependencies` | Loops are rejected and reported |
| `workflow` | `work_item_events` | Only rows whose record type matches the task's type |
| `act_dailystatus` | `task_comments` + `actual_hours` | |
| `requirements` | `requirements`, `requirement_revisions` | The PMS tag stays as the ID. Hierarchy comes from the tag (`X6.1.2` under `X6.1`). A tag used twice becomes `tag~id` and is reported |
| `requirements.document`, `tag` | `requirement_sources` | One source per project and document |
| `baselined_requirements` | `requirement_baselines`, `requirement_baseline_items` | Snapshots as written, even if the requirement has changed or gone |
| `requirement_review` | `requirement_reviews` or history | See the decisions below |
| `log_requirements` | `requirement_events` | Only rows where the state actually changed |
| `act_task_main.req_id` | `requirement_work_items` | |
| `audit_log`, `log_activity` | `legacy_audit_records` | Kept apart from the hash-chained ELM audit, whose time order must stay true |

Everything else with rows (design, development, testing and so on) is listed in the report as deferred. Those belong to later architecture sections, and this loader will grow with them. Document binaries are not part of this version, so there is no file checksum step yet.

## Decisions to review

All of these live in `backend/app/legacy_import/mapping.py`:

- **Roles.** `dev rm rd td te re` → Team Member, `pm tl tm` → Project Engineer, `rv` → Reviewer. PMS `td` means Test Case Editor, not ELM's TD. `admin` and `cm` get no automatic role, because system administration and release authority are decisions, not data.
- **Task states.** PMS has over 200 per-type names. The name decides first (close/finish, on hold, reject, short close), then the `state_status` group. Note that group 3 (`Open`, `Dev_Opened`) maps to **In progress**, so tasks PMS created as `Open` from a plan appear as started. If your teams treat `Open` as not started, change that one line in `_STATUS_GROUPS`.
- **Project of a task.** `act_task_main` has no project column; PMS uses the signed-in user's current project. The loader follows real links only: plan activity, then requirement, then parent task, then a subsystem belonging to exactly one project. If none applies, the task gets no project and is reported.
- **Time zones.** Values are treated as IST, except `act_task_main.created_on`, which reads 5h30 behind `workflow.created_date` for the same event and is treated as UTC.
- **Requirement states.** Proposed → Draft; Reviewing, Reviewed, Approving → Under review; Approved, Validated → Approved; Rejected → Rejected. Baselined is kept only if a baseline holds the requirement. These carry over from PMS, so they have no ELM review decision behind them, and each is listed.
- **Requirement reviews.** `requirement_review.status` is undocumented, so past decisions are not inferred. People assigned to a requirement under review today become pending decisions; all others are kept as history.
- **Requirement owners.** PMS records none and guessing would be wrong, so imported requirements have no owner until one is chosen. They cannot be submitted for review until then.
- **Typed progress** on PMS activities is not kept. ELM calculates progress from tasks, and each case is listed.

## Reconciliation

Each run reports source and target counts per entity, and a SHA-256 over key fields of the source rows against the values read back from ELM. A commit is refused unless the counts balance, the checksums match, and no row was rejected (or `--accept-errors` is given). See `reports/proflow_uat-trial-2026-11-05.md` for the trial run against `proflow_uat`.
