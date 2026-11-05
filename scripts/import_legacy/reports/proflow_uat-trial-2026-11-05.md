# PMS import report (COMMITTED)

- Result: **PASS**
- Run id: `cb3cbf27-220c-4981-aa2a-6f9ab0d2e742`
- Source: proflow_uat extracted 2026-11-04T18:36:35.760498+00:00
- Bundle SHA-256: `d18a49277699f200e32260c7b35ed268695c893848a4292d33bb1f60e8bfba0c`

## Counts

| Entity | Source | Created | Linked | Already imported | Skipped |
|---|---:|---:|---:|---:|---:|
| engineering_items | 9 | 9 | 0 | 0 | 0 |
| legacy_audit_records | 144 | 144 | 0 | 0 | 0 |
| milestones | 5 | 4 | 0 | 0 | 1 |
| org_units | 7 | 7 | 0 | 0 | 0 |
| plan_activities | 4 | 4 | 0 | 0 | 0 |
| plan_phases | 5 | 0 | 5 | 0 | 0 |
| project_members | 32 | 32 | 0 | 0 | 0 |
| project_plans | 1 | 1 | 0 | 0 | 0 |
| projects | 8 | 8 | 0 | 0 | 0 |
| requirement_baseline_items | 15 | 15 | 0 | 0 | 0 |
| requirement_baselines | 11 | 11 | 0 | 0 | 0 |
| requirement_history | 69 | 69 | 0 | 0 | 0 |
| requirement_reviews | 27 | 25 | 0 | 0 | 2 |
| requirement_sources | 13 | 13 | 0 | 0 | 0 |
| requirement_task_links | 6 | 6 | 0 | 0 | 0 |
| requirements | 79 | 79 | 0 | 0 | 0 |
| role_assignments | 51 | 33 | 16 | 0 | 2 |
| task_comments | 4 | 4 | 0 | 0 | 0 |
| task_dependencies | 2 | 2 | 0 | 0 | 0 |
| users | 27 | 26 | 1 | 0 | 0 |
| work_item_events | 18 | 18 | 0 | 0 | 0 |
| work_items | 29 | 29 | 0 | 0 | 0 |

## Reconciliation (source values against what was read back from ELM)

| Entity | Rows | Match |
|---|---:|---|
| milestones | 4 | yes |
| plan_activities | 4 | yes |
| project_plans | 1 | yes |
| projects | 8 | yes |
| requirement_baseline_items | 15 | yes |
| requirements | 79 | yes |
| task_dependencies | 2 | yes |
| users | 26 | yes |
| work_items | 29 | yes |

## Exceptions (39)

