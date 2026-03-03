"""
Proactive Agent — 자율 행동 실행 엔진

매일 아침 브리핑, 계약 만료 알림, 미완료 점검 리마인더, 주간 정합성 점검.
bot_brain.py의 run_loop() / process_messages()에서 호출된다.
"""

import os
import json
import requests
from datetime import datetime, timedelta

from proactive_config import (
    PROACTIVE_ENABLED, PROACTIVE_DRY_RUN,
    PROACTIVE_BRIEFING_ENABLED, PROACTIVE_BRIEFING_HOUR, PROACTIVE_BRIEFING_MINUTE,
    PROACTIVE_WEEKLY_ENABLED, PROACTIVE_WEEKLY_DAY, PROACTIVE_WEEKLY_HOUR, PROACTIVE_WEEKLY_MINUTE,
    PROACTIVE_CONTRACT_ALERT_ENABLED, CONTRACT_ALERT_DAYS,
    PROACTIVE_OVERDUE_ENABLED, OVERDUE_ESCALATION_DAYS,
    PROACTIVE_TOLERANCE_MINUTES,
    STACK_API_URL, STACK_API_KEY, STACK_API_TIMEOUT,
    BOT_NAME,
)
from proactive_tracker import (
    is_already_sent, mark_sent, cleanup_old_alerts,
    get_all_user_spaces, get_space_by_username,
    sync_user_spaces_from_messages,
)

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(_BASE_DIR, "bot_brain.log")
WORKING_LOCK_FILE = os.path.join(_BASE_DIR, "working.json")
UUID_MAP_FILE = os.path.join(_BASE_DIR, "uuid_name_map.json")
UUID_MAP_MAX_AGE_DAYS = 7  # 매핑 캐시 유효기간

# 요일 한글 매핑
_WEEKDAY_KR = ["월", "화", "수", "목", "금", "토", "일"]


def _log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [proactive] {msg}\n")
            f.flush()
    except Exception:
        pass


def _stack_api(method, path, params=None):
    """STACK REST API 호출 (읽기 전용)"""
    url = f"{STACK_API_URL}{path}"
    headers = {"X-API-Key": STACK_API_KEY, "Content-Type": "application/json"}
    try:
        if method == "GET":
            r = requests.get(url, headers=headers, params=params, timeout=STACK_API_TIMEOUT)
        else:
            return {"error": f"Proactive agent only supports GET, got {method}"}
        if r.status_code >= 400:
            return {"error": f"HTTP {r.status_code}: {r.text[:300]}"}
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def _send_proactive_message(space_name, text):
    """
    Proactive 메시지 전송.
    send_message_sync() 대신 _send_message_impl() 직접 사용하여
    working lock 부수효과를 방지한다.
    """
    prefix = "[DRY-RUN] " if PROACTIVE_DRY_RUN else ""

    if PROACTIVE_DRY_RUN:
        _log(f"{prefix}메시지 → {space_name}: {text[:100]}...")
        return True

    try:
        from gchat_sender import _send_message_impl
        result = _send_message_impl(space_name, text)
        if result:
            _log(f"메시지 전송 성공 → {space_name}")
        else:
            _log(f"메시지 전송 실패 → {space_name}")
        return result
    except Exception as e:
        _log(f"메시지 전송 오류: {e}")
        return False


# ─── 스케줄 체크 ───

