# ADA-ELM — Session Handoff

> Read this first when resuming. Then `Docs/PROJECT_CONTEXT.md` and `Docs/ARCHITECTURE_WORKFLOWS.md` (both have an
> **"ADA-ELM implementation notes"** section at the end). Keep this file updated at the end of every session.

**Last updated:** 2026-11-05 (session 3, Sections 9 and 10)
**Repository root:** `D:\Projects\products\ADA-ELM`
**Legacy reference (data migration only):** `D:\Projects\products\PMS`, data in `proflow_uat` on port 3309 (`C:\xampp7410`, started from XAMPP). `adadb_dev` on port 3306 has the same tables but no rows. See `scripts/import_legacy/README.md`.
**On hold by the user:** tool integrations (Jira, Git, DOORS, draw.io, test runners) and anything needing new installs, because C: has about 6 GB free. Resume only when the user says the space problem is fixed. Keep new files and caches on D:.

---

## 1. Decisions taken

| Topic | Decision |
|---|---|
| Product | ADA-ELM: engineering-first (Aircraft → System → Subsystem → LRU → SRU/ECFM) plus non-engineering/administrative flows on the same document and workflow engine. The legacy PMS design is **not** reused. |
| Frontend UI | **Mantine 7.15** (user switched from AntD mid-session 1), Tabler icons, Mantine Charts (Recharts), Spotlight (Ctrl+K), React Flow, PDF.js. Inter font bundled via `@fontsource-variable`. No CDN. |
| Backend | FastAPI modular monolith, SQLAlchemy 2 (sync), UUID PKs, `version` optimistic-locking columns, portable types (SQL Server-friendly). |
| DB | PostgreSQL 16 (prod), SQLite (dev/tests). Alembic baseline `0001_baseline` uses `metadata.create_all`. **From the next schema change onward, use `alembic revision --autogenerate`.** |
| Auth | Local accounts with Argon2id. HttpOnly `elm_session` JWT cookie, SameSite=strict. CSRF double-submit (`elm_csrf` cookie + `X-CSRF-Token` header). Lockout after 5 failures. LDAP/AD adapter still to be done (`auth_source='ldap'` returns `LDAP_NOT_CONFIGURED`). |
| Authorization | Permission catalogue (`app/core/permissions.py`) → configurable roles → **scoped** assignments (GLOBAL / ORG_UNIT / PROJECT / ENG_ITEM, with descendants). Document visibility is filtered in SQL (`services/authz.py::document_visibility_clause`). The sysadmin flag gives **no** approve/release rights. |
| Workflow | Versioned JSON spec (`services/workflow_spec.py`), validated before publish. Instances stay pinned to their version. Stage types: prepare / review / approval / signature / acknowledge. Modes: all / any / quorum. Assignee: initiator / pick (with role eligibility) / role (auto) / named users. Supports SoD exclusions, checklists, SLA, skip conditions, weights, and auto-release on completion. Bindings resolve to the most specific match; ambiguous matches raise an error. |
| Review binding | Reviews bind to revision **iteration + SHA-256**. The revision is locked while in review. "Request changes" ends the cycle, the author edits (new iteration), then resubmits (cycle N+1). |
| Revisions | Letters A, B, C… (I and O skipped) or numeric. Every save is kept as an iteration (`revision_iterations`). Nothing is overwritten. A new revision is allowed only after release or withdrawal. |
| Signatures | Adapter contract in `services/signature.py`. `dev_local_ca` makes **real RSA-PSS/SHA-256** signatures with a local dev CA (keys kept in `ELM_PKI_DIR`, never in the DB). The user re-enters their password to sign, and signing can't be delegated. **Production PKI/HSM is TBD by ADA.** |
| Release | Gate checks: current, approved, file integrity, hash bound, signatures valid. The author or owner can't release (SoD). The register entry is immutable; the previous release is superseded. Withdrawal needs a reason. Packages get a SHA-256-sealed manifest. |
| Audit | Append-only, hash-chained `audit_events` with a chain head row lock. `/audit/verify` checks the chain, and reading the audit trail is itself audited. |
| OnlyOffice | User's existing Document Server (JWT on). Backend signs the editor config. OnlyOffice fetches the file through a short-lived token URL. The save callback is JWT-verified, the download host is allow-listed (SSRF), and each save becomes a new iteration. Saves to locked revisions are rejected. |
| Worker | DB-backed loop (`python -m app.worker`) for SLA overdue reminders. No Redis yet. |