| Severity | Entity | Source id | Message |
|---|---|---|---|
| REVIEW | projects | 1 | TP: PMS has no directorate on a project. Set the lead and contributing directorates in ELM. |
| REVIEW | projects | 2 | EP: PMS has no directorate on a project. Set the lead and contributing directorates in ELM. |
| REVIEW | projects | 3 | RBP: PMS has no directorate on a project. Set the lead and contributing directorates in ELM. |
| REVIEW | projects | 5 | AS: PMS has no directorate on a project. Set the lead and contributing directorates in ELM. |
| REVIEW | projects | 6 | DC: PMS has no directorate on a project. Set the lead and contributing directorates in ELM. |
| REVIEW | projects | 7 | KL: PMS has no directorate on a project. Set the lead and contributing directorates in ELM. |
| REVIEW | projects | 9 | VCON: PMS has no directorate on a project. Set the lead and contributing directorates in ELM. |
| REVIEW | projects | 10 | AWS: PMS has no directorate on a project. Set the lead and contributing directorates in ELM. |
| REVIEW | role_assignments | 1 | PMS role 'admin' for user 1 on project 1 has no automatic ELM role. Assign one if needed; project membership was imported. |
| REVIEW | role_assignments | 67 | PMS role 'admin' for user 11 on project 9 has no automatic ELM role. Assign one if needed; project membership was imported. |
| REVIEW | requirements | 7 | Tag EPEXDTESESBSREQ2 is used by 3 PMS requirements in this project. Imported as EPEXDTESESBSREQ2~7; merge them if they are the same requirement. |
| REVIEW | requirements | 11 | Tag EPEXDTESESBSREQ2 is used by 3 PMS requirements in this project. Imported as EPEXDTESESBSREQ2~11; merge them if they are the same requirement. |
| REVIEW | requirements | 12 | Tag EPEXDTESESBSREQ2 is used by 3 PMS requirements in this project. Imported as EPEXDTESESBSREQ2~12; merge them if they are the same requirement. |
| REVIEW | requirements | 78 | Tag VCONSRSMEAPREQ9 is used by 2 PMS requirements in this project. Imported as VCONSRSMEAPREQ9~78; merge them if they are the same requirement. |
| REVIEW | requirements | 80 | Tag VCONSRSMEAPREQ9 is used by 2 PMS requirements in this project. Imported as VCONSRSMEAPREQ9~80; merge them if they are the same requirement. |
| REVIEW | users | - | PMS administrators, not made ELM system administrators automatically: admin, anton. |
| REVIEW | users | - | 26 imported account(s) cannot sign in yet. PMS passwords are not migrated; set passwords in Users & access, or enable LDAP. |
| WARN | project_members | project_user_role:24 | Refers to project 8 / user 1, which do not both exist. |
| WARN | project_members | user_project_mapping:4 | Refers to project 1 / user 15, which do not both exist. |
| WARN | project_members | user_project_mapping:25 | Refers to project 1 / user 24, which do not both exist. |
| WARN | milestones | project_milestone:4 | Milestone '2' refers to project 8, which does not exist. Not imported. |
| WARN | work_items | 19 | Invalid planned end date '0000-00-00'; used the expected completion date 2026-05-11. |
| WARN | requirement_baselines | 0 | Baseline 'first baseline for test project' holds TPDT1DSDSSREQ1.2.1, which is not among the imported requirements. The snapshot was kept. |
| WARN | requirement_baselines | 3 | Baseline '2nd baseline req' holds TPDT1DSDSSREQ1.2.2, which is not among the imported requirements. The snapshot was kept. |
| INFO | users | 1 | Username admin already exists in ELM. Linked to it; the ELM account was not changed. |
| INFO | plan_activities | 1 | 'Requirements Capture and Finalize': PMS held a typed progress of 10.0% with status not_started. ELM calculates activity progress from its tasks, so that figure was not kept. |
| INFO | work_items | 33 | PMS priority value 2 is unknown; used MEDIUM. |
| INFO | work_items | 34 | PMS priority value 2 is unknown; used MEDIUM. |
| INFO | requirements | 1 | TPDT1DSDSSREQ3: state Reviewing was carried over from PMS. It was not approved through ELM's review, so no ELM review decision exists for it. |
| INFO | requirements | 3 | TPDT1DSDSSREQ5: state Reviewing was carried over from PMS. It was not approved through ELM's review, so no ELM review decision exists for it. |
| INFO | requirements | 4 | TPDT1DSDSSSEC1.2: state Approved was carried over from PMS. It was not approved through ELM's review, so no ELM review decision exists for it. |
| INFO | requirements | 6 | EPEXDTESESBSREQ1: state Approved was carried over from PMS. It was not approved through ELM's review, so no ELM review decision exists for it. |
| INFO | requirements | 66 | VCONSRSMEAPREQ4: state Baselined was carried over from PMS. It was not approved through ELM's review, so no ELM review decision exists for it. |
| INFO | requirements | 67 | VCONSRSMEAPREQ5: state Baselined was carried over from PMS. It was not approved through ELM's review, so no ELM review decision exists for it. |
| INFO | requirements | 74 | VCONSRSMEAPREQ7: state Baselined was carried over from PMS. It was not approved through ELM's review, so no ELM review decision exists for it. |
| INFO | requirements | 88 | AWSSSSREQ6: state Baselined was carried over from PMS. It was not approved through ELM's review, so no ELM review decision exists for it. |
| INFO | requirements | 94 | AWSSSSREQ4.1: state Baselined was carried over from PMS. It was not approved through ELM's review, so no ELM review decision exists for it. |
| INFO | requirements | 108 | AWSSSSREQ12: state Baselined was carried over from PMS. It was not approved through ELM's review, so no ELM review decision exists for it. |
| INFO | requirements | 4 | TPDT1DSDSSSEC1.2: its parent tag is not among the imported requirements, so it has no parent. |

## PMS tables with data not migrated by this version

These belong to later phases (requirements, design, development, testing, deployment, maintenance, documents). They are not lost: PMS stays read-only as the source.