def _should_run_task(task_name, now=None):
    """특정 작업을 지금 실행해야 하는지 확인 (스케줄 + 멱등성)"""
    if now is None:
        now = datetime.now()

    tolerance = timedelta(minutes=PROACTIVE_TOLERANCE_MINUTES)

    if task_name == "briefing":
        if not PROACTIVE_BRIEFING_ENABLED:
            return False
        target = now.replace(hour=PROACTIVE_BRIEFING_HOUR, minute=PROACTIVE_BRIEFING_MINUTE, second=0, microsecond=0)
        in_window = abs(now - target) <= tolerance
        today_key = now.strftime("%Y-%m-%d")
        return in_window and not is_already_sent("briefing", today_key)

    elif task_name == "contract_alert":
        if not PROACTIVE_CONTRACT_ALERT_ENABLED:
            return False
        # 계약 만료 알림은 시간과 무관, 매 실행마다 체크 (멱등성은 계약별로)
        return True

    elif task_name == "overdue_reminder":
        if not PROACTIVE_OVERDUE_ENABLED:
            return False
        return True

    elif task_name == "weekly_check":
        if not PROACTIVE_WEEKLY_ENABLED:
            return False
        if now.weekday() != PROACTIVE_WEEKLY_DAY:
            return False
        target = now.replace(hour=PROACTIVE_WEEKLY_HOUR, minute=PROACTIVE_WEEKLY_MINUTE, second=0, microsecond=0)
        in_window = abs(now - target) <= tolerance
        week_key = now.strftime("%Y-W%W")
        return in_window and not is_already_sent("weekly_check", week_key)

    return False


# ─── 데이터 수집 (1회 호출, 여러 기능에서 공유) ───

def _fetch_shared_data():
    """공유 데이터 1회 수집"""
    data = {}

    # 만료 임박 계약
    data["expiring"] = _stack_api("GET", "/api/maintenance-contracts/expiring")

    # 이번 달 점검
    data["current_checkups"] = _stack_api("GET", "/api/maintenance/issues/current-month")

    # 미완료 점검 (pending API는 assigneeId 필수 → list로 대체)
    data["pending_checkups"] = _stack_api("GET", "/api/maintenance/issues",
                                          params={"status": "OPEN", "size": 200})

    # 7일 내 예정 점검
    data["upcoming"] = _stack_api("GET", "/api/maintenance/issues/upcoming")

    # 계약 목록 (customerName + 담당자 해석용 — expiring API는 이 정보 미포함)
    contracts = _stack_api("GET", "/api/maintenance-contracts",
                           params={"status": "ACTIVE", "size": 200})
    customer_map = {}          # customerId → customerName
    contract_personnel = {}    # contractId → {"salesManagerId", "engineerIds": set()}
    for item in _extract_items(contracts):
        contract = item.get("contract", item)
        cid = contract.get("customerId", "")
        cname = item.get("customerName", "")
        if cid and cname:
            customer_map[cid] = cname
        # 계약별 담당자 정보
        contract_id = contract.get("id", "")
        if contract_id:
            eng_ids = set()
            for proj in item.get("projects", []):
                eid = proj.get("engineerId", "")
                if eid:
                    eng_ids.add(eid)
            contract_personnel[contract_id] = {
                "salesManagerId": contract.get("salesManagerId", ""),
                "engineerIds": eng_ids,
            }
    data["customer_map"] = customer_map
    data["contract_personnel"] = contract_personnel

    return data


def _extract_items(api_result):
    """API 결과에서 아이템 리스트 추출"""
    if not api_result or isinstance(api_result, dict) and api_result.get("error"):
        return []
    if isinstance(api_result, list):
        return api_result
    if isinstance(api_result, dict):
        data = api_result.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("items", [])
    return []


def _get_customer_name(item, customer_map=None):
    """
    아이템에서 고객명 추출.
    점검 이슈: project.customerName
    계약: customerName 또는 customer_map[customerId]
    """
    # 직접 필드
    for key in ["customerName"]:
        val = item.get(key)
        if val:
            return val
    # project 내부 (점검 이슈)
    proj = item.get("project", {})
    if isinstance(proj, dict):
        val = proj.get("customerName") or proj.get("name", "")
        if val:
            return val
    # customer_map으로 해석 (만료 계약)
    if customer_map:
        contract = item.get("contract", item)
        cid = contract.get("customerId", "") if isinstance(contract, dict) else ""
        if not cid:
            cid = item.get("customerId", "")
        if cid and cid in customer_map:
            return customer_map[cid]
    return ""


