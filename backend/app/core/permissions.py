"""Permission catalogue. Roles map to these codes through configuration (role_permissions)."""

PERMISSIONS: dict[str, str] = {
    # documents
    "doc.view": "View documents in scope",
    "doc.create": "Create documents",
    "doc.edit": "Edit draft documents / upload revisions",
    "doc.download": "Download document files",
    "doc.share": "Share documents with other teams",
    "doc.release": "Release approved documents (Release Authority)",
    "doc.withdraw": "Withdraw / supersede released documents",
    "release.view_all": "Central Release Register oversight (Head Directorate)",
    # engineering structure / projects
    "project.view": "View projects",
    "project.manage": "Create/update projects and hierarchy levels",
    "item.manage": "Create/update engineering items (System/LRU...)",
    # requirements
    "req.edit": "Create, edit and link requirements, and submit them for review",
    "req.baseline": "Baseline approved requirements and manage requirement sources",
    # planning and work items
    "plan.manage": "Create and change plans, milestones, work packages, activities and baselines",
    "task.manage": "Create and assign tasks",
    # workflow configuration
    "workflow.configure": "Design, validate and publish workflows",
    # administration
    "admin.org": "Manage organization structure",
    "admin.users": "Manage users and role assignments",
    "admin.config": "Manage document types and master data",
    "audit.view": "View audit trail",
}