| Table | Rows |
|---|---:|
| act_development | 8 |
| act_l1_testing | 2 |
| act_l2testing | 2 |
| act_l3_testing | 2 |
| act_tc_task | 1 |
| attachment | 1 |
| auth_assignment | 97 |
| auth_ldap_config | 1 |
| baseline_doc_versions | 4 |
| baselined_doc_history | 9 |
| comment | 40 |
| configurations | 11 |
| csci_name | 8 |
| csciversion | 3 |
| custom_reports | 8 |
| defect_workflow_transition | 13 |
| df_wdg_detailsmaster | 20 |
| df_widgetmasterdata | 2 |
| di_do_file | 1 |
| di_do_interconnection | 1 |
| discipline | 4 |
| dms_comments | 4 |
| dms_doc_types | 1 |
| dms_documents | 3 |
| dms_folder_permissions | 3 |
| dms_folder_sources | 2 |
| dms_folders | 3 |
| doc_authorities | 2 |
| doc_changed_section | 80 |
| document | 3 |
| document_process_config | 13 |
| document_section | 103 |
| epm_task | 3 |
| ess_ai_file | 1 |
| facility | 1 |
| gitflow_activity | 42 |
| gitflow_branch | 4 |
| gitflow_branch_level | 4 |
| gitflow_commit_log | 3 |
| gitflow_config | 1 |
| gitflow_group | 1 |
| gitflow_merge_request | 1 |
| gitflow_repo | 1 |
| gitlab_activity_log | 51 |
| gitlab_config | 1 |
| gitlab_project_link | 6 |
| gitlab_repo_link | 6 |
| grade | 8 |
| handing_overs | 1 |
| handing_taken_link | 1 |
| handingover_masterdata | 8 |
| handingover_material | 3 |
| hardware_intiallisation | 1 |
| integration_config | 7 |
| linked_tag_history | 6 |
| log_act_development | 44 |
| log_act_l1_testing | 7 |
| log_act_l2testing | 11 |
| log_act_l3_testing | 7 |
| log_act_schedule | 54 |
| log_act_task_main | 118 |
| log_tagged_doc | 26 |
| log_testcase_input_output | 7 |
| log_update_requirements | 1 |
| logondetails | 289 |
| master_data_tables | 1 |
| menu | 90 |
| migration_report | 1 |
| mom | 1 |
| notification | 11 |
| page | 1 |
| pep | 1 |
| priority | 2 |
| process_flow_configuration | 23 |
| process_workflow_completion | 41 |
| project_csciversion | 9 |
| project_doctype | 8 |
| project_group | 9 |
| project_reqtype | 10 |
| project_roles | 22 |
| project_subsystem | 7 |
| project_system | 6 |
| project_system_mapping | 2 |
| projectstatus | 2 |
| ras_affected_display_mapping | 9 |
| ras_affected_interface_mapping | 2 |
| ras_coexist_data | 1 |
| ras_main | 16 |
| ras_master_data | 42 |
| ras_master_phases | 4 |
| ras_mode_mapping | 16 |
| ras_new_mapping | 16 |
| ras_phase_mapping | 16 |
| ras_req_affected_mapping | 14 |
| ras_requirement_mapping | 16 |
| ras_state_mapping | 16 |
| release | 3 |
| release_workflow_transition | 11 |
| report_template | 1 |
| report_template_section | 2 |
| report_workflow_transition | 10 |
| req_milestone_mapping | 14 |
| requirement_group_map | 6 |
| requirement_masterdata | 2 |
| requirement_position | 7 |
| requirement_verification_mapping | 14 |
| requirement_workflow_transition | 17 |
| reviewstatus | 2 |
| role_menu | 371 |
| rpt_additional_record | 3 |
| rpt_amd_record | 1 |
| rpt_amdrecod_mapping | 1 |
| rpt_authority_list | 21 |
| rpt_authority_user | 1 |
| rpt_change_description | 1 |
| rpt_data_dictionary | 1 |
| rpt_deliverable_mapping | 2 |
| rpt_dictionary_mapping | 2 |
| rpt_formal_qualification | 1 |
| rpt_main | 4 |
| rpt_masterdata | 134 |
| rpt_milestone_software_deliverable | 1 |
| rpt_prerequisite_package | 1 |
| rpt_referdoc_mapping | 2 |
| rpt_reference_doc | 1 |
| rpt_scope | 2 |
| rpt_spec_config | 3 |
| rpt_subsysdetails | 1 |
| rpt_test_description | 1 |
| sca_interface | 2 |
| sca_structure | 1 |
| scenario_info | 1 |
| scenario_script | 1 |
| software_flashing | 1 |
| state_map | 82 |
| state_role_map | 63 |
| sub_discipline | 15 |
| subsystem_version_mapping | 2 |
| system_subsystem_mapping | 3 |
| tagged_doc | 25 |
| tagged_doc_flag | 1 |
| tagged_doc_variables | 54 |
| tagged_doc_version | 1 |
| tags | 10 |
| taken_overs | 1 |
| testcase_checklists | 8 |
| testcase_ciu_checklists | 8 |
| testcase_comments | 22 |
| testcase_defect_attachments | 2 |
| testcase_defect_comments | 10 |
| testcase_defects | 2 |
| testcase_inout_link | 3 |
| testcase_input_output | 11 |
| testcase_input_output_alias | 3 |
| testcase_main_general | 7 |
| testcase_master_data | 25 |
| testcase_pep | 8 |
| testcase_requirement_link | 6 |
| testcase_type | 2 |
| testcase_unit | 3 |
| testcase_workflow | 2 |
| trace_req_order | 2 |
| typeofdevelopment | 2 |
| user_company_name | 3 |
| user_group | 5 |
| user_group_map | 52 |
| user_qualification | 4 |
| verification_methods | 1 |
| version_number | 1 |
| view_report_display_fields | 8 |
| view_report_dropdown_filter | 4 |
| view_reports | 1 |
