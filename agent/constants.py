"""
상수 정의 — 도메인 그룹, 쓰기 도구, Fallback 맵

bot_brain.py에서 추출 (복사). 원본은 수정하지 않는다.
"""

# ── 도메인별 도구 그룹핑 (75개 → 12개 그룹) ──
DOMAIN_GROUPS: dict[str, list[str]] = {
    "project_issue": [
        "list_projects", "get_project", "list_issues", "get_issue",
        "create_issue", "update_issue", "change_issue_status", "assign_issue",
    ],
    "request_job": [
        "list_request_jobs", "get_request_job", "get_request_job_stats",
        "create_request_job", "assign_request_job", "update_request_job",
        "change_request_job_status", "delete_request_job",
        "get_customer_request_jobs",
    ],
    "customer": [
        "list_customers", "get_customer", "search_similar_customers",
        "get_customer_projects", "list_customer_contacts", "get_customer_contact",
        "get_customer_corporation", "search_integrated_customer",
        "get_customer_card", "search_maintenance_customer",
        "get_customer_timeline",
    ],
    "maintenance_contract": [
        "list_maintenance_contracts", "get_maintenance_contract",
        "get_expiring_maintenance", "get_maintenance_plan",
        "renew_maintenance_contract", "update_maintenance_contract",
        "expire_maintenance_contract", "get_expired_active_contracts",
        "get_contract_renewal_gaps", "list_sales_managers",
    ],
    "checkup": [
        "list_maintenance_issues", "get_current_month_checkups",
        "get_upcoming_checkups", "get_pending_checkups",
        "get_checkups_by_date_range", "get_maintenance_status",
        "get_contract_issues", "complete_maintenance_checkup",
        "get_server_checkup_data", "save_server_checkup_data",
    ],
    "server": [
        "list_servers", "get_server", "get_customer_servers",
        "search_servers", "get_server_count",
    ],
    "salesforce": [
        "search_expiring_contracts", "get_salesforce_sync_status",
        "get_salesforce_account",
    ],
    "product_license": [
        "list_products", "get_product", "list_product_versions",
        "list_licenses", "get_license", "get_license_stats",
    ],
    "user_engineer": [
        "list_engineers", "list_user_names", "list_sales_managers",
        "get_project_members",
    ],
    "epic_label_comment": [
        "list_epics", "get_epic", "list_labels", "get_label",
        "list_comments", "create_comment",
    ],
    "notification": [
        "notify_expiring_contracts", "send_email",
    ],
    "memory": [
        "search_memory",
    ],
}


# ── 항상 포함하는 도메인 ──
ALWAYS_INCLUDE_DOMAINS = {"memory", "user_engineer"}


# ── 쓰기 도구 (검증 Quick-Pass, 중복 실행 방지) ──
WRITE_TOOLS: set[str] = {
    "create_issue", "update_issue", "change_issue_status", "assign_issue",
    "create_request_job", "assign_request_job",
    "update_request_job", "change_request_job_status", "delete_request_job",
    "complete_maintenance_checkup", "save_server_checkup_data",
    "renew_maintenance_contract", "update_maintenance_contract",
    "expire_maintenance_contract",
    "notify_expiring_contracts", "send_email",
    "create_comment",
}


# ── 도구 Fallback 맵 (Reflection / Re-planner 재시도용) ──
TOOL_FALLBACK_MAP: dict[str, list[str]] = {
    "search_integrated_customer": [
        "search_maintenance_customer", "list_maintenance_contracts",
        "list_customers",
    ],
    "get_expiring_maintenance": ["list_maintenance_contracts"],
    "search_expiring_contracts": [
        "list_maintenance_contracts", "get_expiring_maintenance",
    ],
    "list_maintenance_contracts": [
        "search_maintenance_customer", "search_expiring_contracts",
    ],
    "get_current_month_checkups": [
        "get_checkups_by_date_range", "list_maintenance_issues",
        "get_maintenance_plan",
    ],
    "get_customer_servers": ["list_servers", "search_servers"],
    "list_customers": [
        "search_similar_customers", "search_maintenance_customer",
        "search_integrated_customer",
    ],
    "search_similar_customers": [
        "list_customers", "search_maintenance_customer",
        "search_integrated_customer",
    ],
    "get_pending_checkups": [
        "list_maintenance_issues", "get_maintenance_plan",
    ],
    "get_upcoming_checkups": [
        "get_checkups_by_date_range", "get_maintenance_plan",
        "list_maintenance_issues",
    ],
    "get_checkups_by_date_range": [
        "get_maintenance_plan", "list_maintenance_issues",
    ],
    "search_maintenance_customer": [
        "search_integrated_customer", "list_maintenance_contracts",
        "list_customers",
    ],
}


# ── 도메인 추론용 키워드 맵 (Router fallback) ──
DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "maintenance_contract": [
        "계약", "유지보수", "만료", "갱신", "연장",
        "영업담당", "영업 담당", "담당자",
    ],
    "checkup": ["점검", "체크", "checkup", "정기"],
    "server": ["서버", "server", "호스트"],
    "salesforce": ["salesforce", "SF", "거래처", "세일즈포스", "영업기회", "opportunity"],
    "customer": ["고객", "고객사", "customer"],
    "project_issue": ["이슈", "프로젝트", "project", "issue"],
    "request_job": ["업무요청", "업무 요청", "작업요청"],
    "product_license": ["제품", "라이선스", "license", "product"],
    "notification": ["알림", "메일", "이메일", "notify"],
    "epic_label_comment": ["에픽", "마일스톤", "라벨", "댓글"],
}