def _get_engineer_name(item):
    """아이템에서 엔지니어명 추출"""
    for key in ["engineerName", "assigneeName", "assignee"]:
        val = item.get(key)
        if val:
            return val
    # projects 내부 확인
    for proj in item.get("projects", []):
        val = proj.get("engineerName")
        if val:
            return val
    return ""


def _get_sales_name(item):
    """아이템에서 영업담당자명 추출"""
    for key in ["salesManagerName", "salesManager"]:
        val = item.get(key)
        if val:
            return val
    return ""


def _matches_user(name_from_api, username, display_name):
    """
    STACK API에서 반환된 이름이 사용자와 일치하는지 확인.

    STACK API는 한글 이름("최재형") 또는 username("jhchoi")을 반환할 수 있으므로
    양쪽 모두 비교한다. 부분 매칭이 아닌 완전 매칭 사용.

    Args:
        name_from_api: STACK API에서 반환된 이름 (한글 또는 영문)
        username: 사용자 email prefix (예: "jhchoi")
        display_name: 사용자 표시 이름 (예: "최재형")
    """
    if not name_from_api:
        return False
    api_lower = name_from_api.strip().lower()
    # 1. username 완전 매칭 (영문)
    if username and api_lower == username.lower():
        return True
    # 2. display_name 완전 매칭 (한글)
    if display_name and api_lower == display_name.strip().lower():
        return True
    # 3. display_name이 API 이름에 포함 (예: "최재형" in "최재형 (엔지니어)")
    if display_name and display_name.strip().lower() in api_lower:
        return True
    return False


# ─── UUID→이름 매핑 (1회 구축, 캐시) ───

