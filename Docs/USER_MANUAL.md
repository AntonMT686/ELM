# ADA-ELM — User Manual

Version 0.3 · for ADA-ELM after session 6 (architecture sections 1–14 plus checklists, tagging, traceability and reports)

This manual explains how ADA-ELM is organised, how its modules link to each other, and how to use every module step by
step. Installation is covered separately in `Docs/RUNNING.md` and `Docs/OFFLINE_DEPLOYMENT.md`.

The examples use the fictional demo data: project **ALPHA** (*Product Alpha Development*), with the breakdown
Product → System → Subsystem → Unit → Module, and demo users whose password is `Elm@12345`. All names are generic; your
own projects, levels and people replace them.

---

## Contents

1. [Getting started](#1-getting-started)
2. [How everything links together](#2-how-everything-links-together)
3. [Setting up (administrators)](#3-setting-up-administrators)
4. [Documents: prepare, checklist, review, approve, sign, release](#4-documents)
5. [Requirements: tag, analyse, review, approve, baseline](#5-requirements)
6. [Starting activities from a requirement](#6-starting-activities-from-a-requirement)
7. [Planning and tasks](#7-planning-and-tasks)
8. [Design](#8-design)
9. [Development and GitLab (version control)](#9-development-and-gitlab)
10. [Testing and defects](#10-testing-and-defects)
11. [Deployment](#11-deployment)
12. [Maintenance](#12-maintenance)
13. [Traceability](#13-traceability)
14. [Reports](#14-reports)
15. [Audit trail](#15-audit-trail)
16. [Worked example: one requirement from document to deployment](#16-worked-example)
17. [Quick reference](#17-quick-reference)

---

## 1. Getting started

### 1.1 Signing in
Open the address your administrator gives you, for example `http://elm-server:8088`, and sign in with your user name
and password. After five wrong passwords the account is locked; an administrator unlocks it.

### 1.2 The screen
| Area | What it is |
|---|---|
| Left menu | **Work** (Home, Action inbox, Planning, Tasks board), **Engineering** (Product structure, Requirements, Design, Testing & defects, Deployments, Traceability, Reports, Documents, Source control, Release register), **Governance** and **Administration** (only shown when you have the rights) |
| Search (top, or **Ctrl + K**) | Find documents, requirements, items and people, or jump to a page |
| Bell | Notifications: reviews assigned to you, decisions, due dates, deployment results. Click one to open the record |
| Moon / sun | Dark or light mode |

### 1.3 The Action inbox — your daily starting point
Everything waiting for **your** decision is in **Action inbox → Waiting for me**: document reviews, approvals and
signatures, grouped by urgency (overdue, due soon). Use **j / k** to move between items. The right side shows the
content and your decision panel. *Submitted by me* shows what you sent for review; *Out-of-office delegation* lets you
hand your inbox to a colleague for a period.

Requirement, design, test-case, test-plan and deployment reviews arrive as notifications and are decided on their own
pages (the notification link takes you there).

### 1.4 What you can do depends on your role
Roles are given **for a scope**: everywhere, one directorate, one project or one breakdown item. You only see and
change what your roles allow in that scope. The table in [§17.1](#171-roles-and-what-they-allow) lists the standard roles.

---

## 2. How everything links together

### 2.1 Organisation, projects and levels
```
Organisation (ADA)
 └─ Directorates → Departments / Divisions          (who does the work)
Project / Programme (e.g. ALPHA)
 └─ Breakdown levels, configured per project        (what is being built)
      Product → System → Subsystem → Unit → Module / Component
      e.g. ALPHA-PRD → CTL (Control System) → CTL-PRC (Processing Subsystem) → CTL-CPU (Central Processing Unit) → CTL-CPU-PSM
```
Every engineering record (document, requirement, design record, task, test case, defect) belongs to a **project** and
can be attached to a **breakdown item at any level**. That is how a requirement on the *product* is distinguished from
one on a *unit* or *module*, and how progress rolls up from modules to the product (Product structure page).

### 2.2 The lifecycle chain
```
 Document (SRS, spec at any level)
   │ specifies  (tagged paragraphs, with section)
 Requirement ── derived from / depends on / implements ── Requirement      (parent–child and links, any level)
   │ satisfies              │ implements                    │ verifies
 Design record          Task / Development task          Test case
   │ code (GitLab)          │ branch · commit · merge request  │ executed in
   ▼                        ▼                                 Test run ── found ── Defect ── fix task
                                     Deployment (includes tasks, uses a closed test run as evidence)
```
* Every arrow is a stored link. You can follow it on the record itself, on the **Traceability** page (graph and list),
  in the requirement **traceability matrix** and in the **Traceability report**.
* Every record has a **key** that appears everywhere, including GitLab: tasks `ALPHA-12`, requirements
  `ALPHA-CPU-0003` (format set per requirement source), design records `ALPHA-DES-0001`, test cases `ALPHA-TC-0001`,
  test plans `ALPHA-TP-0001`, runs `ALPHA-RUN-0001`, defects `ALPHA-DEF-0001`, deployments `ALPHA-DEP-0001`.
  Writing a key in a GitLab commit message, branch name or merge-request title links that GitLab item to the record.

### 2.3 Common rules in every module
| Rule | Meaning for you |
|---|---|
| Review is bound to the content | A decision is recorded against the exact revision and its SHA-256 fingerprint. If the content changes, earlier decisions do not count for the new content |
| Separation of duties | You cannot review, approve, verify or release your own work; the author of a deployment cannot approve it; a run's executor cannot close it |
| Nothing is overwritten | Documents, requirements, designs and test cases keep every revision or version; approved content changes only with a reason and as a new revision |
| Locked while in review | You cannot edit a record while it is being reviewed; withdraw it first |
| Everything is audited | Every change, decision, download and report is written to the tamper-evident audit trail |

---

## 3. Setting up (administrators)

Do this once per organisation or project, in this order.

| Step | Where | Who |
|---|---|---|
| 1. Directorates and departments | Administration → Organization | `admin.org` |
| 2. People, and their roles with scope | Administration → Users & access | `admin.users` |
| 3. Roles and their permissions | Administration → Roles & permissions | `admin.users` |
| 4. Projects and their breakdown levels and items | Administration → Projects & breakdown, then Product structure | `project.manage`, `item.manage` |
| 5. Document types: numbering pattern, allowed files, signature, **review checklist required** | Administration → Document types | `admin.config` |
| 6. Review workflows and which document types use them | Governance → Workflow designer | `workflow.configure` |
| 7. Task lifecycles (per project or per kind) | Governance → Task lifecycle | `workflow.configure` |
| 8. Design artefact types and their fields | API `/design-types` (screen planned) | `admin.config` |
| 9. Test failure causes | API `/test-config/failure-causes` | `workflow.configure` |
| 10. GitLab repositories per project | Engineering → Source control | `scm.manage` |
| 11. Deployment environments and their gates | Deployments → Environments | `deploy.configure`, approved by `deploy.approve` |

**Document types.** The numbering pattern uses tokens such as `{PROJECT}-{ITEM}-{TYPE}-{SEQ:3}` and produces numbers
like `ALPHA-CTL-CPU-SRS-001`. *Applicable levels* limits a type to certain breakdown levels. Switch on **Preparer must
write a review checklist before submitting** for every controlled engineering type (on by default for engineering).

**Workflows.** A workflow is a list of stages (prepare, check, review, approval, signature), each with who decides
(picked by the author, a role, named people), how many must agree (all, any, quorum), an SLA, separation-of-duties
exclusions and an optional fixed checklist set by the process owner. Publish a version, then bind it to document types,
projects or levels; the most specific binding wins.

---

## 4. Documents

### 4.1 Create
1. **Documents → New document** (or *Product structure* → item → *New document*).
2. Choose the **type**, then the **project** and **breakdown item** (only items at levels the type allows are offered).
3. Start from the template (number, title and approval table are stamped in) or upload a file.

The document gets its number and revision **A**.

### 4.2 Write the content
* **Edit online** opens OnlyOffice in the browser; every save becomes a new **iteration** (A.1, A.2 …) with its own
  fingerprint. Or upload a new file under *Revisions*.
* Link related documents (*Relations*), share with another team (*Access*), discuss (*Discussion*).

### 4.3 Prepare the review checklist (preparer)
Reviewers and approvers check the document against **your** checklist.
1. Open the document → **Review checklist** tab.
2. **Add item** for each point a reviewer must confirm, for example:
   * *Every requirement is uniquely tagged and testable* — guidance: *tags follow the source's tag format*
   * *Interfaces and referenced documents are listed with their revisions* — guidance: *sections 2 and 6*
   * *Open issues and TBDs are recorded with owners* — guidance: *Annex A*
3. Optionally limit an item to certain **stages** (e.g. only the *Reviewed By* stage). Empty means every review and
   approval stage answers it.
4. Order the items with the arrows and click **Save checklist**.

If the type requires a checklist, the main button reads **Prepare checklist to submit** until you have saved one. The
checklist is frozen while the revision is in review. A new revision starts with a copy you can adapt.

### 4.4 Submit for review
1. **Submit for review**. ELM shows the stages of the workflow that applies and, for each stage, the people eligible to
   decide (they hold the required role in the document's scope).
2. Pick the checker, reviewer(s) and approver. You cannot pick yourself.
3. Submit. The revision is locked and the first stage's people are notified.

### 4.5 Review and approve (reviewers, approvers)
1. **Action inbox** → select the item. The content is on the left; your decision panel on the right.
2. **Preparer's checklist**: for every item choose **OK**, **Not OK** or **N/A**. *Not OK* and *N/A* need a remark
   saying what is wrong and where, or why it does not apply. Answers from earlier stages of the same cycle are shown
   under each item.
3. **Process checklist** (if the process owner configured one): tick each point.
4. Decide:
   * **Accept & forward / Approve** — possible only when every item is answered and none is *Not OK*.
   * **Request changes** — needs a comment; your *Not OK* items and remarks go to the author.
   * **Reject** (if the stage allows it) — ends the cycle.

The author sees each decision and every *Not OK* item with its remark on the document page (*Changes were requested*
box and **Review history**). After updating the content the author submits again; a new cycle starts and everyone
answers the checklist again for the new content.

### 4.6 Sign, release, revise
* **Signature stage**: each person involved signs digitally by re-entering their password (*Sign digitally* in the
  inbox). The signature covers the document fingerprint.
* **Release**: the Release Authority (not the author) opens the approved document → **Release**. ELM checks the gates
  (approved, signed, file intact) and writes an entry in the **Release register**; the previous release is superseded.
  Several approved documents can be released together as a **package** with one sealed manifest.
* **Revise**: on a released document, **More → New revision** starts revision **B** from the released content.

---

## 5. Requirements

Page: **Engineering → Requirements**, then choose the project. Tabs: *Register*, *Traceability matrix*, *Baselines*,
*Sources and import*.

### 5.1 Requirement sources and the tag format
A source says where requirements come from (a specification, an SRS, an interface document, a customer document, a tool
export) and how their IDs look.
1. *Sources and import* → **New source**.
2. **Prefix**, e.g. `CPU-SRS`.
3. **Tag format**, built from tokens:

   | Token | Becomes | Example |
   |---|---|---|
   | `{PREFIX}` | the source prefix | `CPU-SRS` |
   | `{PROJECT}` | project code | `ALPHA` |
   | `{ITEM}` | code of the breakdown item | `CTL-CPU` |
   | `{LEVEL}` | code of that item's level | `UNIT` |
   | `{SEQ:n}` | running number with *n* digits (required, once) | `007` |

   Examples: `{PREFIX}-{SEQ:4}` → `CPU-SRS-0007`; `{PROJECT}-{ITEM}-SRS-{SEQ:3}` → `ALPHA-CTL-CPU-SRS-007`;
   `{PROJECT}-{LEVEL}-{SEQ:4}` → `ALPHA-SYSTEM-0012`.
4. **Source document**: the Word document the requirements are written in (optional, can be chosen later).

Requirements created by hand in this source use the same format and counter.

### 5.2 Tag requirements from a document
1. *Sources and import* → the source → **Tag from document**.
2. Choose the **document** (.docx) and what to find:
   * **Tags + shall** (default): paragraphs that already carry a tag in this format, and "shall" / "must" statements
     without a tag;
   * **Tagged only**: only paragraphs the author has already tagged;
   * **Untagged shall**: only statements still waiting for a tag.
3. **Scan document**. Each candidate shows its **section** (nearest heading), its tag (or *assigned on import*), the
   text, and what will happen: *new*, *changed* (text differs from the requirement in ELM), *unchanged*, or *approved:
   not overwritten*.
4. Tick the paragraphs to import. Choose the **breakdown item (level)** the new requirements belong to (product,
   system, subsystem, unit …; required when the tag format uses `{ITEM}` or `{LEVEL}`).
5. Leave **Write the new tags back into the document** on. ELM puts `[TAG]` at the start of each newly tagged
   paragraph and saves it as a new iteration of the document's current revision. If the document is in review or
   released, the new tags are listed for you to add by hand.
6. **Import**. The requirements are created as *Draft*, linked to the document with their section and paragraph, and
   their history records where they came from.

Scan again at any time: changed paragraphs update draft requirements; approved or baselined ones are never overwritten
(change them in ELM with a reason). Tables in the document are read too.

Other ways in: **New requirement** (by hand) and **Import CSV** (exports from DOORS or other tools).

### 5.3 Requirements at any level
Every requirement has a **Breakdown item (level)** field. Use it to place requirements on the product, a system, a
subsystem, a unit or a module. Requirements at different levels link to each other:
* **Parent** (hierarchy): a system requirement broken down into subsystem requirements;
* **Links**: *derived from*, *depends on*, *implements*, *related to*, *conflicts with*. Loops are refused.

### 5.4 Analyse, review, approve
1. **Start analysis** (Draft → Under analysis): complete title, description, acceptance criteria, type, priority and
   owner. Required fields must be filled before review.
2. **Submit for review**: pick reviewers (optional) and at least one approver; the owner and you are excluded.
3. Reviewers decide first, then approvers. Any rejection ends the cycle; resubmitting starts a new cycle with fresh
   decisions. The requirement is locked while under review.
4. All approve → **Approved**.

Changing approved or baselined content needs a **reason**; it opens a new revision, returns the requirement to
analysis, and notifies the owners of linked tasks, designs and tests.

### 5.5 Baseline (release) requirements
*Baselines* → **New baseline** (needs `req.baseline`): choose the approved requirements, give a label (e.g. *CDR*) and a
reason. The baseline is a sealed snapshot (SHA-256); later changes never alter it. Compare a baseline with the current
state or with another baseline to see what changed.

### 5.6 Impact and traceability
* **Impact** tab of a requirement: everything that depends on it (children, linked requirements, tasks, documents,
  baselines) — and a button to create an impact-review task.
* **Traceability matrix** tab: one row per requirement with traces to/from other requirements, designs, tasks, merge
  requests, documents, test cases (coloured by last result), defects and baselines; coverage figures at the top;
  *Show only untraced* finds gaps; *Export CSV*.

---

## 6. Starting activities from a requirement

Open a requirement → **Start activity**:

| Choice | Creates | Link |
|---|---|---|
| Design record | a design record in the same project and item | *satisfies* the requirement |
| Development task | a task of kind *Development* (code review, merge, test lifecycle, GitLab) | *implements* |
| Task | an ordinary task | *implements* |
| Test case | a draft test case with the acceptance criteria as expected result | *verifies* |

ELM opens the new record. The requirement's history notes what was derived from it, and the RTM and Traceability
page show the new link at once. You can also link existing records from either side.

---

## 7. Planning and tasks

* **Planning**: per project, the plan → work packages (lead and contributing directorates) → activities (phase, owner,
  dates, hours) → tasks and sub-tasks; milestones; Gantt with dependencies and critical path; baselines with variance;
  CSV import/export.
* **Tasks board**: drag a card to change its status; only allowed moves are accepted and gates are checked (sub-tasks
  closed, mandatory checklist items done, deliverable documents released, predecessors finished). *Work tasks* and
  *Development* boards use their own lifecycles.
* **Task drawer**: details, checklist, dependencies, deliverables, people (a named reviewer means the owner cannot
  accept the task), activity, and for project tasks the **Code** tab (§9).
* Progress is calculated from status: Open 0 %, Completed 100 %, in between the owner's estimate capped at 95 %.

---

## 8. Design

Page: **Engineering → Design** → project.
1. **New design record**: type (architecture, workflow, sequence, class, ER, interface, drawing, calculation, model,
   evidence …), title, description and the type's fields.
2. Add **versions**: *Edit diagram* (embedded draw.io when your administrator has installed it), upload a file (with
   an optional SVG/PNG preview), or save an external link (model repository, CAD vault). Versions are never overwritten;
   **Restore** makes a new version copying an older one.
3. **Submit for review** with reviewers and approvers (owner excluded); decisions bind to the version fingerprint.
4. **Baseline** an approved record (needs `design.baseline`). Later changes need a reason and start a new version;
   the baseline stays as it was.
5. **Traceability** tab: link requirements (*satisfies*), documents (with section), tasks and test cases.
6. **Code** tab: GitLab commits, branches and merge requests that mention the record's key (e.g. `ALPHA-DES-0001`),
   or add one by hand.
7. **PDF report**: the record with versions, reviews and traceability.

---

## 9. Development and GitLab

Version control works for every activity: tasks get branches and merge requests; design records, test cases and
defects get links to any commit, branch or merge request that names their key.

### 9.1 Once per project (`scm.manage`)
**Engineering → Source control** → **Register repository** (`group/project`). The page shows the webhook address and
whether GitLab is reachable. Ask the GitLab administrator to add the webhook (push and merge-request events) with the
secret token.

### 9.2 Developer workflow
1. Create a **Development** task (Tasks board → *Development* → *New task*, or *Start activity* on a requirement).
2. **Start development**. In the task's **Code** tab choose the repository → **Create branch**
   (`task/ALPHA-21-…`).
3. Clone, change and commit with your usual Git tools. Put the task key in commit messages: `ALPHA-21 add watchdog`.
   For design or test files, put that record's key: `ALPHA-DES-0004 update interface diagram`, `ALPHA-TC-0007 add
   automation script`.
4. **Open merge request** from the Code tab. The task moves to *Code review* automatically.
5. The named reviewer approves the code **in ELM** (*Approve code*). When GitLab reports the merge, an approved task
   moves to *Merged* automatically; a merge before approval does not skip it.
6. *Start testing* → *Complete*. A development task cannot be completed until its merge request is merged.

*Sync from GitLab* picks up anything the webhook missed. *Link by hand* records references ELM did not create (manual
reference mode). GitLab-confirmed links cannot be deleted.

---

## 10. Testing and defects

Page: **Engineering → Testing & defects** → project. Tabs: *Test cases*, *Plans*, *Runs*, *Defects*, *Coverage*.

### 10.1 Test cases
1. **New test case** (or *Start activity → Test case* on a requirement): objective, preconditions, type, steps with
   expected results, overall expected result, optional automation id.
2. Link the requirement(s) it **verifies** (Traceability tab), and designs or tasks.
3. **Submit for review** → approver approves. Only approved cases can be executed. Changing an approved case needs a
   reason and makes a new revision that needs approval again.
4. **Code** tab: test scripts in GitLab that mention the case key.

### 10.2 Test plans
1. *Plans* → **Create plan**; set scope, build/version, environments, entry criteria and exit criteria (every case
   executed, minimum pass rate, no open defects of chosen severities, manual checks confirmed at closure).
2. Add test cases to suites. **Submit for approval**, then **Activate** (`test.approve`).

### 10.3 Test runs and execution
1. On an active plan → **New run**: title, build, environment, executor. The run takes the approved cases at their
   current revision.
2. For each case → **Execute**: result *Passed / Failed / Blocked / Skipped*, actual result, notes, evidence file.
3. A **failed** result needs a **failure cause**:
   * *Application defect* → link an open defect or raise a new one (ELM creates it if you do not);
   * other causes (environment, test data, script, configuration, infrastructure, changed behaviour, equipment) are
     recorded as analysis only — no defect is raised.

### 10.4 Defects
Lifecycle: Open → In progress → Fixed → Verified → Closed (also Rejected, Deferred, reopen).
1. The defect manager assigns it; the assignee starts fixing and links a fix task.
2. **Mark fixed** with the build that contains the fix. Every run case that failed on this defect becomes **Retest**.
3. The tester re-executes: **pass → the defect is verified automatically**; fail → it re-opens on the same defect.
   The person who fixed it cannot verify it.
4. The reporter or manager **closes** the verified defect.

### 10.5 Closing a run
**Close run** (`test.approve`, not the executor): ELM checks every exit criterion and lists what is not met; manual
checks must be confirmed. Executions after closure are refused.

### 10.6 Automation
Map cases to an automation id and tool; *Run automated cases* queues a job for a registered runner; results come back
through the runner API (retries never duplicate executions). Without a runner the job fails with a clear message.

---

## 11. Deployment

Page: **Engineering → Deployments** → project. This releases **software builds** to environments; controlled documents
are released in the Release register (§4.6).

1. **Environments** (`deploy.configure`): INT, UAT, PROD or your names, each with its gates: approvals, closed test run
   of the same build, blocking defect severities, released document types, checklist, change window and blackout
   dates, verified commit, secrets, execution adapter (manual, GitLab pipeline, approved script), health check. Someone
   with `deploy.approve` other than the last editor **approves the configuration**.
2. **Request deployment**: environment, version, repository/tag/commit, test run, included tasks (release notes are
   drafted from them and their merge requests).
3. **Submit** with approvers (requester excluded), who approve in the deployment drawer.
4. **Deploy**: every gate is checked; a failing gate says exactly what is missing. The worker runs the attempt;
   *manual* deployments wait for **Record result**; a health check confirms success.
5. **Retry** a failed deployment (new attempt, history kept). **Roll back** a deployed version: a new deployment of the
   previous version with the same approvals and gates.
6. **What runs where** shows the current version per environment.

---

## 12. Maintenance

The maintenance and in-service change workflow (architecture §16: problem reports, change requests, ECR → ECN) is the
next part to be built. Until then, record maintenance work as tasks of kind *Change request* linked to the affected
requirements, designs and documents, and use defects for faults found in service.

---

## 13. Traceability

**Engineering → Traceability**, or the **Trace** button on any document, requirement, design record, task, test case,
run, defect or deployment.
* Choose where to start and the **depth** (how many steps to follow).
* **Graph**: columns from documents to deployments; click a box to open the record (code boxes open GitLab).
* **List**: the same records with their status and distance from the start.
Only records you may open are shown.

---

## 14. Reports

**Engineering → Reports** → project → **PDF** (for the record) or **CSV** (for analysis):

| Report | Contents |
|---|---|
| Document register | documents with type, level, revision, status, review cycles, owner |
| Requirements and RTM | coverage figures, status counts, the traceability matrix |
| Design register | design records with version, baseline, satisfied requirements, code links |
| Development report | development tasks with requirements, branches, merge requests, commits |
| Test summary report | runs with pass rates and exit criteria, test cases with last result |
| Defect report | defects by severity and status, builds, age |
| Deployment report | current version per environment, all deployments and attempts |
| End-to-end traceability | requirement → document → design → task → code → test → defect → deployment, with gaps |

Reports contain only records you may see, and generating one is recorded in the audit trail. The design page and the
requirement page also have their own PDF / CSV exports.

---

## 15. Audit trail

**Governance → Audit trail** (`audit.view`): every create, change, decision, signature, release, download and report,
with who, when, from where and the before/after data. **Verify chain** checks that no entry was altered or removed.

---

## 16. Worked example

One requirement from the specification to deployment, using demo users.

| # | Who | What |
|---|---|---|
| 1 | `pe.kumar` | Requirements → ALPHA → *Sources* → **New source** *CPU SRS*, prefix `CPU-SRS`, tag format `{PROJECT}-{ITEM}-SRS-{SEQ:3}`, source document = the CPU SRS |
| 2 | `pe.kumar` | **Tag from document** → scan → tick the new "shall" paragraphs → item *Unit CTL-CPU* → write tags back → Import. Requirements `ALPHA-CTL-CPU-SRS-001 …` appear as Draft, linked to their sections |
| 3 | `pe.kumar` | Open `…-001` → *Start analysis* → add acceptance criteria → **Submit for review** (approver `td.menon`) |
| 4 | `td.menon` | Opens the notification → approves. Status *Approved* |
| 5 | `pe.kumar` | *Baselines* → **New baseline** *PDR* with the approved requirements |
| 6 | `pe.kumar` | On `…-001`: **Start activity → Design record**; add a diagram version; submit; `td.menon` approves; baseline it |
| 7 | `pe.kumar` | **Start activity → Development task**; assign to a developer; *Code* tab → create branch; developer commits `ALPHA-NN …` and opens the merge request; reviewer approves code; merge |
| 8 | `eng.priya` / `rev.joshi` | **Start activity → Test case**; write steps; submit; `rev.joshi` approves; add to an active plan |
| 9 | `qa.verma` | Run the plan: execute; a failure → application defect raised; developer fixes in build 1.5.1; retest passes → defect verified; `pe.kumar` closes the run |
| 10 | `pe.kumar` | Deployments → request 1.5.1 to UAT with the closed run and the task; approver approves; **Deploy** → record result → health check |
| 11 | anyone | **Trace** on `…-001`: document → requirement → design → task → code → test → run → defect → deployment. **Reports → End-to-end traceability (PDF)** for the record |

For documents (any step that produces a controlled document): the preparer writes the **review checklist** first; the
checker, reviewer and approver answer every item; *Not OK* items go back to the author with remarks.

---

## 17. Quick reference

### 17.1 Roles and what they allow
Role names and permissions are configurable; these are the standard ones.

| Role | Typical person | Main rights |
|---|---|---|
| Project Engineer (PE) | engineer leading a project | create and edit documents, requirements, designs, tests; plans and tasks; baseline requirements and designs; GitLab repositories; configure, request and execute deployments |
| Team Member | engineer | create and edit documents, requirements, designs, test cases; request deployments |
| Checker / Reviewer / Approver | reviewers by stage | decide in document workflows (picked by the author) |
| TD / PGD (labels configurable) | technical / programme direction | approve; baseline; test approval; defect management; deployment approval |
| Directorate / Department Head | line management | documents, plans, tasks in their unit; defect management |
| Release / Configuration Authority | configuration manager | release documents, withdraw, baseline; approve and execute deployments |
| Quality / Audit | QA | audit trail; test execution, approval and run closure; defects; deployment approval |
| Process / Workflow Administrator | process owner | workflows, lifecycles, master data |
| Head Directorate Oversight | programme office | see all released documents |

### 17.2 Status meanings
| Record | Statuses |
|---|---|
| Document | Draft → In review → Changes requested / Approved → Released → Superseded / Withdrawn |
| Requirement | Draft → Under analysis → Under review → Approved → Baselined (Rejected, Deferred) |
| Design record | Draft → In progress → Submitted → Under review → Changes requested / Approved → Baselined |
| Development task | Open → In progress → Code review → Changes requested / Approved → Merged → Testing → Completed (Rejected) |
| Test case | Draft → Under review → Approved (Obsolete) |
| Test plan | Draft → Under review → Approved → Active → Closed |
| Test run | Planned → In progress → Closed |
| Defect | Open → In progress → Fixed → Verified → Closed (Rejected, Deferred) |
| Deployment | Planned → Awaiting approval → Approved → Deploying → Deployed / Failed → Rolled back (Rejected, Cancelled) |

### 17.3 Keys and shortcuts
| Key | Action |
|---|---|
| Ctrl + K | search and jump |
| j / k | next / previous item in the Action inbox |

### 17.4 Getting help
If something is refused, the message says why (missing permission, gate not met, record locked, wrong state). If you
think it is wrong, send the message text and the *request id* shown with it to the ELM administrator.