## 2. What's built (code exists; **not yet compiled or run**, see §3)

### Backend `backend/app`
- `core/`: config (env `ELM_*`), db, security, permissions, errors (no stack traces leak), deps (`Ctx` with audit helper).
- `models/`: org (OrgUnit, User, UserOrgAssignment, Role, RolePermission, RoleAssignment, Delegation), project (ProcessDomain, Project, ProjectOrgAssignment, ProjectMember, HierarchyLevel, EngineeringItem, EngineeringItemOrg, WorkItem), document (FileObject, DocumentType, NumberSequence, Document, DocumentRevision, RevisionIteration, DocumentRelation, DocumentAccessGrant, DocumentComment, DocumentAccessLog), workflow (Definition, Version, Binding, Instance, StageRun, Task, SignatureRecord, ReleasePackage(+Item), ReleaseRegisterEntry), system (AuditEvent, AuditChainHead, Notification, SystemSetting).
- `services/`: authz, audit, notify, storage (magic-byte checks), numbering, documents (templates stamped with number/title/approval table), workflow_spec, workflow_engine, signature, release, onlyoffice, progress (explainable roll-up), serial.
- `api/v1/`: auth, admin (org / users / roles / assignments / delegations / doc types / domains), engineering (projects, tree with roll-up, items), documents (register, detail, workflow view, history, content upload, revise, download/inline, relations, shares, comments, workflow plan, submit, withdraw, release checks, release, signature verify), workflow (inbox, decide, sign, reassign, designer CRUD/draft/publish/bindings), releases (register, withdraw, packages), dashboard, misc (notifications, search, audit, work items), onlyoffice (config/file/callback).
- `seed.py`: fictional ADA org (PD Head Directorate, FCS, AWS, STR, ICT, QA, ADMIN plus departments), 16 users, 13 roles, AMCA (5 levels, about 20 items) and MK1 (Aircraft→LRU→ECFM), 12 document types (engineering / management / non-engineering), 3 workflows. Demo documents are **driven through the real engine** (one released with 4 signatures, others in review, changes requested, approved, programme document in quorum concurrence, and admin documents auto-released).
- `tests/test_platform.py`: login/CSRF, scope isolation, the full lifecycle (SoD, checklist, request changes → resubmit, signing, wrong password, author can't release, release, revise → B), audit chain, dashboard/tree, and the OnlyOffice callback guard.

### Frontend `frontend/src` (Mantine)
App shell (collapsible dark nav, Ctrl+K Spotlight, theme toggle, notifications drawer). Pages:
Login · Home dashboard (KPIs, next actions, pipeline, aging, programme rings, directorate bars, throughput, activity) ·
**Action inbox** (grouped overdue/soon, j/k keys, live preview + lifecycle tracker, checklist-gated approve, request changes/reject, sign modal with password, reassign, delegations) ·
**Product structure explorer** (tree with level tags + progress bars, item panel with stacked status bar, docs/sub-items/tasks, add sub-item with automatic level) ·
Document register (filters, quick chips) and a **guided New Document wizard** (type → item, filtered by applicable level → template/upload) ·
**Document workspace** (header actions by permission, lifecycle tracker, smart Submit modal with eligible candidates per stage, release gate checklist, upload, revise, share, link, child doc; tabs: preview (OnlyOffice view/PDF.js/image), review history, revisions + iterations, signatures with verify, relation graph, discussion, access, audit) ·
Full-screen OnlyOffice editor · Release register + packages · Kanban tasks board (drag and drop) ·
**Visual workflow designer** (React Flow canvas, stage inspector, bindings, versions, validate & publish) ·
Audit trail with chain verify · Admin: organization tree, users and scoped roles, role × permission matrix, document types, projects and breakdown levels.

### Deploy
`docker-compose.yml` (db / backend / worker / web, optional `onlyoffice` profile), `backend/Dockerfile` (uses `backend/wheels` offline if present), `frontend/Dockerfile` + `nginx.conf` (CSP allows the OnlyOffice origin), `.env.example`, `deploy/scripts/build_offline_bundle.sh`, `install_offline.sh`.

## 2a. Session 2 (2026-11-04)
- User ran the steps: `npm install && npm run build` **succeeded** (frontend/dist built, package-lock.json kept).
- `pytest`: all 8 tests **errored at setup** (startup/seed). Root cause found: `SessionLocal(autoflush=False)` meant queries
  inside one use-case didn't see just-added rows (seed `pending()` returned None; signature stage could not find approvers).
  Fixed → `autoflush=True` in `app/core/db.py`. Awaiting user re-run of pytest to confirm (paste output if anything fails).
- Login bug: sign-in succeeded but UI bounced back to /login (cached `me` error state in React Query). Fixed: LoginPage fetches `/auth/me` and `setQueryData` before navigating; `Protected` shows loader while refetching after an error.
- Flicker loop (/ ↔ /login): `useEffect(() => setUnauthorizedHandler(...))` returned the handler, so React ran it as cleanup on every navigation. Fixed with a block body; `setUnauthorizedHandler` now returns void.
- Document page blank: SubmitModal evaluated `plan.data.definition` while closed (modal children are evaluated eagerly). Guarded; added `ErrorBoundary` around page outlet so crashes show a message, not a blank screen.
- Layout: Mantine AppShell `layout="alt"` (sidebar full height from top; header starts right of it); header is a 3-column grid with search centred.
- Offline Windows deployment added: `deploy/offline/` (prepare-offline-bundle.ps1 on connected PC → `dist/ADA-ELM-Offline-0.1.0/`; START/STOP/STATUS/BACKUP .bat + elm.ps1 on server; docker-compose.offline.yml incl. OnlyOffice 8.2.2 with generated JWT, service-name URLs). Guide: `Docs/OFFLINE_DEPLOYMENT.md`. Not yet executed end-to-end.
- Offline: reuses an OnlyOffice already running on the server (auto-detects container, port, JWT via `docker exec ... local.json`; checks ALLOW_PRIVATE_IP_ADDRESS); bundled OnlyOffice only via `COMPOSE_PROFILES=bundled-onlyoffice`. `prepare-offline-bundle.ps1 -SkipOnlyOffice` leaves its image out.
- Seed split: `ELM_SEED_DEMO_DATA=false` → `seed_minimal()` (ADA root org, `admin` with ELM_ADMIN_PASSWORD, roles, domains, doc types, workflows). `python -m app.seed` / dev startup call `run()`.
- `.env.example` rewritten with comments on their own lines (no inline comments).
- Explained to user how to run (Docker / local dev) and how to obtain OnlyOffice JWT secret + URLs (incl. `ALLOW_PRIVATE_IP_ADDRESS`).

## 2b. Session 3 (2026-11-04): architecture §9, Programme / Project Planning and Tasks
Sections 1–8 are treated as done, per the user. Section 9 is now built.

**Backend.** `models/planning.py`: PlanPhase, ProjectPlan, Milestone, WorkPackage(+Org), PlanActivity, TaskDependency, TaskParticipant, TaskChecklistItem, TaskDeliverable, TaskComment, WorkItemEvent, PlanBaseline, LegacyImportRun/Map, LegacyAuditRecord. `WorkItem` stays the task entity and gained hierarchy, hours, weight, actual dates and legacy fields.
- `services/task_lifecycle.py`: configurable lifecycle (states with categories, transitions with allowed actors and required reasons), validated on save. Default is the §9.3 template. Status codes changed: TODO→OPEN, BLOCKED→ON_HOLD, DONE→COMPLETED, plus REVIEW and CHANGES_REQUESTED. **Status now only changes through `POST /work-items/{id}/transition`.** PUT no longer accepts it.
- Gates: completion needs sub-tasks closed, mandatory checklist done, mandatory deliverable documents at their required real status, and dependencies satisfied (switchable in `task.completion_rules`). Start is gated by FS/SS predecessors. A task with a named reviewer cannot be accepted by its owner (`SOD_VIOLATION`).
- Progress is server-calculated: Open 0, Completed 100, otherwise the assignee's estimate capped at 95; parents and activities roll up by weight or hours. A 100% plan with open gates reports `fully_complete: false` (scenario G).
- `services/planning.py`: WBS, explainable overview, schedule conflicts, critical path, sealed baselines and variance. `services/planning_sweep.py`: due-date and milestone reminders in the worker.
- `api/v1/tasks.py` replaces the task routes in `misc.py`. `api/v1/planning.py`: plans, phases, milestones, work packages, activities, baselines, portfolio, CSV export (formula-safe) and CSV import (validated, all-or-nothing).
- **Security fixes in existing code:** task routes used `has_any("task.manage")`, so a task manager anywhere could change any task; the task list and `GET /projects/{id}`, `/tree` and `/items/{id}` also had no project scope. All are now scope-checked.
- New permission `plan.manage` (PGD, TD, DIR_HEAD, PE). Migration `0002_planning` is hand-written and idempotent because `0001` uses `create_all`. It maps old statuses and grants the permission.

**Frontend.** `/planning` (portfolio), `/planning/:projectId` (Overview, WBS, Gantt in plain SVG with dependencies and critical path, Milestones, Baselines with variance, CSV), lifecycle-driven `/tasks` board, shared `TaskDrawer` (transitions with blockers, checklist, dependencies, deliverables, people, activity), `/admin/task-lifecycle`. No new npm or Python runtime dependency.

**Migration.** `scripts/import_legacy/extract_pms.py` (read-only, makes a JSON bundle) and `python -m app.legacy_import.load` (dry run by default, `--commit`, `--rollback`, reconciliation and exception reports). Decisions for ADA are in `app/legacy_import/mapping.py` and `scripts/import_legacy/README.md`. Trial against `proflow_uat`: 29/29 tasks, 26 users created and 1 linked, 8 projects, 1 plan, 4 activities, checksums match; 1 milestone and 3 memberships point at a project or users that do not exist in PMS. Report: `scripts/import_legacy/reports/proflow_uat-trial-2026-11-04.md`. **It has not been run against the user's Docker database.**

**Verified this session:** pytest 28/28 on SQLite. Before the final small edits, 25/25 on a temporary PostgreSQL 16, along with Alembic fresh install, downgrade, upgrade from the old schema and `alembic check` (no drift), and import dry run, commit, re-run (0 created), refused rollback, rollback and re-import with the audit chain valid. `npm run build` passes. Browser walkthrough on the Vite dev server with SQLite: portfolio, overview, WBS, Gantt, task drawer, a real transition, board, admin lifecycle, imported VCON plan.
**Not verified:** the Docker deployment with this code (the image on this PC is older), drag and drop on the board, the plan/work-package/activity/milestone/baseline/CSV forms in the browser (their APIs are tested), and the importer's test suite on PostgreSQL.

**Not built in §9:** XLSX and MS Project XML import/export, and Jira sync (on hold). Traceability currently reaches documents only; requirements, design, tests and so on arrive with their sections.

## 2c. Session 3 continued (2026-11-05): architecture §10, Requirement Management
**Backend.** `models/requirements.py`: RequirementSource, Requirement, RequirementRevision, RequirementReview, RequirementLink, RequirementWorkItem, RequirementDocument, RequirementEvent, RequirementBaseline(+Item). `services/requirements.py`, `api/v1/requirements.py`, migration `0003_requirements`, permissions `req.edit` (PGD, TD, DIR_HEAD, PE, TEAM_MEMBER) and `req.baseline` (PGD, TD, PE, RELEASE_AUTH).
- Lifecycle is configurable through `/requirement-lifecycle` (API only, no screen yet). The states DRAFT, UNDER_ANALYSIS, UNDER_REVIEW, APPROVED, REJECTED and BASELINED are required because the code gives them meaning. Actors are `owner`, `manager`, `system`; system moves happen only through decisions, baselining and edits.
- Review: submit picks reviewers (optional) and approvers (at least one). Reviewers decide first, then approvers. Every decision binds to revision and SHA-256. The owner and submitter are excluded. Any rejection ends the cycle; a new cycle needs fresh decisions. Locked while under review.
- Editing approved or baselined content needs a reason, opens a new revision, returns to analysis, and notifies owners of linked work. Old revisions and baselines never change.
- Baselines store a full text snapshot per item, SHA-256 sealed, comparable with live data or another baseline.
- Impact: children and depends_on / derived_from / implements dependents (transitive), tasks, documents, baselines, filtered by access. It reports only, and can create a CHANGE_REQUEST review task with a checklist.
- RTM with coverage counts and CSV export. Design, development, test and defect columns come with §11–§13.
- File exchange: CSV import with preview (new, changed, conflicts, removed). Approved content is never overwritten and removed rows are only reported. ReqIF and the live DOORS adapter wait with tool integrations.

**Frontend.** `/requirements/:projectId`: register with hierarchy and filters, detail drawer (content, traceability, impact, reviews, history), RTM, baselines with compare, sources and CSV import. Requirements show on the task drawer.

**Migration.** `extract_pms.py` and the loader now cover requirements, sources, baselines, review assignments, state history and task links. Trial against `proflow_uat`: 79/79 requirements, 13 sources, 11 baselines with 15 items, 6 task links, checksums match, re-run creates 0, rollback restores the demo data with the audit chain valid. Report: `scripts/import_legacy/reports/proflow_uat-trial-2026-11-05.md`. **Re-extract: older bundles have no requirement data.** `requirement_review.status` is undocumented, so no past decision is inferred; imported Approved and Baselined states have no ELM review record. 79 imported requirements have no owner, since PMS records none. Deferred: `requirement_group_map`, `req_milestone_mapping`, `requirement_verification_mapping`, `testcase_requirement_link` (with §13), `tagged_doc` contents.

**Verified:** pytest 44/44 on SQLite and on a temporary PostgreSQL 16; migration `0003` upgrading a database with data, downgrade and re-upgrade, fresh install with seed, `alembic check` (no drift); `npm run build`; browser on the Vite dev server with SQLite: register, submit gate, impact, editing approved content (warning, required reason, new revision), a reviewer decision, real imported VCON data.
**Not verified:** the Docker deployment with this code, and the real-data import on PostgreSQL (the 2026-11-05 trial used SQLite; the 2026-11-04 trial on PostgreSQL predates requirements; the importer's tests pass on both). In the browser: baseline creation and CSV import (their APIs are tested).
**Known gap:** requirement reviews reach people by notification but are not in the Action inbox, which reads document workflows only. Add them there next.

**Environment notes.** `pms-gitlab` uses about 6.4 GB of Docker's 7.65 GB VM, which likely caused the Docker hang on 2026-11-04; stop it when it is not needed. `ada-elm-worker-1` shows unhealthy because it inherits the backend image's HTTP healthcheck and has no web server; add `healthcheck: { disable: true }` for the worker in the compose files.

## 3. Older verification items
1. `docker compose up -d --build`, sign in as each persona, and walk through: create → edit in OnlyOffice → submit → check → review → approve → 4 signatures → release by `cm.sharma`.
2. Check OnlyOffice networking: browser → `ELM_ONLYOFFICE_PUBLIC_URL`, OnlyOffice → `ELM_BACKEND_INTERNAL_URL` (web:80 proxies `/api`), backend → `ELM_ONLYOFFICE_INTERNAL_URL`. The JWT secret must match the Document Server.

## 4. Backlog (priority order)
1. **Architecture §11, Design and engineering artefacts**, the next section. The draw.io part waits with tool integrations; records, uploads, versions, review and requirement links do not. Extend `app/legacy_import` at the same time.
2. Run the migration on the real target after a backup and a dry run, then have ADA review the exceptions.
3. LDAP/AD authentication adapter, MFA hook, session revocation table. Imported users cannot sign in until this exists or an administrator sets passwords.
4. PDF report generation (reportlab is in requirements): release transmittal, document register, RTM, approval aging, plan and progress reports.
5. Engineering modules: §11–§16 in order, change requests / ECR→ECN workflow on `WorkItem.kind=CHANGE_REQUEST`, verification and test evidence, SDLC modules for software work packages.
6. **On hold (tool integrations):** self-hosted draw.io (`.drawio` is already an allowed type for DDD), Jira, Git, DOORS, test runners.
7. Watermarking / print and download controls by classification. Malware-scan adapter (`FileObject.scan_status`).
8. SLA working calendar and holidays, escalation to managers, email adapter.
9. Proper Alembic autogenerated migrations, a SQL Server compatibility test, backup/restore scripts, SBOM.
10. Production PKI/HSM signature adapter (PAdES if ADA picks PDF signing).

## 5. Open ADA decisions (still TBD)
PGD/TD meaning and permission mapping · official org list · classification labels and handling rules · numbering
schemes per document type · PKI/token standard · identity provider (LDAP/AD details) · retention · target OS/CPU · RPO/RTO.

## 6. Conventions
- API prefix `/api/v1`. Errors are `{error:{code,message,details,request_id}}`. Every mutating endpoint writes an audit event in the same transaction.
- Never hard-code directorates, roles, levels, stages or document types. Seed data is demo only.
- Frontend: `useAction()` for mutations (notifications + invalidation). Permissions come from `/auth/me`, and the UI hides actions but the server enforces them.