def _load_uuid_map():
    """캐시된 UUID→이름 매핑 로드. 유효기간 초과 시 빈 dict 반환."""
    if not os.path.exists(UUID_MAP_FILE):
        return {}
    try:
        with open(UUID_MAP_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        updated = data.get("_updated", "")
        if updated:
            updated_dt = datetime.strptime(updated, "%Y-%m-%d")
            if (datetime.now() - updated_dt).days > UUID_MAP_MAX_AGE_DAYS:
                return {}
        return data.get("map", {})
    except Exception:
        return {}


def _save_uuid_map(uuid_map):
    """UUID→이름 매핑 저장."""
    data = {
        "_updated": datetime.now().strftime("%Y-%m-%d"),
        "map": uuid_map,
    }
    try:
        with open(UUID_MAP_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        _log(f"UUID 매핑 저장 오류: {e}")


def _build_uuid_map():
    """
    UUID→이름 매핑 구축 (2단계).
    1단계: 계약 상세 API → salesManagerId/engineerId 수집
    2단계: 점검 이슈의 projectId → 프로젝트 멤버 수집
    캐시가 유효하면 파일에서 로드 (API 호출 0).
    """
    existing = _load_uuid_map()
    if existing:
        return existing

    _log("UUID→이름 매핑 구축 시작")
    uuid_map = {}

    # 1단계: 계약 상세에서 영업/엔지니어 수집
    contracts = _stack_api("GET", "/api/maintenance-contracts",
                           params={"status": "ACTIVE", "size": 200})
    items = _extract_items(contracts)

    checked = 0
    max_checks = 50
    for item in items:
        if checked >= max_checks:
            break
        contract = item.get("contract", item)
        cid = contract.get("id", "")
        if not cid:
            continue
        checked += 1

        detail = _stack_api("GET", f"/api/maintenance-contracts/{cid}/detail")
        d = detail.get("data", {})

        sm_id = d.get("contract", {}).get("salesManagerId", "")
        sm_name = d.get("salesManagerName", "")
        if sm_id and sm_name:
            uuid_map[sm_id] = sm_name

        for proj in d.get("projects", []):
            eid = proj.get("engineerId", "")
            ename = proj.get("engineerName", "")
            if eid and ename:
                uuid_map[eid] = ename

    _log(f"1단계 완료: 계약 {checked}개 → {len(uuid_map)}명")

    # 2단계: 점검 이슈의 프로젝트 멤버에서 추가 수집
    # (계약 상세에는 없지만 프로젝트 멤버로 배정된 엔지니어 포함)
    current = _stack_api("GET", "/api/maintenance/issues/current-month")
    pending = _stack_api("GET", "/api/maintenance/issues",
                         params={"status": "OPEN", "size": 200})

    project_ids = set()
    for item in _extract_items(current) + _extract_items(pending):
        aid = item.get("assigneeId", "")
        pid = item.get("projectId", "")
        # 이미 매핑된 UUID는 스킵, 프로젝트가 있는 미매핑만 수집
        if aid and aid not in uuid_map and pid:
            project_ids.add(pid)

    proj_checked = 0
    for pid in project_ids:
        proj_checked += 1
        proj_data = _stack_api("GET", f"/api/projects/{pid}")
        proj = proj_data.get("data", proj_data)
        for member in proj.get("members", []):
            uid = member.get("userId", "")
            dname = member.get("displayName", "")
            if uid and dname and uid not in uuid_map:
                uuid_map[uid] = dname

    _save_uuid_map(uuid_map)
    _log(f"UUID→이름 매핑 구축 완료: {len(uuid_map)}명 (계약 {checked}개 + 프로젝트 {proj_checked}개)")
    return uuid_map


def _find_user_uuid(uuid_map, username, display_name):
    """UUID 매핑에서 사용자의 UUID를 찾는다."""
    for uid, name in uuid_map.items():
        if _matches_user(name, username, display_name):
            return uid
    return None


# ─── 아침 브리핑 ───

def _morning_briefing(now, shared_data=None):
    """매일 아침 개인화 브리핑 전송"""
    today_key = now.strftime("%Y-%m-%d")
    if is_already_sent("briefing", today_key):
        return

    _log("아침 브리핑 시작")

    if shared_data is None:
        shared_data = _fetch_shared_data()

    users = get_all_user_spaces()
    if not users:
        sync_user_spaces_from_messages()
        users = get_all_user_spaces()

    if not users:
        _log("사용자-Space 매핑 없음 → 브리핑 스킵")
        return

    # UUID→이름 매핑 (캐시, 주 1회 갱신)
    uuid_map = _build_uuid_map()

    weekday = _WEEKDAY_KR[now.weekday()]
    date_str = now.strftime("%Y-%m-%d")

    recipients = []

    for email, user_info in users.items():
        username = user_info.get("username", "")
        display_name = user_info.get("display_name", username)
        space_name = user_info.get("space_name", "")

        if not space_name:
            continue

        # UUID 기반 필터링 (assigneeId / salesManagerId 매칭)
        user_uuid = _find_user_uuid(uuid_map, username, display_name)
        if not user_uuid:
            _log(f"UUID 미발견: {username}/{display_name} → 전체 데이터 표시")

        my_checkups = []
        for item in _extract_items(shared_data.get("current_checkups")):
            if item.get("status") in ("DONE", "COMPLETED", "CLOSED"):
                continue
            if user_uuid:
                if item.get("assigneeId") == user_uuid:
                    my_checkups.append(item)
            else:
                my_checkups.append(item)

        my_expiring = []
        contract_personnel = shared_data.get("contract_personnel", {})
        for item in _extract_items(shared_data.get("expiring")):
            contract = item.get("contract", item)
            cid = contract.get("id", item.get("id", ""))
            if user_uuid:
                # salesManagerId 직접 확인 (flat 구조)
                if contract.get("salesManagerId", item.get("salesManagerId", "")) == user_uuid:
                    my_expiring.append(item)
                # contracts list에서 가져온 담당자 정보로 엔지니어 확인
                elif cid in contract_personnel:
                    personnel = contract_personnel[cid]
                    if user_uuid == personnel.get("salesManagerId") or user_uuid in personnel.get("engineerIds", set()):
                        my_expiring.append(item)
            else:
                my_expiring.append(item)

        my_pending = []
        for item in _extract_items(shared_data.get("pending_checkups")):
            if user_uuid:
                if item.get("assigneeId") == user_uuid:
                    my_pending.append(item)
            else:
                my_pending.append(item)

        # 브리핑 구성
        customer_map = shared_data.get("customer_map", {})
        lines = [f"📋 좋은 아침입니다, {display_name}님! ({date_str} {weekday})\n"]

        if my_checkups:
            lines.append(f"🔧 이번 달 점검 ({len(my_checkups)}건)")
            for i, item in enumerate(my_checkups[:10], 1):
                customer = _get_customer_name(item, customer_map)
                summary = item.get("summary") or item.get("title") or ""
                due_date = item.get("dueDate", "")
                due_str = f" (마감: {due_date[:10]})" if due_date else ""
                # summary에 고객명이 이미 포함되면 summary만 사용
                if customer and summary and summary.startswith(customer):
                    lines.append(f"  {i}. {summary}{due_str}")
                else:
                    label = f"{customer} {summary}".strip() if customer else summary
                    lines.append(f"  {i}. {label}{due_str}")
            lines.append("")

        if my_expiring:
            lines.append(f"⚠️ 만료 임박 계약 ({len(my_expiring)}건)")
            for i, item in enumerate(my_expiring[:10], 1):
                customer = _get_customer_name(item, customer_map)
                contract = item.get("contract", item)
                end_date = contract.get("contractEndDate", item.get("contractEndDate", ""))
                if end_date:
                    try:
                        end_dt = datetime.strptime(end_date[:10], "%Y-%m-%d")
                        d_day = (end_dt - now.replace(hour=0, minute=0, second=0, microsecond=0)).days
                        lines.append(f"  {i}. {customer} - D-{d_day} ({end_date[:10]})")
                    except ValueError:
                        lines.append(f"  {i}. {customer} ({end_date[:10]})")
                else:
                    lines.append(f"  {i}. {customer}")
            lines.append("")

        if my_pending:
            lines.append(f"📌 미완료 점검 ({len(my_pending)}건)")
            for i, item in enumerate(my_pending[:10], 1):
                customer = _get_customer_name(item, customer_map)
                summary = item.get("summary") or item.get("title") or ""
                due_date = item.get("dueDate", "")
                # summary에 고객명 포함 시 중복 방지
                if customer and summary and summary.startswith(customer):
                    label = summary
                else:
                    label = f"{customer} {summary}".strip() if customer else summary
                if due_date:
                    try:
                        due_dt = datetime.strptime(due_date[:10], "%Y-%m-%d")
                        overdue_days = (now.replace(hour=0, minute=0, second=0, microsecond=0) - due_dt).days
                        if overdue_days > 0:
                            lines.append(f"  {i}. {label} (마감 +{overdue_days}일 초과)")
                        else:
                            lines.append(f"  {i}. {label} (마감: {due_date[:10]})")
                    except ValueError:
                        lines.append(f"  {i}. {label}")
                else:
                    lines.append(f"  {i}. {label}")
            lines.append("")

        # 내용이 인사말뿐이면 "할 일 없음" 메시지 추가
        if not my_checkups and not my_expiring and not my_pending:
            lines.append("✅ 오늘은 예정된 점검/알림이 없습니다.")
            lines.append("")

        lines.append("좋은 하루 되세요!")

        message = "\n".join(lines)
        if _send_proactive_message(space_name, message):
            recipients.append(email)

    mark_sent("briefing", today_key, recipients)
    _log(f"아침 브리핑 완료 → {len(recipients)}명")


# ─── 계약 만료 알림 ───

def _contract_expiration_alerts(now, shared_data=None):
    """계약 만료 D-30/D-7/D-1 알림"""
    _log("계약 만료 알림 체크")

    if shared_data is None:
        shared_data = _fetch_shared_data()

    expiring_items = _extract_items(shared_data.get("expiring"))
    if not expiring_items:
        _log("만료 임박 계약 없음")
        return

    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    customer_map = shared_data.get("customer_map", {})

    for item in expiring_items:
        contract = item.get("contract", item)
        contract_id = contract.get("id", item.get("id", ""))
        customer_name = _get_customer_name(item, customer_map)
        end_date_str = contract.get("contractEndDate", item.get("contractEndDate", ""))

        if not end_date_str or not contract_id:
            continue

        try:
            end_date = datetime.strptime(end_date_str[:10], "%Y-%m-%d")
        except ValueError:
            continue

        d_days = (end_date - today).days

        # 어떤 티어에 해당하는지 확인
        for alert_day in CONTRACT_ALERT_DAYS:
            if d_days == alert_day:
                alert_key = f"contract_{contract_id}_D-{alert_day}"
                if is_already_sent("contract_alert", alert_key):
                    continue

                # UUID 매핑에서 담당자 이름 해석
                uuid_map = _build_uuid_map()
                contract_personnel = shared_data.get("contract_personnel", {})
                personnel = contract_personnel.get(contract_id, {})

                sm_id = contract.get("salesManagerId", item.get("salesManagerId", ""))
                sales = uuid_map.get(sm_id, "")
                # expiring API는 projects가 없으므로 contracts list에서 가져온 정보 사용
                engineer_ids = list(personnel.get("engineerIds", set()))
                engineers = [uuid_map.get(eid, "") for eid in engineer_ids if eid and eid in uuid_map]
                engineer = engineers[0] if engineers else ""

                cycle = contract.get("checkupCycle", item.get("checkupCycle", ""))
                cycle_kr = {"MONTHLY": "월간", "QUARTERLY": "분기", "SEMI_ANNUALLY": "반기",
                            "ANNUALLY": "연간", "REQUEST": "요청시", "PARTNER": "파트너"}.get(cycle, cycle)

                message = f"""⚠️ 계약 만료 {alert_day}일 전 알림

📄 {customer_name} 유지보수 계약
- 종료일: {end_date_str[:10]}
- 점검 주기: {cycle_kr}"""

                if sales:
                    message += f"\n- 영업: {sales}"
                if engineer:
                    message += f"\n- 엔지니어: {engineer}"

                message += "\n\n갱신 확인이 필요합니다."

                recipients = []
                all_users = get_all_user_spaces()

                # UUID로 관련 담당자 찾아서 알림
                target_uuids = set()
                if sm_id:
                    target_uuids.add(sm_id)
                target_uuids.update(eid for eid in engineer_ids if eid)

                for email_addr, info in all_users.items():
                    uname = info.get("username", "")
                    dname = info.get("display_name", "")
                    user_uid = _find_user_uuid(uuid_map, uname, dname)
                    if user_uid and user_uid in target_uuids and info.get("space_name"):
                        if _send_proactive_message(info["space_name"], message):
                            recipients.append(email_addr)

                # 매핑된 사용자가 없으면 모든 등록 사용자에게
                if not recipients:
                    for email_addr, info in all_users.items():
                        if info.get("space_name"):
                            if _send_proactive_message(info["space_name"], message):
                                recipients.append(email_addr)

                mark_sent("contract_alert", alert_key, recipients)
                _log(f"계약 만료 알림: {customer_name} D-{alert_day} → {recipients}")


# ─── 미완료 점검 리마인더 ───

def _overdue_checkup_reminders(now, shared_data=None):
    """미완료 점검 Day+1, +3, +7 리마인더"""
    _log("미완료 점검 리마인더 체크")

    if shared_data is None:
        shared_data = _fetch_shared_data()

    pending_items = _extract_items(shared_data.get("pending_checkups"))
    if not pending_items:
        _log("미완료 점검 없음")
        return

    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    customer_map = shared_data.get("customer_map", {})

    for item in pending_items:
        issue_id = item.get("id", item.get("issueId", ""))
        customer_name = _get_customer_name(item, customer_map)
        summary = item.get("summary", item.get("title", ""))
        due_date_str = item.get("dueDate", "")
        assignee_id = item.get("assigneeId", "")

        if not due_date_str or not issue_id:
            continue

        try:
            due_date = datetime.strptime(due_date_str[:10], "%Y-%m-%d")
        except ValueError:
            continue

        overdue_days = (today - due_date).days
        if overdue_days <= 0:
            continue

        for escalation_day in OVERDUE_ESCALATION_DAYS:
            if overdue_days >= escalation_day:
                alert_key = f"issue_{issue_id}_D+{escalation_day}"
                if is_already_sent("overdue_reminder", alert_key):
                    continue

                # UUID 매핑에서 담당자 이름 해석
                uuid_map = _build_uuid_map()
                engineer = uuid_map.get(assignee_id, "")

                # 에스컬레이션 수준
                if escalation_day >= 7:
                    urgency = "🚨 긴급"
                    target_note = "(매니저 에스컬레이션)"
                elif escalation_day >= 3:
                    urgency = "⚠️ 주의"
                    target_note = "(팀장 알림)"
                else:
                    urgency = "📌 알림"
                    target_note = ""

                message = f"""{urgency} 미완료 점검 리마인더 {target_note}

🔧 {customer_name} - {summary}
- 마감일: {due_date_str[:10]} ({overdue_days}일 초과)"""

                if engineer:
                    message += f"\n- 담당: {engineer}"

                message += "\n\n점검 완료 처리가 필요합니다."

                recipients = []
                all_users = get_all_user_spaces()

                # assigneeId로 담당 엔지니어 찾기
                if assignee_id:
                    for email_addr, info in all_users.items():
                        uname = info.get("username", "")
                        dname = info.get("display_name", "")
                        user_uid = _find_user_uuid(uuid_map, uname, dname)
                        if user_uid == assignee_id and info.get("space_name"):
                            if _send_proactive_message(info["space_name"], message):
                                recipients.append(email_addr)

                if not recipients:
                    for email_addr, info in all_users.items():
                        if info.get("space_name"):
                            if _send_proactive_message(info["space_name"], message):
                                recipients.append(email_addr)

                mark_sent("overdue_reminder", alert_key, recipients)
                _log(f"미완료 리마인더: {customer_name} D+{escalation_day} → {recipients}")


# ─── 주간 데이터 정합성 점검 ───

def _weekly_integrity_check(now):
    """매주 월요일 데이터 정합성 점검"""
    week_key = now.strftime("%Y-W%W")
    if is_already_sent("weekly_check", week_key):
        return

    _log("주간 정합성 점검 시작")

    issues = []

    # 1. 활성 계약인데 점검 이슈 없음
    contracts_result = _stack_api("GET", "/api/maintenance-contracts", params={"status": "ACTIVE", "size": 200})
    contracts = _extract_items(contracts_result)

    # API 호출 제한: 최대 30개 계약만 점검 이슈 확인 (성능 보호)
    checked_count = 0
    max_contract_checks = 30

    for item in contracts:
        contract = item.get("contract", item)
        contract_id = contract.get("id", "")
        customer = item.get("customerName", "")
        cycle = contract.get("checkupCycle", "")

        if not contract_id or cycle in ("REQUEST", "PARTNER", ""):
            continue

        if checked_count >= max_contract_checks:
            _log(f"주간 점검: 계약 {max_contract_checks}개 확인 후 중단 (전체 {len(contracts)}개)")
            break
        checked_count += 1

        # 해당 계약의 점검 이슈 확인
        contract_issues = _stack_api("GET", f"/api/maintenance-contracts/{contract_id}/issues")
        contract_issue_list = _extract_items(contract_issues)

        if not contract_issue_list:
            issues.append(f"❌ {customer}: 활성 계약이나 점검 이슈 없음 (주기: {cycle})")

    # 2. 만료일 지났는데 ACTIVE 상태
    for item in contracts:
        contract = item.get("contract", item)
        end_date_str = contract.get("contractEndDate", "")
        status = contract.get("status", "")
        customer = item.get("customerName", "")

        if status == "ACTIVE" and end_date_str:
            try:
                end_date = datetime.strptime(end_date_str[:10], "%Y-%m-%d")
                if end_date < now.replace(hour=0, minute=0, second=0, microsecond=0):
                    issues.append(f"⚠️ {customer}: 만료({end_date_str[:10]})되었으나 상태가 ACTIVE")
            except ValueError:
                pass

    # 3. 담당자 미배정 점검 (이번 달 + 미완료만)
    current_issues = _stack_api("GET", "/api/maintenance/issues/current-month")
    pending_issues = _stack_api("GET", "/api/maintenance/issues",
                                params={"status": "OPEN", "size": 200})
    seen_ids = set()
    for item in _extract_items(current_issues) + _extract_items(pending_issues):
        item_id = item.get("id", item.get("issueId", ""))
        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)
        status = item.get("status", "")
        if status in ("COMPLETED", "CLOSED"):
            continue
        engineer = _get_engineer_name(item)
        if not engineer:
            customer = _get_customer_name(item)
            summary = item.get("summary", item.get("title", ""))
            issues.append(f"👤 {customer} - {summary}: 담당자 미배정")

    # 결과 전송
    if issues:
        message = f"📊 주간 데이터 정합성 점검 결과 ({now.strftime('%Y-%m-%d')})\n\n"
        message += f"발견된 이슈: {len(issues)}건\n\n"
        for issue in issues[:20]:  # 최대 20건
            message += f"  {issue}\n"
        if len(issues) > 20:
            message += f"\n  ... 외 {len(issues) - 20}건"
        message += "\n\n확인 후 조치가 필요합니다."
    else:
        message = f"✅ 주간 데이터 정합성 점검 완료 ({now.strftime('%Y-%m-%d')})\n\n모든 데이터가 정상입니다."

    recipients = []
    all_users = get_all_user_spaces()
    for email, info in all_users.items():
        if info.get("space_name"):
            if _send_proactive_message(info["space_name"], message):
                recipients.append(email)

    mark_sent("weekly_check", week_key, recipients)
    _log(f"주간 정합성 점검 완료 → 이슈 {len(issues)}건, 수신 {len(recipients)}명")


# ─── 메인 실행 함수 ───

def run_proactive_checks(force=False):
    """
    자율 행동 실행 엔진. bot_brain.py에서 호출.

    Args:
        force: True이면 스케줄 무시하고 강제 실행
    """
    if not PROACTIVE_ENABLED and not force:
        return

    # working.json 존재 시 스킵 (사용자 요청 처리 중)
    if os.path.exists(WORKING_LOCK_FILE) and not force:
        _log("working lock 존재 → proactive 스킵")
        return

    now = datetime.now()
    _log(f"proactive 체크 시작 ({now.strftime('%H:%M')})")

    # 오래된 알림 기록 정리 (60일)
    try:
        cleanup_old_alerts()
    except Exception:
        pass

    # 공유 데이터 1회 수집
    shared_data = None
    needs_data = (
        (force or _should_run_task("briefing", now)) or
        (force or _should_run_task("contract_alert", now)) or
        (force or _should_run_task("overdue_reminder", now))
    )

    if needs_data:
        try:
            shared_data = _fetch_shared_data()
        except Exception as e:
            _log(f"공유 데이터 수집 실패: {e}")
            return

    # 아침 브리핑
    if force or _should_run_task("briefing", now):
        try:
            _morning_briefing(now, shared_data)
        except Exception as e:
            _log(f"아침 브리핑 오류: {e}")

    # 계약 만료 알림
    if force or _should_run_task("contract_alert", now):
        try:
            _contract_expiration_alerts(now, shared_data)
        except Exception as e:
            _log(f"계약 만료 알림 오류: {e}")

    # 미완료 점검 리마인더
    if force or _should_run_task("overdue_reminder", now):
        try:
            _overdue_checkup_reminders(now, shared_data)
        except Exception as e:
            _log(f"미완료 리마인더 오류: {e}")

    # 주간 정합성 점검
    if force or _should_run_task("weekly_check", now):
        try:
            _weekly_integrity_check(now)
        except Exception as e:
            _log(f"주간 정합성 점검 오류: {e}")

    _log("proactive 체크 완료")
