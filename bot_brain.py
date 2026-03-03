#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
비서최재형 - OpenAI API 기반 자율 처리 엔진
Google Chat 메시지를 받아 OpenAI로 처리하고 결과를 회신한다.
"""

import os
import sys

# ─── stdout/stderr를 OS 레벨 + Python 레벨 모두 devnull로 리다이렉트 ───
# C 라이브러리(SSL, httpx 등)가 fd 1/2에 직접 쓰기 때문에
# Python의 sys.stdout만 바꾸면 부족. os.dup2로 fd 자체를 교체해야 함.
try:
    _devnull_fd = os.open(os.devnull, os.O_WRONLY)
    os.dup2(_devnull_fd, 1)  # fd 1 = stdout → devnull
    os.dup2(_devnull_fd, 2)  # fd 2 = stderr → devnull
    os.close(_devnull_fd)
except OSError:
    pass
# Python 레벨도 리다이렉트 (print() 등)
_devnull_py = open(os.devnull, "w", encoding="utf-8")
sys.stdout = _devnull_py
sys.stderr = _devnull_py

import json
import requests
import threading
from datetime import datetime
from dotenv import load_dotenv

# 프로젝트 루트 설정
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

LOG_FILE = os.path.join(BASE_DIR, "bot_brain.log")

def log(msg):
    """로그 메시지를 bot_brain.log에 직접 기록 (flush 즉시)"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}\n"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
    except Exception:
        pass

os.chdir(BASE_DIR)
load_dotenv()

from openai import OpenAI
from chat_bot import (
    check_chat, combine_tasks, create_working_lock, remove_working_lock,
    reserve_memory_chat, report_chat, mark_done_chat, load_memory,
    get_task_dir, search_memory
)
from gchat_sender import send_message_sync, _send_message_impl

# Proactive Agent (선택적 로드)
_PROACTIVE_AVAILABLE = False
try:
    from proactive_agent import run_proactive_checks
    _PROACTIVE_AVAILABLE = True
except Exception:
    pass

# ─── 사용자 UUID 매핑 ───
UUID_MAP_FILE = os.path.join(BASE_DIR, "uuid_name_map.json")

def _lookup_user_identity(sender_email, user_name):
    """
    sender_email과 user_name으로 uuid_name_map.json에서 UUID를 조회한다.

    Args:
        sender_email: 사용자 이메일 (예: "jhchoi@rsupport.com")
        user_name: 사용자 표시 이름 (예: "최재형")

    Returns:
        dict: {"uuid": "...", "name": "...", "email": "..."} 또는 None
    """
    if not sender_email and not user_name:
        return None

    try:
        if not os.path.exists(UUID_MAP_FILE):
            log(f"[identity] uuid_name_map.json 없음")
            return None

        with open(UUID_MAP_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        uuid_map = data.get("map", {})
        if not uuid_map:
            return None

        # 1차: user_name(표시 이름)으로 완전 매칭
        if user_name:
            for uid, name in uuid_map.items():
                if name.strip() == user_name.strip():
                    log(f"[identity] 사용자 확인: {user_name} → {uid}")
                    return {"uuid": uid, "name": name, "email": sender_email}

        # 2차: email prefix로 부분 매칭 (STACK username = email prefix 관례)
        if sender_email and "@" in sender_email:
            username = sender_email.split("@")[0].lower()
            # username이 이름에 포함되거나 이름이 username에 포함되는 경우는 매칭하지 않음
            # 정확한 매칭만 수행 (1차에서 이미 시도)
            pass

        log(f"[identity] UUID 매핑 실패: email={sender_email}, name={user_name}")
        return None

    except Exception as e:
        log(f"[identity] UUID 조회 오류: {e}")
        return None

# ─── 설정 ───
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
STACK_API_URL = os.getenv("STACK_API_URL", "")
STACK_API_KEY = os.getenv("STACK_API_KEY", "")
BOT_NAME = os.getenv("BOT_NAME", "AI비서")

OPENAI_TIMEOUT = int(os.getenv("OPENAI_TIMEOUT", "60"))
OPENAI_MAX_TOKENS = int(os.getenv("OPENAI_MAX_TOKENS", "4096"))
STACK_API_TIMEOUT = int(os.getenv("STACK_API_TIMEOUT", "15"))
MAX_TOOL_TURNS = int(os.getenv("MAX_TOOL_TURNS", "10"))
TRUNCATE_MAX_LEN = int(os.getenv("TRUNCATE_MAX_LEN", "8000"))
BOT_LOOP_INTERVAL = int(os.getenv("BOT_LOOP_INTERVAL", "5"))
BOT_IDLE_TIMEOUT = int(os.getenv("BOT_IDLE_TIMEOUT", "600"))  # C: 10분 idle → 스케줄러 5분 간격과 겹침 방지

# ─── Reflection (결과 검증) 설정 ───
REFLECTION_ENABLED = os.getenv("REFLECTION_ENABLED", "true").lower() == "true"
REFLECTION_MODEL = os.getenv("REFLECTION_MODEL", "gpt-4o-mini")  # 검증은 경량 모델로 (속도 우선)
FAST_MODEL = os.getenv("FAST_MODEL", "gpt-4o-mini")  # B: 단순 질문용 경량 모델

# ─── Agent Planning (자율 사고) 설정 ───
AGENT_PLANNING_ENABLED = os.getenv("AGENT_PLANNING_ENABLED", "true").lower() == "true"
COMPLEXITY_THRESHOLD_COMPLEX = int(os.getenv("COMPLEXITY_THRESHOLD_COMPLEX", "5"))
AGENT_MODEL = os.getenv("AGENT_MODEL", "gpt-4o-mini")  # 복잡도 평가 + 계획 생성용

# ─── LangGraph Agent (Feature Flag) ───
AGENT_GRAPH_ENABLED = os.getenv("AGENT_GRAPH_ENABLED", "false").lower() == "true"

client = OpenAI(api_key=OPENAI_API_KEY, timeout=float(OPENAI_TIMEOUT))

# ─── UUID → 이름 변환 ───
_uuid_name_cache = {}
_uuid_name_cache_ts = 0

def _load_uuid_name_map():
    """uuid_name_map.json + list_user_names API에서 UUID→이름 매핑 로드 (5분 캐시)"""
    global _uuid_name_cache, _uuid_name_cache_ts
    import time as _t
    if _uuid_name_cache and (_t.time() - _uuid_name_cache_ts) < 300:
        return _uuid_name_cache
    m = {}
    try:
        if os.path.exists(UUID_MAP_FILE):
            with open(UUID_MAP_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            m.update(data.get("map", {}))
    except Exception:
        pass
    _uuid_name_cache = m
    _uuid_name_cache_ts = _t.time()
    return m

def _resolve_uuids_in_result(result):
    """도구 결과 내 UUID 필드들을 사람 이름으로 치환"""
    name_map = _load_uuid_name_map()
    if not name_map:
        return result

    UUID_FIELDS = {
        "salesManagerId": "salesManagerName",
        "engineerId": "engineerName",
        "assigneeId": "assigneeName",
        "managerId": "managerName",
        "creatorId": "creatorName",
        "customerId": "customerName",
    }

    def _resolve_item(item):
        if not isinstance(item, dict):
            return
        for uuid_key, name_key in UUID_FIELDS.items():
            uid = item.get(uuid_key)
            if uid and uid in name_map and not item.get(name_key):
                item[name_key] = name_map[uid]
        # contract 내부도 처리
        contract = item.get("contract")
        if isinstance(contract, dict):
            _resolve_item(contract)
        # projects 내부도 처리
        for proj in item.get("projects", []):
            _resolve_item(proj)

    def _walk(data):
        if isinstance(data, list):
            for item in data:
                _walk(item)
        elif isinstance(data, dict):
            _resolve_item(data)
            for v in data.values():
                if isinstance(v, (list, dict)):
                    _walk(v)

    _walk(result)
    return result


# ─── STACK API 호출 ───
def stack_api(method, path, params=None, body=None, timeout=None):
    """STACK REST API 호출"""
    url = f"{STACK_API_URL}{path}"
    headers = {"X-API-Key": STACK_API_KEY, "Content-Type": "application/json"}
    req_timeout = timeout or STACK_API_TIMEOUT
    try:
        if method == "GET":
            r = requests.get(url, headers=headers, params=params, timeout=req_timeout)
        elif method == "POST":
            r = requests.post(url, headers=headers, json=body, timeout=req_timeout)
        elif method == "PUT":
            r = requests.put(url, headers=headers, json=body, timeout=req_timeout)
        elif method == "PATCH":
            r = requests.patch(url, headers=headers, json=body, timeout=req_timeout)
        elif method == "DELETE":
            r = requests.delete(url, headers=headers, timeout=req_timeout)
        else:
            return {"error": f"Unknown method: {method}"}

        if r.status_code >= 400:
            return {"error": f"HTTP {r.status_code}: {r.text[:500]}"}

        try:
            return r.json()
        except:
            return {"result": r.text[:1000]}
    except Exception as e:
        return {"error": str(e)}


# ─── Tool 정의 (OpenAI function calling) ───
TOOLS = [
    # 프로젝트/이슈
    {"type": "function", "function": {"name": "list_projects", "description": "프로젝트 목록 조회 (search로 프로젝트명/고객명 검색 가능. 특정 프로젝트를 찾을 때 반드시 search 사용)", "parameters": {"type": "object", "properties": {"search": {"type": "string", "description": "프로젝트명 또는 고객명 검색 키워드 (예: 삼성전자)"}}}}},
    {"type": "function", "function": {"name": "get_project", "description": "프로젝트 상세 조회", "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}}},
    {"type": "function", "function": {"name": "list_issues", "description": "프로젝트의 이슈 목록", "parameters": {"type": "object", "properties": {"project_id": {"type": "string"}}, "required": ["project_id"]}}},
    {"type": "function", "function": {"name": "get_issue", "description": "이슈 상세 조회", "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}}},
    {"type": "function", "function": {"name": "create_issue", "description": "이슈 생성", "parameters": {"type": "object", "properties": {"project_id": {"type": "string"}, "summary": {"type": "string"}, "description": {"type": "string"}, "priority": {"type": "string"}}, "required": ["project_id", "summary"]}}},
    {"type": "function", "function": {"name": "update_issue", "description": "이슈 수정", "parameters": {"type": "object", "properties": {"id": {"type": "string"}, "summary": {"type": "string"}, "description": {"type": "string"}, "priority": {"type": "string"}}, "required": ["id"]}}},
    {"type": "function", "function": {"name": "change_issue_status", "description": "이슈 상태 변경", "parameters": {"type": "object", "properties": {"id": {"type": "string"}, "status": {"type": "string"}}, "required": ["id", "status"]}}},
    {"type": "function", "function": {"name": "assign_issue", "description": "이슈 담당자 배정", "parameters": {"type": "object", "properties": {"id": {"type": "string"}, "assignee_id": {"type": "string"}}, "required": ["id", "assignee_id"]}}},

    # 업무요청
    {"type": "function", "function": {"name": "list_request_jobs", "description": "업무요청 목록 (검색/상태/작업유형 필터)", "parameters": {"type": "object", "properties": {"search": {"type": "string"}, "status": {"type": "string"}, "jobType": {"type": "string"}, "page": {"type": "integer"}, "size": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "get_request_job", "description": "업무요청 상세 조회", "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}}},
    {"type": "function", "function": {"name": "get_request_job_stats", "description": "업무요청 통계", "parameters": {"type": "object", "properties": {}}}},

    # 고객사
    {"type": "function", "function": {"name": "list_customers", "description": "고객사 목록 (검색/페이지네이션)", "parameters": {"type": "object", "properties": {"search": {"type": "string"}, "page": {"type": "integer"}, "size": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "get_customer", "description": "고객사 상세 조회", "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}}},
    {"type": "function", "function": {"name": "search_similar_customers", "description": "유사 고객사 검색", "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "get_customer_projects", "description": "고객사의 프로젝트 목록", "parameters": {"type": "object", "properties": {"customer_id": {"type": "string"}}, "required": ["customer_id"]}}},

    # 영업/Salesforce
    {"type": "function", "function": {"name": "search_expiring_contracts", "description": "Salesforce 영업 계약 만료 조회 (유지보수 계약과 다름! 유지보수 계약은 list_maintenance_contracts 사용)", "parameters": {"type": "object", "properties": {"months": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "get_salesforce_sync_status", "description": "Salesforce 동기화 상태", "parameters": {"type": "object", "properties": {}}}},

    # 유지보수 계약
    {"type": "function", "function": {"name": "list_maintenance_contracts", "description": "유지보수 계약 목록 조회. contractEndMonth로 특정 월 종료 계약 필터링 가능.", "parameters": {"type": "object", "properties": {"search": {"type": "string", "description": "고객사명 검색 키워드"}, "status": {"type": "string", "description": "ACTIVE/EXPIRED/RENEWED"}, "checkupCycle": {"type": "string"}, "productCode": {"type": "string"}, "isExpiring": {"type": "boolean", "description": "만료 임박 필터"}, "isExpiredButActive": {"type": "boolean", "description": "만료됐는데 ACTIVE인 계약 필터"}, "contractEndMonth": {"type": "string", "description": "종료월 필터 (예: 2026-03). 해당 월에 종료되는 계약만 반환"}, "size": {"type": "integer", "description": "조회 수 (기본 20, 전체 조회시 200)"}}}}},
    {"type": "function", "function": {"name": "get_maintenance_contract", "description": "유지보수 계약 상세 (고객/제품/프로젝트 포함)", "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}}},
    {"type": "function", "function": {"name": "get_expiring_maintenance", "description": "60일 이내 만료 임박 계약만 조회. 특정 월/날짜 검색에는 list_maintenance_contracts를 사용할 것.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_maintenance_plan", "description": "연간 점검 계획표", "parameters": {"type": "object", "properties": {"year": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "renew_maintenance_contract", "description": "유지보수 계약 갱신", "parameters": {"type": "object", "properties": {"id": {"type": "string"}, "new_end_date": {"type": "string"}}, "required": ["id", "new_end_date"]}}},
    {"type": "function", "function": {"name": "update_maintenance_contract", "description": "유지보수 계약 수정 (계약기간, 점검주기, 영업담당자, 비고 등)", "parameters": {"type": "object", "properties": {"id": {"type": "string", "description": "계약 ID"}, "contractStartDate": {"type": "string", "description": "계약 시작일 (YYYY-MM-DD)"}, "contractEndDate": {"type": "string", "description": "계약 종료일 (YYYY-MM-DD)"}, "checkupCycle": {"type": "string", "description": "점검주기 (MONTHLY/QUARTERLY/SEMI_ANNUALLY/ANNUALLY/REQUEST)"}, "salesManagerId": {"type": "string", "description": "영업담당자 ID"}, "remarks": {"type": "string", "description": "비고"}}, "required": ["id"]}}},

    # 정기점검
    {"type": "function", "function": {"name": "list_maintenance_issues", "description": "점검 이슈 목록 (담당자 UUID/상태 필터). '내 점검' 질문 시 assignee에 사용자 UUID를 전달하세요.", "parameters": {"type": "object", "properties": {"assignee": {"type": "string", "description": "담당자 UUID로 필터링"}, "status": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "get_current_month_checkups", "description": "이번 달 점검 목록. '내 점검' 질문 시 assignee에 사용자 UUID를 전달하면 본인 것만 필터링됩니다.", "parameters": {"type": "object", "properties": {"assignee": {"type": "string", "description": "담당자 UUID로 필터링 (선택)"}}}}},
    {"type": "function", "function": {"name": "get_upcoming_checkups", "description": "7일 내 예정 점검", "parameters": {"type": "object", "properties": {"assignee": {"type": "string", "description": "담당자 UUID로 필터링 (선택)"}}}}},
    {"type": "function", "function": {"name": "get_pending_checkups", "description": "미완료 점검", "parameters": {"type": "object", "properties": {"assignee": {"type": "string", "description": "담당자 UUID로 필터링 (선택)"}}}}},
    {"type": "function", "function": {"name": "get_maintenance_status", "description": "월별 점검 현황", "parameters": {"type": "object", "properties": {"year": {"type": "integer"}, "month": {"type": "integer"}}, "required": ["year", "month"]}}},
    {"type": "function", "function": {"name": "get_contract_issues", "description": "계약별 점검 이슈 목록", "parameters": {"type": "object", "properties": {"contract_id": {"type": "string"}}, "required": ["contract_id"]}}},

    # 서버
    {"type": "function", "function": {"name": "list_servers", "description": "서버 목록 (고객사/검색 필터)", "parameters": {"type": "object", "properties": {"search": {"type": "string"}, "customerId": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "get_server", "description": "서버 상세 정보", "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}}},
    {"type": "function", "function": {"name": "get_customer_servers", "description": "고객사별 서버 목록", "parameters": {"type": "object", "properties": {"customer_id": {"type": "string"}}, "required": ["customer_id"]}}},

    # 업무요청 (쓰기)
    {"type": "function", "function": {"name": "create_request_job", "description": "업무요청 신규 생성", "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "description": {"type": "string"}, "jobType": {"type": "string"}, "priority": {"type": "string"}}, "required": ["title"]}}},
    {"type": "function", "function": {"name": "assign_request_job", "description": "업무요청 담당자 배정", "parameters": {"type": "object", "properties": {"id": {"type": "string"}, "assignee_name": {"type": "string"}}, "required": ["id", "assignee_name"]}}},

    # 정기점검 (쓰기)
    {"type": "function", "function": {"name": "complete_maintenance_checkup", "description": "점검 완료 처리 (등급+서버 데이터)", "parameters": {"type": "object", "properties": {"issue_id": {"type": "string"}, "grade": {"type": "string"}, "comment": {"type": "string"}}, "required": ["issue_id"]}}},
    {"type": "function", "function": {"name": "get_server_checkup_data", "description": "서버별 점검 데이터 조회", "parameters": {"type": "object", "properties": {"issue_id": {"type": "string"}}, "required": ["issue_id"]}}},
    {"type": "function", "function": {"name": "save_server_checkup_data", "description": "서버 점검 데이터 저장", "parameters": {"type": "object", "properties": {"issue_id": {"type": "string"}, "server_id": {"type": "string"}, "data": {"type": "object"}}, "required": ["issue_id", "server_id", "data"]}}},

    # 알림
    {"type": "function", "function": {"name": "notify_expiring_contracts", "description": "만료 임박 계약 알림 발송 (이메일+Google Chat)", "parameters": {"type": "object", "properties": {}}}},

    # 이메일
    {"type": "function", "function": {"name": "send_email", "description": "이메일 발송", "parameters": {"type": "object", "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}}, "required": ["to", "subject", "body"]}}},

    # 메모리 검색
    {"type": "function", "function": {"name": "search_memory", "description": "이전 작업 기록 검색 (키워드로)", "parameters": {"type": "object", "properties": {"keyword": {"type": "string"}}, "required": ["keyword"]}}},

    # 통합고객검색
    {"type": "function", "function": {"name": "search_integrated_customer", "description": "Salesforce+NAS+유지보수 통합 고객사 검색", "parameters": {"type": "object", "properties": {"keyword": {"type": "string", "description": "검색 키워드"}}, "required": ["keyword"]}}},
    {"type": "function", "function": {"name": "get_salesforce_account", "description": "Salesforce 거래처 상세 조회", "parameters": {"type": "object", "properties": {"accountId": {"type": "string"}}, "required": ["accountId"]}}},
    {"type": "function", "function": {"name": "get_customer_timeline", "description": "고객사 활동 타임라인 조회", "parameters": {"type": "object", "properties": {"customerId": {"type": "string"}}, "required": ["customerId"]}}},

    # 제품
    {"type": "function", "function": {"name": "list_products", "description": "제품 목록 조회 (고객사별 필터)", "parameters": {"type": "object", "properties": {"customerId": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "get_product", "description": "제품 상세 조회", "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}}},
    {"type": "function", "function": {"name": "list_product_versions", "description": "제품 버전 목록", "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}}},

    # 고객사 담당자
    {"type": "function", "function": {"name": "list_customer_contacts", "description": "고객사 담당자 연락처 목록", "parameters": {"type": "object", "properties": {"customerId": {"type": "string"}}, "required": ["customerId"]}}},
    {"type": "function", "function": {"name": "get_customer_contact", "description": "고객사 담당자 상세 정보", "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}}},

    # 법인
    {"type": "function", "function": {"name": "get_corporation", "description": "법인 정보 상세 조회", "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}}},
    {"type": "function", "function": {"name": "get_customer_corporation", "description": "고객사의 법인 정보 조회", "parameters": {"type": "object", "properties": {"customerId": {"type": "string"}}, "required": ["customerId"]}}},

    # 에픽/마일스톤
    {"type": "function", "function": {"name": "list_epics", "description": "프로젝트의 에픽/마일스톤 목록", "parameters": {"type": "object", "properties": {"projectId": {"type": "string"}}, "required": ["projectId"]}}},
    {"type": "function", "function": {"name": "get_epic", "description": "에픽 상세 조회 (진행률 포함)", "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}}},

    # 사용자/엔지니어
    {"type": "function", "function": {"name": "list_engineers", "description": "전체 엔지니어 목록 조회", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "list_user_names", "description": "전체 사용자 이름 목록", "parameters": {"type": "object", "properties": {}}}},

    # 댓글
    {"type": "function", "function": {"name": "list_comments", "description": "이슈/프로젝트의 댓글 목록 조회", "parameters": {"type": "object", "properties": {"targetType": {"type": "string", "description": "ISSUE 또는 PROJECT"}, "targetId": {"type": "string"}}, "required": ["targetType", "targetId"]}}},
    {"type": "function", "function": {"name": "create_comment", "description": "댓글 작성", "parameters": {"type": "object", "properties": {"targetType": {"type": "string", "description": "ISSUE 또는 PROJECT"}, "targetId": {"type": "string"}, "content": {"type": "string"}, "parentId": {"type": "string"}}, "required": ["targetType", "targetId", "content"]}}},

    # 라벨
    {"type": "function", "function": {"name": "list_labels", "description": "라벨/태그 목록 조회", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_label", "description": "라벨 상세 조회", "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}}},

    # 유지보수 영업 담당자
    {"type": "function", "function": {"name": "list_sales_managers", "description": "유지보수 영업 담당자 목록 조회", "parameters": {"type": "object", "properties": {}}}},

    # 라이선스
    {"type": "function", "function": {"name": "list_licenses", "description": "라이선스 목록 조회 (고객사/제품별 필터)", "parameters": {"type": "object", "properties": {"customerId": {"type": "string"}, "productId": {"type": "string"}, "page": {"type": "integer"}, "size": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "get_license", "description": "라이선스 상세 조회", "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}}},
    {"type": "function", "function": {"name": "get_license_stats", "description": "라이선스 통계", "parameters": {"type": "object", "properties": {}}}},

    # 서버 확장
    {"type": "function", "function": {"name": "search_servers", "description": "고객사 서버 검색 (키워드)", "parameters": {"type": "object", "properties": {"customerId": {"type": "string", "description": "고객사 ID (필수)"}, "keyword": {"type": "string", "description": "검색 키워드"}}, "required": ["customerId", "keyword"]}}},
    {"type": "function", "function": {"name": "get_server_count", "description": "고객사 서버 수량 조회 (환경별)", "parameters": {"type": "object", "properties": {"customerId": {"type": "string", "description": "고객사 ID (필수)"}}, "required": ["customerId"]}}},

    # ─── 신규 도구 (2026-02 추가) ───

    # 날짜 범위 점검 조회 (다음 달/특정 기간 점검에 최적)
    {"type": "function", "function": {"name": "get_checkups_by_date_range", "description": "날짜 범위로 점검 이슈 조회. '다음 달 점검', '3월 점검', '특정 기간 점검'에 사용. assigneeId로 본인 점검만 필터링 가능.", "parameters": {"type": "object", "properties": {"startDate": {"type": "string", "description": "시작일 (YYYY-MM-DD)"}, "endDate": {"type": "string", "description": "종료일 (YYYY-MM-DD)"}, "assigneeId": {"type": "string", "description": "담당자 UUID (선택)"}}, "required": ["startDate", "endDate"]}}},

    # 만료됐는데 ACTIVE인 계약 감지
    {"type": "function", "function": {"name": "get_expired_active_contracts", "description": "계약 종료일이 지났는데 아직 ACTIVE 상태인 계약 목록 (갱신 누락 감지)", "parameters": {"type": "object", "properties": {}}}},

    # 갱신 누락 계약 감지
    {"type": "function", "function": {"name": "get_contract_renewal_gaps", "description": "갱신이 필요한데 아직 처리되지 않은 계약 목록 (D-N일 기준)", "parameters": {"type": "object", "properties": {"daysAhead": {"type": "integer", "description": "만료 N일 전 기준 (기본 60)"}}}}},

    # 계약 만료 처리
    {"type": "function", "function": {"name": "expire_maintenance_contract", "description": "유지보수 계약 만료 처리 (ACTIVE → EXPIRED)", "parameters": {"type": "object", "properties": {"contractId": {"type": "string", "description": "계약 ID"}}, "required": ["contractId"]}}},

    # 업무요청 확장
    {"type": "function", "function": {"name": "update_request_job", "description": "업무요청 수정", "parameters": {"type": "object", "properties": {"id": {"type": "string", "description": "업무요청 ID"}, "description": {"type": "string"}, "dueDate": {"type": "string"}, "status": {"type": "string"}, "workType": {"type": "string"}}, "required": ["id"]}}},
    {"type": "function", "function": {"name": "change_request_job_status", "description": "업무요청 상태 변경", "parameters": {"type": "object", "properties": {"id": {"type": "string", "description": "업무요청 ID"}, "status": {"type": "string", "description": "변경할 상태"}}, "required": ["id", "status"]}}},
    {"type": "function", "function": {"name": "delete_request_job", "description": "업무요청 삭제", "parameters": {"type": "object", "properties": {"id": {"type": "string", "description": "업무요청 ID"}}, "required": ["id"]}}},

    # 통합 고객 카드
    {"type": "function", "function": {"name": "get_customer_card", "description": "통합 고객 카드 조회 (계약/프로젝트/Salesforce 정보 통합)", "parameters": {"type": "object", "properties": {"customerId": {"type": "string", "description": "고객사 ID"}}, "required": ["customerId"]}}},

    # 유지보수 고객 검색
    {"type": "function", "function": {"name": "search_maintenance_customer", "description": "유지보수 관점 고객 검색 (계약/점검 정보 포함)", "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "검색 키워드"}}, "required": ["query"]}}},

    # 프로젝트 멤버
    {"type": "function", "function": {"name": "get_project_members", "description": "프로젝트 멤버 목록 (담당자 이름/UUID 확인)", "parameters": {"type": "object", "properties": {"projectId": {"type": "string", "description": "프로젝트 ID"}}, "required": ["projectId"]}}},

    # 고객사별 업무요청
    {"type": "function", "function": {"name": "get_customer_request_jobs", "description": "특정 고객사의 업무요청 목록", "parameters": {"type": "object", "properties": {"customerId": {"type": "string", "description": "고객사 ID"}}, "required": ["customerId"]}}},
]


# ─── 도구 Fallback 맵 (Reflection 재시도용) ───
TOOL_FALLBACK_MAP = {
    "search_integrated_customer": ["list_maintenance_contracts", "list_customers", "search_similar_customers"],
    "get_expiring_maintenance": ["list_maintenance_contracts"],
    "search_expiring_contracts": ["list_maintenance_contracts", "get_expiring_maintenance"],
    "list_maintenance_contracts": ["search_maintenance_customer", "search_expiring_contracts"],
    "get_current_month_checkups": ["get_checkups_by_date_range", "list_maintenance_issues", "get_maintenance_plan"],
    "get_customer_servers": ["list_servers", "search_servers"],
    "list_customers": ["search_similar_customers", "search_maintenance_customer", "search_integrated_customer"],
    "search_similar_customers": ["list_customers", "search_maintenance_customer", "search_integrated_customer"],
    "get_pending_checkups": ["list_maintenance_issues", "get_maintenance_plan"],
    "get_upcoming_checkups": ["get_checkups_by_date_range", "get_maintenance_plan", "list_maintenance_issues"],
    "get_checkups_by_date_range": ["get_maintenance_plan", "list_maintenance_issues"],
    "search_integrated_customer": ["search_maintenance_customer", "list_maintenance_contracts", "list_customers"],
    "search_maintenance_customer": ["search_integrated_customer", "list_maintenance_contracts", "list_customers"],
}

# ─── Agent: 복잡도 평가 ───
def _assess_complexity(instruction):
    """
    쿼리 복잡도 점수 (0-10) → SIMPLE/MODERATE/COMPLEX 분류.
    규칙 기반으로 API 호출 없이 즉시 판별한다.
    """
    import re as _re

    text = instruction.strip()
    # [요청 1] ... \n---\n[참고사항] 에서 실제 질문만 추출
    if "\n---\n" in text:
        text = text.split("\n---\n")[0].strip()
    req = _re.search(r"\[요청\s*\d+\].*?\n(.+)", text, _re.DOTALL)
    if req:
        text = req.group(1).strip()

    score = 0

    # 1. 복합 키워드 (+3)
    if _re.search(r"비교|분석|통계|요약|종합|현황|추이|정리|리포트|보고서", text):
        score += 3

    # 2. 다중 도메인 (2개 이상이면 +2 per extra)
    domains = 0
    if _re.search(r"계약|유지보수|만료|갱신", text):
        domains += 1
    if _re.search(r"점검|체크|checkup", text):
        domains += 1
    if _re.search(r"서버|server", text):
        domains += 1
    if _re.search(r"영업|salesforce|Salesforce|거래처", text):
        domains += 1
    if _re.search(r"이슈|프로젝트|업무요청", text):
        domains += 1
    if domains >= 2:
        score += (domains - 1) * 2

    # 3. 날짜 비교 (+2)
    if _re.search(r"대비|추이|변화|전월|전년|작년|지난.*(비교|대비)", text):
        score += 2

    # 4. 다중 요청 (+1 each, max 3)
    conjunctions = len(_re.findall(r"하고|도\s|또한|그리고|및\s|겸", text))
    score += min(conjunctions, 3)

    # 5. 긴 질문 (+1)
    if len(text) > 100:
        score += 1

    # 점수 상한
    score = min(score, 10)

    level = "SIMPLE" if score <= 3 else "MODERATE" if score <= COMPLEXITY_THRESHOLD_COMPLEX - 1 else "COMPLEX"
    return score, level


# ─── Agent: 실행 계획 생성 ───
def _format_tool_names():
    """사용 가능한 도구 이름 목록 (계획 생성용)"""
    names = [t["function"]["name"] for t in TOOLS if "function" in t]
    # 주요 도구 그룹핑
    groups = {
        "고객사": [n for n in names if "customer" in n or "similar" in n],
        "유지보수계약": [n for n in names if "maintenance_contract" in n or n in ("get_expiring_maintenance", "get_expired_active_contracts", "get_contract_renewal_gaps")],
        "점검": [n for n in names if "checkup" in n or "maintenance_issue" in n or n in ("get_current_month_checkups", "get_upcoming_checkups", "get_pending_checkups", "get_checkups_by_date_range", "get_maintenance_status", "list_maintenance_issues", "get_contract_issues")],
        "서버": [n for n in names if "server" in n],
        "영업": [n for n in names if "salesforce" in n or "expiring_contract" in n or n == "search_integrated_customer"],
        "이슈/프로젝트": [n for n in names if "issue" in n or "project" in n or "epic" in n],
    }
    lines = []
    for group, tools in groups.items():
        if tools:
            lines.append(f"  {group}: {', '.join(tools)}")
    return "\n".join(lines)


def _generate_plan(instruction, identity, available_tools):
    """복잡한 쿼리에 대한 다단계 실행 계획 생성 (gpt-4o-mini)"""
    import re as _re

    # 순수 질문만 추출
    text = instruction.strip()
    if "\n---\n" in text:
        text = text.split("\n---\n")[0].strip()
    req = _re.search(r"\[요청\s*\d+\].*?\n(.+)", text, _re.DOTALL)
    if req:
        text = req.group(1).strip()

    user_info = ""
    if identity:
        user_info = f"\n사용자: {identity['name']} (UUID: {identity['uuid']})"

    plan_prompt = f"""사용자 질문을 답변하기 위한 실행 계획을 세워주세요.

[질문]
{text[:500]}{user_info}

[사용 가능한 도구]
{_format_tool_names()}

[규칙]
- 최소한의 도구로 최대 정보를 얻는 계획
- 각 단계는 이전 단계 결과에 따라 달라질 수 있음
- 3-5단계 이내로 제한
- "내 점검" 등 본인 관련 질문은 assigneeId/assignee에 사용자 UUID 사용

반드시 아래 JSON 배열만 반환하세요 (설명 없이):
[
  {{"step": 1, "tool": "도구명", "purpose": "이 단계의 목적", "args_hint": "주요 파라미터 힌트"}},
  ...
]"""

    try:
        response = client.chat.completions.create(
            model=AGENT_MODEL,
            messages=[{"role": "user", "content": plan_prompt}],
            temperature=0.2,
            max_tokens=800,
        )
        plan_text = response.choices[0].message.content or ""

        # JSON 파싱
        # ```json ... ``` 블록 추출
        code_block = _re.search(r'```(?:json)?\s*(\[.*?\])\s*```', plan_text, _re.DOTALL)
        if code_block:
            plan_text = code_block.group(1)
        else:
            # 순수 JSON 배열 추출
            bracket_match = _re.search(r'\[.*\]', plan_text, _re.DOTALL)
            if bracket_match:
                plan_text = bracket_match.group()

        parsed = json.loads(plan_text)
        if isinstance(parsed, list) and len(parsed) > 0:
            # 최대 5단계로 제한
            parsed = parsed[:5]
            log(f"[agent] 계획 생성 완료: {len(parsed)}단계")
            return parsed
        else:
            log("[agent] 계획 파싱 실패: 빈 배열")
            return None

    except (json.JSONDecodeError, Exception) as e:
        log(f"[agent] 계획 생성/파싱 실패: {e}")
        return None


# ─── Agent: 단계별 검증 ───
def _verify_step_result(tool_name, tool_args, result, instruction):
    """
    도구 결과가 유의미한지 즉시 판별 → (ok, suggestion).
    API 호출 없이 규칙 기반으로 판별 → 추가 비용 0, 지연 0.
    """
    result_str = truncate_json(result, max_len=500)

    # 쓰기 작업 → 항상 OK
    if tool_name in WRITE_TOOLS:
        return True, None

    # 데이터 있음 → OK
    if _result_has_data(result_str):
        return True, None

    # 빈 결과 → TOOL_FALLBACK_MAP에서 대체 도구 제안
    fallbacks = TOOL_FALLBACK_MAP.get(tool_name, [])
    if fallbacks:
        suggestion = f"빈 결과. 대체 도구 추천: {fallbacks[0]}"
        return False, suggestion

    return False, "빈 결과, 대체 도구 없음"


# 쓰기 작업 도구 이름 (검증 Quick-Pass용)
WRITE_TOOLS = {
    "create_issue", "update_issue", "change_issue_status", "assign_issue",
    "create_request_job", "assign_request_job",
    "update_request_job", "change_request_job_status", "delete_request_job",
    "complete_maintenance_checkup", "save_server_checkup_data",
    "renew_maintenance_contract", "update_maintenance_contract",
    "expire_maintenance_contract",
    "notify_expiring_contracts", "send_email",
    "create_comment",
}


# ─── A: Fast Path (의도 직접 매칭 → OpenAI turn 1 스킵) ───
def _fast_path_match(instruction, identity):
    """
    자주 사용하는 질문 패턴을 로컬에서 매칭 → (tool_name, tool_args) 반환.
    매칭 실패 시 None → 기존 OpenAI function calling으로 fallback.
    """
    import re as _re

    # [요청 1] ... \n---\n[참고사항] 에서 실제 질문만 추출
    text = instruction.strip()
    if "\n---\n" in text:
        text = text.split("\n---\n")[0].strip()
    req = _re.search(r"\[요청\s*\d+\].*?\n(.+)", text, _re.DOTALL)
    if req:
        text = req.group(1).strip()

    is_personal = bool(_re.search(r"내|나의|내꺼|내\s*것|본인", text))
    uuid = identity["uuid"] if identity else None
    now = datetime.now()

    # ── 점검 관련 ──
    if _re.search(r"점검|체크", text):
        # 미완료/지연
        if _re.search(r"미(완료|처리|진행)|지연|밀린|안\s*한|누락", text):
            args = {"assignee": uuid} if is_personal and uuid else {}
            return ("get_pending_checkups", args)

        # 다음 달 → date-range API 사용
        if _re.search(r"(다음|차|익|내달)\s*(달)?", text):
            import calendar
            next_m = now.month + 1 if now.month < 12 else 1
            next_y = now.year if now.month < 12 else now.year + 1
            last_day = calendar.monthrange(next_y, next_m)[1]
            fp_args = {"startDate": f"{next_y}-{next_m:02d}-01", "endDate": f"{next_y}-{next_m:02d}-{last_day}"}
            if is_personal and uuid:
                fp_args["assigneeId"] = uuid
            return ("get_checkups_by_date_range", fp_args)

        # 특정 월 (현재 월이 아닌 경우) → date-range API 사용
        month_m = _re.search(r"(\d{1,2})월", text)
        if month_m:
            m = int(month_m.group(1))
            if m != now.month:
                import calendar
                last_day = calendar.monthrange(now.year, m)[1]
                fp_args = {"startDate": f"{now.year}-{m:02d}-01", "endDate": f"{now.year}-{m:02d}-{last_day}"}
                if is_personal and uuid:
                    fp_args["assigneeId"] = uuid
                return ("get_checkups_by_date_range", fp_args)

        # 이번 달 / 일반 점검
        args = {"assignee": uuid} if is_personal and uuid else {}
        return ("get_current_month_checkups", args)

    # ── 만료 계약 조회 (다음 달 / 이번 달 / 특정 월 / 만료 임박) ──
    target_month = None
    if _re.search(r"다음\s*달.*(만료|종료|끝|마감)|다음\s*달.*계약", text):
        next_m = now.month + 1
        next_y = now.year
        if next_m > 12:
            next_m = 1
            next_y += 1
        target_month = f"{next_y}-{next_m:02d}"
    elif _re.search(r"이번\s*달.*(만료|종료|끝|마감)|이번\s*달.*계약", text):
        target_month = f"{now.year}-{now.month:02d}"
    else:
        month_expire = _re.search(r"(\d{1,2})월.*(만료|종료|끝|마감|계약)", text)
        if month_expire:
            target_month = f"{now.year}-{int(month_expire.group(1)):02d}"

    if target_month:
        return ("_combined_expiring_contracts", {"_filter_month": target_month})

    if _re.search(r"만료.*(임박|예정|곧)|곧.*만료", text):
        return ("get_expiring_maintenance", {})

    # ── 매칭 안됨 → 기존 flow ──
    return None


# ─── D: Fast Path용 경량 시스템 프롬프트 ───
FAST_SYSTEM_PROMPT = """업무 비서 AI. 도구 결과를 한국어로 간결하게 정리.
규칙: 고객사별 그룹핑, 담당자 표시, UUID 숨김, 영문→한국어 번역(ACTIVE=활성, QUARTERLY=분기, MONTHLY=월간, SEMI_ANNUALLY=반기, COMPLETED=완료, PENDING=대기)."""


def execute_tool(name, args):
    """Tool 실행 → STACK API 호출 → UUID 자동 변환"""
    result = _execute_tool_raw(name, args)
    # 모든 도구 결과에서 UUID → 이름 자동 변환
    try:
        _resolve_uuids_in_result(result)
    except Exception:
        pass
    return result

def _execute_tool_raw(name, args):
    """Tool 실행 (내부용)"""

    # ── 내부 전용: 유지보수 + Salesforce 만료 계약 통합 조회 ──
    if name == "_combined_expiring_contracts":
        filter_month = args.get("_filter_month", "")
        log(f"[tool] _combined_expiring_contracts: filter_month={filter_month}")
        combined = []
        seen_names = set()

        # 1) 유지보수 계약 (list_maintenance_contracts, 전체 조회 + 월 필터)
        try:
            mc_result = stack_api("GET", "/api/maintenance-contracts",
                                 params={"size": 1000, "statuses": "ACTIVE,RENEWED,EXPIRED"}, timeout=45)
            mc_items = []
            if isinstance(mc_result, dict) and mc_result.get("data"):
                raw = mc_result["data"]
                mc_items = raw.get("items", []) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
            for item in mc_items:
                contract = item.get("contract", item)
                ed = contract.get("contractEndDate", "")
                if ed and ed.startswith(filter_month):
                    cname = item.get("customerName", contract.get("customerName", ""))
                    combined.append({
                        "source": "유지보수",
                        "customerName": cname,
                        "contractStartDate": contract.get("contractStartDate", ""),
                        "contractEndDate": ed,
                        "status": contract.get("status", ""),
                        "checkupCycle": contract.get("checkupCycle", ""),
                        "salesManagerName": item.get("salesManagerName", ""),
                        "projects": item.get("projects", []),
                    })
                    if cname:
                        seen_names.add(cname)
            log(f"[tool] _combined: 유지보수 {len(mc_items)}건 → {filter_month} 매칭 {len(combined)}건")
        except Exception as e:
            log(f"[tool] _combined: 유지보수 조회 실패: {e}")

        # 2) Salesforce 영업 계약 (contract-expiration/search)
        #    응답: {data: {opportunities: [...], totalOpportunities: N}}
        #    항목 키: accountName, contract_End_Date__c, stageName, ownerName, amount, name
        try:
            sf_result = stack_api("GET", "/api/contract-expiration/search", params={"months": 3})
            sf_items = []
            if isinstance(sf_result, dict) and sf_result.get("data"):
                sf_data = sf_result["data"]
                sf_items = sf_data.get("opportunities", sf_data.get("items", []))
            sf_count = 0
            for item in sf_items:
                ed = item.get("contract_End_Date__c", item.get("closeDate", ""))
                if ed and ed.startswith(filter_month):
                    cname = item.get("accountName", item.get("customerName", ""))
                    if cname and cname not in seen_names:
                        combined.append({
                            "source": "Salesforce",
                            "customerName": cname,
                            "opportunityName": item.get("name", ""),
                            "contractEndDate": ed,
                            "amount": item.get("amount", ""),
                            "stage": item.get("stageName", ""),
                            "ownerName": item.get("ownerName", ""),
                        })
                        seen_names.add(cname)
                        sf_count += 1
            log(f"[tool] _combined: Salesforce {len(sf_items)}건 → {filter_month} 신규 {sf_count}건")
        except Exception as e:
            log(f"[tool] _combined: Salesforce 조회 실패: {e}")

        log(f"[tool] _combined: 총 {len(combined)}건 (유지보수+Salesforce 통합)")
        if not combined:
            return {"success": True, "data": [], "total": 0, "message": f"{filter_month}에 종료되는 계약이 없습니다."}
        return {"success": True, "data": combined, "total": len(combined), "filter": f"contractEndDate in {filter_month}"}

    # 프로젝트/이슈
    if name == "list_projects":
        params = {}
        if args.get("search"):
            params["search"] = args["search"]
        return stack_api("GET", "/api/projects", params=params)
    elif name == "get_project":
        return stack_api("GET", f"/api/projects/{args['id']}")
    elif name == "list_issues":
        return stack_api("GET", f"/api/projects/{args['project_id']}/issues")
    elif name == "get_issue":
        return stack_api("GET", f"/api/issues/{args['id']}")
    elif name == "create_issue":
        body = {k: v for k, v in args.items() if k != "project_id"}
        return stack_api("POST", f"/api/projects/{args['project_id']}/issues", body=body)
    elif name == "update_issue":
        body = {k: v for k, v in args.items() if k != "id"}
        return stack_api("PUT", f"/api/issues/{args['id']}", body=body)
    elif name == "change_issue_status":
        return stack_api("PATCH", f"/api/issues/{args['id']}/status", body={"status": args["status"]})
    elif name == "assign_issue":
        return stack_api("PATCH", f"/api/issues/{args['id']}/assign", body={"assigneeId": args["assignee_id"]})

    # 업무요청
    elif name == "list_request_jobs":
        return stack_api("GET", "/api/requestJob", params={k: v for k, v in args.items()})
    elif name == "get_request_job":
        return stack_api("GET", f"/api/requestJob/{args['id']}")
    elif name == "get_request_job_stats":
        return stack_api("GET", "/api/requestJob/stats")

    # 고객사
    elif name == "list_customers":
        return stack_api("GET", "/api/customers", params={k: v for k, v in args.items()})
    elif name == "get_customer":
        return stack_api("GET", f"/api/customers/{args['id']}")
    elif name == "search_similar_customers":
        return stack_api("GET", "/api/customers/check-similar", params={"name": args["name"]})
    elif name == "get_customer_projects":
        return stack_api("GET", f"/api/customers/{args['customer_id']}/projects")

    # 영업
    elif name == "search_expiring_contracts":
        return stack_api("GET", "/api/contract-expiration/search", params=args)
    elif name == "get_salesforce_sync_status":
        return stack_api("GET", "/api/salesforce-sync/status")

    # 유지보수 계약
    elif name == "list_maintenance_contracts":
        end_month = args.pop("contractEndMonth", None)
        if end_month:
            args["size"] = 1000  # 전체 조회 필수
            args.pop("status", None)  # 기존 status 제거
            args["statuses"] = "ACTIVE,RENEWED,EXPIRED"  # 모든 상태 명시 요청
        log(f"[tool] list_maintenance_contracts: params={args}, end_month={end_month}")
        api_timeout = 45 if end_month else None  # 전체 조회 시 타임아웃 연장
        result = stack_api("GET", "/api/maintenance-contracts", params=args, timeout=api_timeout)
        if end_month:
            # 에러 응답 감지 → 바로 반환
            if isinstance(result, dict) and "error" in result:
                log(f"[tool] list_maintenance_contracts: API 에러 → {str(result['error'])[:200]}")
                return result

            # 결과 구조 디버깅
            result_type = type(result).__name__
            result_keys = list(result.keys())[:10] if isinstance(result, dict) else "N/A"
            data_val = result.get("data") if isinstance(result, dict) else None
            data_type = type(data_val).__name__ if data_val is not None else "None"
            log(f"[tool] list_maintenance_contracts: result_type={result_type}, keys={result_keys}, data_type={data_type}")
            # content 키 등 대체 구조 확인
            if isinstance(result, dict) and data_val is None:
                for k in ["content", "items", "list", "contracts", "results"]:
                    if k in result and result[k]:
                        log(f"[tool] list_maintenance_contracts: 대체 키 발견 '{k}' (type={type(result[k]).__name__})")
                log(f"[tool] list_maintenance_contracts: result preview={str(result)[:300]}")

            # items 추출 (다양한 API 응답 구조 대응)
            items = []
            if isinstance(result, dict):
                raw_data = result.get("data")
                if raw_data and isinstance(raw_data, list):
                    items = raw_data
                elif raw_data and isinstance(raw_data, dict):
                    items = raw_data.get("items", [])
                    if not isinstance(items, list):
                        items = []
                elif not raw_data:
                    # "data" 키 없음 → 대체 키 탐색
                    for alt_key in ["content", "items", "list", "contracts", "results"]:
                        alt_val = result.get(alt_key)
                        if alt_val and isinstance(alt_val, list):
                            items = alt_val
                            log(f"[tool] list_maintenance_contracts: '{alt_key}' 키에서 {len(items)}건 추출")
                            break
                    # "totalElements" 있으면 페이지네이션 응답 → "content" 키 대신 직접 items 키 사용
                    if not items and "totalElements" in result:
                        # Spring Page 응답: {content: [...], totalElements: N, ...}
                        content = result.get("content", [])
                        if isinstance(content, list):
                            items = content
                            log(f"[tool] list_maintenance_contracts: Spring Page 'content' 키에서 {len(items)}건 추출")
            elif isinstance(result, list):
                items = result

            # 페이지네이션 확인
            if isinstance(result.get("data"), dict):
                total_el = result["data"].get("totalElements", "?")
                total_pg = result["data"].get("totalPages", "?")
                log(f"[tool] list_maintenance_contracts: totalElements={total_el}, totalPages={total_pg}, fetched={len(items)}")

            log(f"[tool] list_maintenance_contracts: 전체 {len(items)}건, endMonth={end_month} 필터링 시작")
            filtered = []
            for item in items:
                contract = item.get("contract", item) if isinstance(item, dict) else {}
                ed = contract.get("contractEndDate", "")
                if ed and ed.startswith(end_month):
                    filtered.append({
                        "customerName": item.get("customerName", contract.get("customerName", "")),
                        "contractStartDate": contract.get("contractStartDate", ""),
                        "contractEndDate": ed,
                        "status": contract.get("status", ""),
                        "checkupCycle": contract.get("checkupCycle", ""),
                        "salesManagerName": item.get("salesManagerName", ""),
                        "contractId": contract.get("id", ""),
                        "projects": [{"description": p.get("description", ""), "engineerName": p.get("engineerName", ""), "productCode": p.get("productCode", "")} for p in item.get("projects", [])],
                    })
            log(f"[tool] list_maintenance_contracts: {end_month} 매칭 {len(filtered)}건")
            if not filtered:
                return {"success": True, "data": [], "total": 0, "message": f"{end_month}에 종료되는 유지보수 계약이 없습니다."}
            return {"success": True, "data": filtered, "total": len(filtered), "filter": f"contractEndDate starts with {end_month}"}
        return result
    elif name == "get_maintenance_contract":
        return stack_api("GET", f"/api/maintenance-contracts/{args['id']}/detail")
    elif name == "get_expiring_maintenance":
        filter_month = args.pop("_filter_month", None)
        result = stack_api("GET", "/api/maintenance-contracts/expiring")
        if isinstance(result, dict) and result.get("data"):
            items = result["data"] if isinstance(result["data"], list) else result["data"].get("items", [])
            # 특정 월 필터링
            if filter_month:
                filtered = []
                for item in items:
                    contract = item.get("contract", item)
                    ed = contract.get("contractEndDate", "")
                    if ed and ed.startswith(filter_month):
                        filtered.append(item)
                log(f"[tool] get_expiring_maintenance: {filter_month} 필터 → {len(filtered)}/{len(items)}건")
                if not filtered:
                    return {"success": True, "data": [], "total": 0, "message": f"{filter_month}에 종료되는 유지보수 계약이 없습니다."}
                if isinstance(result["data"], list):
                    result["data"] = filtered
                elif isinstance(result["data"], dict):
                    result["data"]["items"] = filtered
                    result["data"]["totalElements"] = len(filtered)
        return result
    elif name == "get_maintenance_plan":
        return stack_api("GET", "/api/maintenance-contracts/plan", params={"year": args.get("year", datetime.now().year)})
    elif name == "renew_maintenance_contract":
        return stack_api("POST", f"/api/maintenance-contracts/{args['id']}/renew", body={"newEndDate": args["new_end_date"]})
    elif name == "update_maintenance_contract":
        cid = args.pop("id")
        body = {k: v for k, v in args.items() if v is not None}
        return stack_api("PUT", f"/api/maintenance-contracts/{cid}", body=body)

    # 정기점검
    elif name == "list_maintenance_issues":
        assignee_filter = args.pop("assignee", None)
        result = stack_api("GET", "/api/maintenance/issues", params=args)
        # API가 assignee 필터를 무시하므로 클라이언트 사이드 필터링
        if assignee_filter and isinstance(result, dict) and not result.get("error"):
            data = result.get("data", result)
            items = data.get("items", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            filtered = [i for i in items if i.get("assigneeId") == assignee_filter]
            log(f"[tool] list_maintenance_issues: assignee 필터 적용 {len(items)}→{len(filtered)}건")
            if isinstance(data, dict):
                data["items"] = filtered
                data["totalCount"] = len(filtered)
            else:
                result["data"] = filtered
        return result
    elif name in ("get_current_month_checkups", "get_upcoming_checkups", "get_pending_checkups"):
        endpoint_map = {
            "get_current_month_checkups": "/api/maintenance/issues/current-month",
            "get_upcoming_checkups": "/api/maintenance/issues/upcoming",
            "get_pending_checkups": "/api/maintenance/issues/pending",
        }
        assignee_filter = args.get("assignee")

        # get_pending_checkups는 서버가 assigneeId를 필수로 요구함
        if name == "get_pending_checkups":
            params = {}
            if assignee_filter:
                params["assigneeId"] = assignee_filter
            else:
                # assigneeId 없으면 list_maintenance_issues로 대체 (전체 조회)
                log(f"[tool] get_pending_checkups: assigneeId 없음 → list_maintenance_issues 대체")
                result = stack_api("GET", "/api/maintenance/issues", params={"status": "OPEN", "size": 200})
                return result
            result = stack_api("GET", endpoint_map[name], params=params)
            return result

        # current-month, upcoming: 서버가 assignee 필터 무시 → 클라이언트 사이드 필터링
        result = stack_api("GET", endpoint_map[name])
        if assignee_filter and isinstance(result, dict) and not result.get("error"):
            data = result.get("data", result)
            items = data.get("items", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            filtered = [i for i in items if i.get("assigneeId") == assignee_filter]
            log(f"[tool] {name}: assignee 필터 적용 {len(items)}→{len(filtered)}건")
            if isinstance(data, dict) and "items" in data:
                data["items"] = filtered
            elif isinstance(data, list):
                result["data"] = filtered
            else:
                result["data"] = filtered
        return result
    elif name == "get_maintenance_status":
        return stack_api("GET", "/api/maintenance/status", params={"year": args.get("year"), "month": args.get("month")})
    elif name == "get_contract_issues":
        return stack_api("GET", f"/api/maintenance-contracts/{args['contract_id']}/issues")

    # 서버
    elif name == "list_servers":
        return stack_api("GET", "/api/servers", params=args)
    elif name == "get_server":
        return stack_api("GET", f"/api/servers/{args['id']}")
    elif name == "get_customer_servers":
        return stack_api("GET", f"/api/customers/{args['customer_id']}/servers")

    # 업무요청 (쓰기)
    elif name == "create_request_job":
        return stack_api("POST", "/api/requestJob", body=args)
    elif name == "assign_request_job":
        return stack_api("PATCH", f"/api/requestJob/{args['id']}/assign/{args['assignee_name']}")

    # 정기점검 (쓰기)
    elif name == "complete_maintenance_checkup":
        body = {k: v for k, v in args.items() if k != "issue_id"}
        return stack_api("POST", f"/api/maintenance/issues/{args['issue_id']}/complete", body=body)
    elif name == "get_server_checkup_data":
        return stack_api("GET", f"/api/maintenance/issues/{args['issue_id']}/servers")
    elif name == "save_server_checkup_data":
        return stack_api("POST", f"/api/maintenance/issues/{args['issue_id']}/servers/{args['server_id']}/save", body=args.get("data", {}))

    # 알림
    elif name == "notify_expiring_contracts":
        return stack_api("POST", "/api/contract-expiration/notify")

    # 이메일
    elif name == "send_email":
        return stack_api("POST", "/api/mail/send", body=args)

    # 메모리 검색
    elif name == "search_memory":
        matches = search_memory(keyword=args["keyword"])
        return {"matches": matches}

    # 통합고객검색
    elif name == "search_integrated_customer":
        return stack_api("GET", "/api/integrated-customer/search", params={"keyword": args["keyword"]})
    elif name == "get_salesforce_account":
        return stack_api("GET", f"/api/integrated-customer/salesforce/account/{args['accountId']}")
    elif name == "get_customer_timeline":
        return stack_api("GET", f"/api/integrated-customer/{args['customerId']}/timeline")

    # 제품
    elif name == "list_products":
        return stack_api("GET", "/api/products", params=args)
    elif name == "get_product":
        return stack_api("GET", f"/api/products/{args['id']}")
    elif name == "list_product_versions":
        return stack_api("GET", f"/api/products/{args['id']}/versions")

    # 고객사 담당자
    elif name == "list_customer_contacts":
        return stack_api("GET", "/api/customer-contacts", params={"customerId": args["customerId"]})
    elif name == "get_customer_contact":
        return stack_api("GET", f"/api/customer-contacts/{args['id']}")

    # 법인
    elif name == "get_corporation":
        return stack_api("GET", f"/api/corporations/{args['id']}")
    elif name == "get_customer_corporation":
        return stack_api("GET", f"/api/corporations/customer/{args['customerId']}")

    # 에픽/마일스톤
    elif name == "list_epics":
        return stack_api("GET", "/api/epics", params={"projectId": args["projectId"]})
    elif name == "get_epic":
        return stack_api("GET", f"/api/epics/{args['id']}")

    # 사용자/엔지니어
    elif name == "list_engineers":
        return stack_api("GET", "/api/users/engineers")
    elif name == "list_user_names":
        return stack_api("GET", "/api/users/names")

    # 댓글
    elif name == "list_comments":
        return stack_api("GET", "/api/comments", params={"targetType": args["targetType"], "targetId": args["targetId"]})
    elif name == "create_comment":
        body = {"targetType": args["targetType"], "targetId": args["targetId"], "content": args["content"]}
        if args.get("parentId"):
            body["parentId"] = args["parentId"]
        return stack_api("POST", "/api/comments", body=body)

    # 라벨
    elif name == "list_labels":
        return stack_api("GET", "/api/labels")
    elif name == "get_label":
        return stack_api("GET", f"/api/labels/{args['id']}")

    # 라이선스
    elif name == "list_licenses":
        return stack_api("GET", "/api/licenses", params=args)
    elif name == "get_license":
        return stack_api("GET", f"/api/licenses/{args['id']}")
    elif name == "get_license_stats":
        return stack_api("GET", "/api/licenses/stats")

    # 유지보수 영업 담당자
    elif name == "list_sales_managers":
        return stack_api("GET", "/api/maintenance-contracts/sales-managers")

    # 서버 확장
    elif name == "search_servers":
        return stack_api("GET", "/api/servers/search", params={"customerId": args["customerId"], "keyword": args["keyword"]})
    elif name == "get_server_count":
        return stack_api("GET", "/api/servers/count", params={"customerId": args["customerId"]})

    # ─── 신규 도구 핸들러 (2026-02 추가) ───

    # 날짜 범위 점검 조회
    elif name == "get_checkups_by_date_range":
        params = {"startDate": args["startDate"], "endDate": args["endDate"]}
        if args.get("assigneeId"):
            params["assigneeId"] = args["assigneeId"]
        return stack_api("GET", "/api/maintenance/issues/date-range", params=params)

    # 만료됐는데 ACTIVE인 계약
    elif name == "get_expired_active_contracts":
        return stack_api("GET", "/api/integrated-customer/contracts/expired-active")

    # 갱신 누락 계약
    elif name == "get_contract_renewal_gaps":
        params = {}
        if args.get("daysAhead"):
            params["daysAhead"] = args["daysAhead"]
        return stack_api("GET", "/api/integrated-customer/contract-renewal-gaps", params=params)

    # 계약 만료 처리
    elif name == "expire_maintenance_contract":
        return stack_api("POST", f"/api/maintenance-contracts/{args['contractId']}/expire")

    # 업무요청 수정
    elif name == "update_request_job":
        rid = args.pop("id")
        return stack_api("PUT", f"/api/requestJob/{rid}", body=args)

    # 업무요청 상태 변경
    elif name == "change_request_job_status":
        return stack_api("PATCH", f"/api/requestJob/{args['id']}/status", body={"status": args["status"]})

    # 업무요청 삭제
    elif name == "delete_request_job":
        return stack_api("DELETE", f"/api/requestJob/{args['id']}")

    # 통합 고객 카드
    elif name == "get_customer_card":
        return stack_api("GET", f"/api/integrated-customer/customer-card/{args['customerId']}")

    # 유지보수 고객 검색
    elif name == "search_maintenance_customer":
        return stack_api("GET", "/api/integrated-customer/search/maintenance", params={"query": args["query"]})

    # 프로젝트 멤버
    elif name == "get_project_members":
        return stack_api("GET", f"/api/projects/{args['projectId']}/members")

    # 고객사별 업무요청
    elif name == "get_customer_request_jobs":
        return stack_api("GET", f"/api/customers/{args['customerId']}/request-jobs")

    return {"error": f"Unknown tool: {name}"}


def truncate_json(data, max_len=None):
    if max_len is None:
        max_len = TRUNCATE_MAX_LEN
    """JSON을 max_len 이하로 잘라서 반환"""
    s = json.dumps(data, ensure_ascii=False, default=str)
    if len(s) <= max_len:
        return s
    return s[:max_len] + "... (truncated)"


# ─── Reflection (결과 검증) 함수 ───

def _result_has_data(content):
    """도구 결과에 유의미한 데이터가 있는지 판별"""
    if not content:
        return False
    s = str(content)
    # 빈 결과 패턴
    empty_patterns = [
        '"data": []', '"data":[]', '"items": []', '"items":[]',
        '"matches": []', '"matches":[]', '"total": 0', '"total":0',
        '"count": 0', '"count":0', '[]', '{}',
    ]
    s_stripped = s.replace(" ", "").lower()
    for pat in empty_patterns:
        if s_stripped == pat.replace(" ", "").lower():
            return False
    # JSON 파싱 시도
    try:
        parsed = json.loads(s) if isinstance(content, str) else content
        if isinstance(parsed, dict):
            if parsed.get("error"):
                return False
            data = parsed.get("data")
            if data is not None:
                if isinstance(data, list) and len(data) == 0:
                    return False
                if isinstance(data, dict) and data.get("items") is not None and len(data["items"]) == 0:
                    return False
            items = parsed.get("items")
            if items is not None and isinstance(items, list) and len(items) == 0:
                return False
        elif isinstance(parsed, list) and len(parsed) == 0:
            return False
    except (json.JSONDecodeError, TypeError):
        pass
    return True


def _collect_tool_history(oai_messages):
    """메시지 히스토리에서 도구 호출/결과 요약 추출"""
    history = []
    for msg in oai_messages:
        # assistant 메시지의 tool_calls
        if hasattr(msg, 'tool_calls') and msg.tool_calls:
            for tc in msg.tool_calls:
                entry = {
                    "tool": tc.function.name,
                    "args": tc.function.arguments[:200] if tc.function.arguments else "",
                    "call_id": tc.id,
                    "has_data": None,
                }
                history.append(entry)
        # tool 결과 메시지
        if isinstance(msg, dict) and msg.get("role") == "tool":
            call_id = msg.get("tool_call_id", "")
            content = msg.get("content", "")
            has_data = _result_has_data(content)
            # 해당 call_id와 매칭
            for entry in history:
                if entry["call_id"] == call_id:
                    entry["has_data"] = has_data
                    entry["result_preview"] = content[:300] if content else ""
                    break
    return history


def _verify_response(instruction, response, oai_messages, chat_id):
    """
    OpenAI에 검증 요청 → pass이면 None, fail이면 재시도 후 새 응답 반환.

    Quick-Pass 규칙으로 70% 요청은 추가 API 호출 없이 통과.
    """
    tool_history = _collect_tool_history(oai_messages)

    if not tool_history:
        return None  # 도구 호출이 없었으면 검증 불필요

    # ── Quick-Pass 규칙 ──
    called_tools = {h["tool"] for h in tool_history}
    all_have_data = all(h.get("has_data", True) for h in tool_history)
    any_empty = any(h.get("has_data") is False for h in tool_history)
    used_write_tool = bool(called_tools & WRITE_TOOLS)

    # 규칙 1: 쓰기 작업 → 빈 결과가 실패가 아님
    if used_write_tool:
        log("[reflection] Quick-Pass: 쓰기 작업 → 검증 스킵")
        return None

    # 규칙 2: 모든 도구가 데이터 반환 + 응답 200자 이상
    if all_have_data and len(response) >= 200:
        log("[reflection] Quick-Pass: 모든 도구 데이터 있음 + 응답 충분 → 검증 스킵")
        return None

    # 규칙 3: 빈 결과 없음 + 응답 100자 이상
    if not any_empty and len(response) >= 100:
        log("[reflection] Quick-Pass: 빈 결과 없음 + 응답 100자 이상 → 검증 스킵")
        return None

    # 규칙 4: 도구가 "없습니다" 명시적 메시지 반환 + 응답도 "없" 포함 (특정 기간 조회 시 빈 결과 = 정답)
    tool_returned_empty_msg = any("없습니다" in str(h.get("result_preview", "")) for h in tool_history)
    response_says_none = "없" in response and len(response) >= 30
    if tool_returned_empty_msg and response_says_none:
        log("[reflection] Quick-Pass: 도구가 '없습니다' 반환 + 응답 확인 → 검증 스킵")
        return None

    # ── 검증 API 호출 ──
    log(f"[reflection] 검증 시작 (도구 {len(tool_history)}개, 응답 {len(response)}자)")

    tool_summary = "\n".join([
        f"- {h['tool']}({h['args'][:100]}): {'데이터 있음' if h.get('has_data') else '빈 결과/오류'}"
        for h in tool_history
    ])

    verify_prompt = f"""다음 사용자 질문에 대해 AI 비서가 도구를 호출하고 답변을 생성했습니다. 답변의 품질을 검증해주세요.

[사용자 질문]
{instruction[:500]}

[호출된 도구 및 결과]
{tool_summary}

[생성된 답변]
{response[:1000]}

검증 기준:
1. 질문에 관련된 데이터를 실제로 찾았는가?
2. 빈 결과를 받았는데 "찾을 수 없습니다"로 포기하지 않았는가?
3. 다른 도구로 재시도하면 더 나은 결과를 얻을 수 있는가?
4. 답변의 날짜/기간/월이 사용자가 요청한 것과 일치하는가? (예: "5월 만료"인데 4월 데이터를 보여주면 fail)
5. 데이터가 있지만 질문과 무관한 결과를 보여주고 있지 않은가?

응답 형식 (반드시 JSON):
- 통과: {{"verdict": "pass"}}
- 재시도 필요: {{"verdict": "fail", "reason": "이유", "retry_tool": "대체도구명", "retry_args": {{...}}}}

주의: 특정 월/기간 만료 계약을 물을 때 결과가 없으면 "해당 기간에 없다"가 정답일 수 있음. 이 경우 verdict=pass.
get_expiring_maintenance는 D-60 범위만 반환하므로 특정 월 검색 재시도에 절대 사용 금지.

도구 이름은 반드시 다음 중 하나: list_maintenance_contracts, list_customers, search_similar_customers, search_integrated_customer, list_maintenance_issues, get_pending_checkups, get_current_month_checkups, get_maintenance_plan, list_servers, search_servers, search_expiring_contracts, search_maintenance_customer"""

    try:
        verify_response = client.chat.completions.create(
            model=REFLECTION_MODEL,
            messages=[{"role": "user", "content": verify_prompt}],
            temperature=0.1,
            max_tokens=500,
        )
        verify_text = verify_response.choices[0].message.content or ""
        log(f"[reflection] 검증 응답: {verify_text[:200]}")

        # JSON 파싱 (중첩 JSON 대응)
        verdict = None
        # 방법 1: "verdict" 포함하는 가장 바깥쪽 JSON 블록 추출
        import re
        # ```json ... ``` 블록 우선 시도
        code_block = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', verify_text, re.DOTALL)
        if code_block:
            try:
                verdict = json.loads(code_block.group(1))
            except json.JSONDecodeError:
                pass
        # 방법 2: 전체 텍스트에서 JSON 객체 추출
        if verdict is None:
            # { 부터 마지막 } 까지 시도 (greedy)
            brace_match = re.search(r'\{.*\}', verify_text, re.DOTALL)
            if brace_match:
                try:
                    verdict = json.loads(brace_match.group())
                except json.JSONDecodeError:
                    pass
        # 방법 3: 단순 flat JSON
        if verdict is None:
            flat_match = re.search(r'\{[^{}]*"verdict"[^{}]*\}', verify_text)
            if flat_match:
                try:
                    verdict = json.loads(flat_match.group())
                except json.JSONDecodeError:
                    pass
        if verdict is None or "verdict" not in verdict:
            log("[reflection] 검증 JSON 파싱 실패 → 통과 처리")
            return None

        if verdict.get("verdict") == "pass":
            log("[reflection] 검증 통과")
            return None

        # ── 재시도 ──
        retry_tool = verdict.get("retry_tool", "")
        retry_args = verdict.get("retry_args", {})
        reason = verdict.get("reason", "")
        log(f"[reflection] 검증 실패: {reason} → 재시도: {retry_tool}({retry_args})")

        if not retry_tool:
            # 검증 실패했지만 대체 도구 없음 → fallback 맵 활용
            for h in tool_history:
                if not h.get("has_data") and h["tool"] in TOOL_FALLBACK_MAP:
                    retry_tool = TOOL_FALLBACK_MAP[h["tool"]][0]
                    # 원래 도구의 인자를 기반으로 추론
                    try:
                        original_args = json.loads(h["args"]) if h["args"] else {}
                    except json.JSONDecodeError:
                        original_args = {}
                    retry_args = original_args
                    log(f"[reflection] Fallback 맵 사용: {h['tool']} → {retry_tool}")
                    break

        if not retry_tool:
            log("[reflection] 대체 도구 없음 → 원본 응답 유지")
            return None

        return _execute_retry(instruction, retry_tool, retry_args, oai_messages, chat_id)

    except Exception as e:
        log(f"[reflection] 검증 중 오류: {e} → 원본 응답 유지")
        return None


def _execute_retry(instruction, tool_name, tool_args, oai_messages, chat_id):
    """대체 도구 실행 → 응답 재생성"""
    log(f"[reflection] 재시도 실행: {tool_name}({tool_args})")

    try:
        # 진행 알림
        try:
            _send_message_impl(chat_id, "🔄 추가 검색 중...")
        except Exception:
            pass

        # 도구 실행
        result = execute_tool(tool_name, tool_args)
        result_str = truncate_json(result)

        if not _result_has_data(result_str):
            log(f"[reflection] 재시도 도구도 빈 결과 → 원본 응답 유지")
            return None

        log(f"[reflection] 재시도 데이터 확보 (len={len(result_str)})")

        # 응답 재생성
        regenerate_prompt = f"""이전에 사용자 질문에 답변하려 했으나 데이터가 부족했습니다.
추가 도구 호출로 새로운 데이터를 확보했습니다. 이 데이터를 포함하여 사용자 질문에 정확히 답변해주세요.

[사용자 질문]
{instruction[:500]}

[추가 도구: {tool_name}]
{result_str[:3000]}

규칙:
1. 한국어로, 핵심만 간결하게 정리
2. 고객사별로 그룹핑
3. 담당자 이름 표시 (개인명이 없으면 "정보 없음"으로 표시, 팀명만 있으면 팀명 표시)
4. 영문 enum은 한국어로 번역 (ACTIVE=활성, QUARTERLY=분기 등)
5. UUID는 표시하지 마세요
6. 중요: 질문에서 요청한 날짜/기간에 해당하는 데이터만 포함. 해당 기간 데이터가 없으면 "해당 기간에 만료 계약이 없습니다"라고 명확히 안내하고, 가장 가까운 시기의 데이터를 참고로 안내"""

        regen_response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": regenerate_prompt}],
            temperature=0.3,
            max_tokens=OPENAI_MAX_TOKENS,
        )
        new_response = regen_response.choices[0].message.content or ""

        if new_response and len(new_response) > 50:
            log(f"[reflection] 응답 재생성 성공 (len={len(new_response)})")
            return new_response
        else:
            log("[reflection] 재생성 응답이 너무 짧음 → 원본 유지")
            return None

    except Exception as e:
        log(f"[reflection] 재시도 중 오류: {e} → 원본 응답 유지")
        return None


# ─── 공유 메시지 처리 로직 ───
def _handle_messages(pending):
    """
    Feature Flag에 따라 Legacy 또는 LangGraph Agent로 분기한다.
    """
    if AGENT_GRAPH_ENABLED:
        return _handle_messages_graph(pending)
    return _handle_messages_legacy(pending)


def _handle_messages_graph(pending):
    """
    LangGraph StateGraph 기반 메시지 처리.
    기존 로직을 agent/ 패키지의 그래프로 대체한다.
    """
    import traceback

    try:
        from agent import compile_graph
        from agent.state import create_initial_state
    except ImportError as e:
        log(f"[bot_brain] agent 패키지 import 실패, legacy로 fallback: {e}")
        return _handle_messages_legacy(pending)

    # 1. 여러 메시지 합산
    log("[bot_brain] _handle_messages_graph: calling combine_tasks()...")
    try:
        combined = combine_tasks(pending)
    except Exception as e:
        log(f"[bot_brain] combine_tasks() CRASHED: {e}")
        log(traceback.format_exc())
        return False

    if not combined:
        log("[bot_brain] combine_tasks() returned None")
        return False

    chat_id = combined["chat_id"]
    instruction = combined["combined_instruction"]
    message_ids = combined["message_ids"]

    log(f"[bot_brain] _handle_messages_graph: Processing {len(message_ids)} messages (IDs: {message_ids})")

    # 2. 즉시 답장 (비동기)
    def _send_ack():
        try:
            if len(message_ids) > 1:
                _send_message_impl(chat_id, f"확인했습니다! (총 {len(message_ids)}개 요청 합산 처리)")
            else:
                _send_message_impl(chat_id, "확인했습니다! 처리 중...")
        except Exception as e:
            log(f"[bot_brain] _handle_messages_graph: ack send FAILED: {e}")
    ack_thread = threading.Thread(target=_send_ack, daemon=True)
    ack_thread.start()

    # 3. 작업 잠금
    try:
        lock_ok = create_working_lock(message_ids, instruction)
    except Exception as e:
        log(f"[bot_brain] create_working_lock() CRASHED: {e}")
        return False

    if not lock_ok:
        log("[bot_brain] _handle_messages_graph: Lock failed - another task in progress")
        return False

    try:
        # 4. 초기 상태 구성
        initial_state = create_initial_state(
            instruction=instruction,
            chat_id=chat_id,
            message_ids=message_ids,
            context_24h=combined.get("context_24h", ""),
            files=combined.get("files", []),
            sender_email=combined.get("sender_email", ""),
            user_name=combined.get("user_name", ""),
            all_timestamps=combined.get("all_timestamps", []),
        )

        # 5. 그래프 컴파일 + 실행
        log("[bot_brain] _handle_messages_graph: compiling and invoking graph...")
        graph = compile_graph()
        final_state = graph.invoke(initial_state)
        log(f"[bot_brain] _handle_messages_graph: graph completed. "
            f"response_len={len(final_state.get('final_response', ''))}")

        # 6. 새 메시지 확인 (기존과 동일)
        try:
            from chat_bot import check_new_messages_during_work, save_new_instructions
            new_msgs = check_new_messages_during_work()
            if new_msgs:
                save_new_instructions(new_msgs)
                log(f"[bot_brain] _handle_messages_graph: {len(new_msgs)} new messages detected")
        except Exception as e:
            log(f"[bot_brain] new message check failed (non-fatal): {e}")

    except Exception as e:
        log(f"[bot_brain] _handle_messages_graph CRASHED: {e}")
        log(traceback.format_exc())
        try:
            _send_message_impl(chat_id, f"처리 중 오류가 발생했습니다: {e}")
        except Exception:
            log("[bot_brain] error notification send also FAILED")
    finally:
        # deliver_node가 이미 remove_working_lock()을 호출하지만,
        # 예외 발생 시 여기서도 안전하게 정리한다.
        try:
            import os as _os
            lock_path = _os.path.join(BASE_DIR, "working.json")
            if _os.path.exists(lock_path):
                remove_working_lock()
        except Exception as e:
            log(f"[bot_brain] _handle_messages_graph: cleanup lock FAILED: {e}")

    return True


def _handle_messages_legacy(pending):
    """
    pending 메시지 리스트를 받아 OpenAI로 처리하고 결과를 Google Chat으로 전송.
    process_messages()와 run_loop() 모두 이 함수를 호출한다.

    Returns:
        True  - 메시지를 처리했음 (성공 또는 오류 후 복구)
        False - 잠금 실패 등으로 처리하지 못했음
    """
    import traceback

    # 2. 여러 메시지 합산
    log("[bot_brain] _handle_messages: calling combine_tasks()...")
    try:
        combined = combine_tasks(pending)
    except Exception as e:
        log(f"[bot_brain] combine_tasks() CRASHED: {e}")
        log(traceback.format_exc())
        return False

    chat_id = combined['chat_id']
    instruction = combined['combined_instruction']
    message_ids = combined['message_ids']

    log(f"[bot_brain] _handle_messages: Processing {len(message_ids)} messages (IDs: {message_ids})")

    # 3. 즉시 답장 (비동기 — 전송 완료를 기다리지 않음)
    log("[bot_brain] _handle_messages: sending ack to chat (async)...")
    def _send_ack():
        try:
            if len(message_ids) > 1:
                _send_message_impl(chat_id, f"확인했습니다! (총 {len(message_ids)}개 요청 합산 처리)")
            else:
                _send_message_impl(chat_id, "확인했습니다! 처리 중...")
            log("[bot_brain] _handle_messages: ack sent OK (async)")
        except Exception as e:
            log(f"[bot_brain] _handle_messages: ack send FAILED: {e}")
    ack_thread = threading.Thread(target=_send_ack, daemon=True)
    ack_thread.start()

    # 4. 작업 잠금
    log("[bot_brain] _handle_messages: creating working lock...")
    try:
        lock_ok = create_working_lock(message_ids, instruction)
    except Exception as e:
        log(f"[bot_brain] create_working_lock() CRASHED: {e}")
        log(traceback.format_exc())
        return False

    if not lock_ok:
        log("[bot_brain] _handle_messages: Lock failed - another task in progress")
        return False

    try:
        # 5. 메모리 예약
        log("[bot_brain] _handle_messages: reserving memory...")
        try:
            reserve_memory_chat(instruction, chat_id, combined['all_timestamps'], message_ids)
            log("[bot_brain] _handle_messages: memory reserved OK")
        except Exception as e:
            log(f"[bot_brain] reserve_memory_chat() CRASHED: {e}")
            log(traceback.format_exc())
            # 메모리 예약 실패해도 처리는 계속

        # 6. 기존 메모리 로드 (인덱스 기반 - 구조화된 데이터)
        log("[bot_brain] _handle_messages: loading memory index...")
        memory_context = ""
        try:
            all_tasks = search_memory()  # 인수 없이 호출 -> 전체 목록
            if all_tasks:
                recent = all_tasks[:10]  # 최신 10개 (이미 역순 정렬됨)
                lines = []
                for m in recent:
                    inst = m.get('instruction', '')[:80]
                    if "(합산됨)" not in inst and inst:
                        lines.append(f"- {inst}")
                if lines:
                    memory_context = "\n\n[이전 작업 기록 - 참고용, 데이터는 반드시 도구로 재조회할 것]\n" + "\n".join(lines)
            log(f"[bot_brain] _handle_messages: memory loaded ({len(all_tasks) if all_tasks else 0} tasks)")
        except Exception as e:
            log(f"[bot_brain] search_memory() CRASHED: {e}")
            log(traceback.format_exc())
            # 메모리 로드 실패해도 처리는 계속

        # 7. 24시간 대화 컨텍스트 (combine_tasks에서 이미 생성됨)
        context_24h = combined.get('context_24h', '')

        # 7.5. 사용자 신원 확인 (UUID 조회)
        user_identity_context = ""
        try:
            sender_email = combined.get('sender_email', '')
            user_name = combined.get('user_name', '')
            identity = _lookup_user_identity(sender_email, user_name)
            if identity:
                user_identity_context = f"""

현재 사용자: {identity['name']} ({identity['email']})
사용자 UUID: {identity['uuid']}
"내", "나의", "내꺼", "내 것" 등 본인 관련 질문 시 assigneeId, salesManagerId, engineerId 등에 이 UUID를 사용하여 필터링하세요."""
                log(f"[identity] 시스템 프롬프트에 주입: {identity['name']} ({identity['uuid'][:8]}...)")
        except Exception as e:
            log(f"[identity] 주입 실패 (무시): {e}")

        # 8. OpenAI API 호출 (function calling loop)
        system_prompt = f"""당신은 '{BOT_NAME}', 업무 비서 AI입니다.
사용자의 요청을 정확히 처리하고, 결과를 간결하고 명확하게 보고합니다.

현재 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{user_identity_context}

사용 가능한 도구:
- STACK 시스템: 프로젝트/이슈/업무요청/고객사/유지보수계약/정기점검/서버 데이터 조회 및 관리
- 이메일 발송, 만료 계약 알림
- 이전 작업 기록 검색

도구 선택 가이드:
- 계약 정보/유지보수 계약/특정 고객 계약 → list_maintenance_contracts (search로 고객명 검색)
- 특정 월에 종료되는 계약 → list_maintenance_contracts (contractEndMonth 파라미터 사용, 예: "2026-03")
- get_expiring_maintenance는 오직 "만료 임박/곧 만료" 질문에만 사용 (D-60 기본)
- 고객사 정보/고객 검색 → search_similar_customers 또는 list_customers (search 파라미터)
- Salesforce 거래처/영업 정보 → search_integrated_customer (Salesforce에 없는 고객은 조회 불가)
- 이번 달 점검 → get_current_month_checkups
- 다음 달/특정 월 점검 → get_checkups_by_date_range(startDate, endDate, assigneeId) 사용. 예: 3월 점검 → startDate="2026-03-01", endDate="2026-03-31"
- 미완료/지연 점검 → get_pending_checkups(assignee=UUID) — assigneeId 필수!
- "내 점검" 등 본인 관련 → assigneeId에 사용자 UUID 전달
- 만료됐는데 ACTIVE인 계약 → get_expired_active_contracts 또는 list_maintenance_contracts(isExpiredButActive=true)
- 갱신 누락 감지 → get_contract_renewal_gaps
- 통합 고객 정보 → get_customer_card(customerId) 또는 search_maintenance_customer(query)
- 첫 번째 도구가 결과 없으면, 다른 도구로 재시도하세요. 예: search_integrated_customer 실패 → list_maintenance_contracts로 재검색

사고 프로토콜:
- 복잡한 질문을 받으면, 먼저 어떤 정보가 필요한지 생각하세요.
- 첫 번째 도구 결과가 부족하면, 다른 도구로 보완하세요.
- 여러 데이터를 조합해야 하면, 단계적으로 수집한 후 종합하세요.
- 결과가 비어있으면 "없습니다"로 끝내지 말고, 대체 도구를 시도하세요.

규칙:
1. **[최우선] 매번 반드시 도구를 호출하여 최신 데이터를 조회하세요.** 이전 대화 내역이나 [이전 작업 기록]의 데이터를 절대 재사용하지 마세요. 같은 질문이 반복되더라도 항상 새로 API를 호출해야 합니다. 도구 호출 없이 데이터를 답변하는 것은 금지됩니다.
2. **[중요] 답변은 오직 이번 턴에서 호출한 도구의 결과만 사용하세요.** 이전 대화에 나온 데이터(Salesforce 결과, 금액, 이전 API 응답 등)를 현재 답변에 절대 포함하지 마세요. 도구 결과에 없는 데이터는 답변에 넣지 마세요.
3. 결과는 한국어로, 핵심만 간결하게 정리하세요.
4. 고객사별로 그룹핑하여 보기 좋게 정리하세요.
5. 담당자 이름이 있으면 표시하세요.
6. 목록이 많으면 중요한 것 위주로 요약하고, 전체 수량도 알려주세요.
7. 오류가 발생하면 어떤 오류인지 간단히 설명하세요.
8. 고객사 ID(UUID)가 결과에 포함되면, 반드시 get_customer 또는 get_maintenance_contract로 고객사명을 조회해서 이름으로 표시하세요. UUID를 사용자에게 그대로 보여주지 마세요.
9. 모든 관련 데이터를 빠짐없이 보고하세요. "총 10개" 라면 10개 모두 표시하세요.
10. API 응답의 영문 enum 값은 반드시 한국어로 번역하세요:
   - 점검주기: MONTHLY=월간, QUARTERLY=분기, SEMI_ANNUALLY=반기, ANNUALLY=연간, REQUEST=요청시, PARTNER=파트너
   - 상태: ACTIVE=활성, EXPIRED=만료, PENDING=대기, COMPLETED=완료, IN_PROGRESS=진행중
   - 우선순위: HIGH=높음, MEDIUM=보통, LOW=낮음
   - 기타 영문 코드도 자연스러운 한국어로 변환하세요.
{memory_context}"""

        oai_messages = [
            {"role": "system", "content": system_prompt},
        ]

        if context_24h and context_24h != "최근 24시간 이내 대화 내역이 없습니다.":
            oai_messages.append({"role": "user", "content": f"[최근 대화 참고]\n{context_24h}"})

        oai_messages.append({"role": "user", "content": instruction})

        # ─── 복잡도 평가 ───
        complexity_score, complexity_level = _assess_complexity(instruction)
        log(f"[agent] 복잡도: {complexity_score}점 ({complexity_level})")

        # ─── A+B: Fast Path (SIMPLE만: 패턴 매칭 → 도구 직접 호출 → 경량 모델로 응답) ───
        final_response = ""
        fast_match = None
        if complexity_level == "SIMPLE":
            fast_match = _fast_path_match(instruction, identity)
        if fast_match:
            fp_tool, fp_args = fast_match
            log(f"[fast-path] 매칭 성공: {fp_tool}({fp_args})")
            try:
                fp_result = execute_tool(fp_tool, fp_args)
                fp_result_str = truncate_json(fp_result)
                log(f"[fast-path] 도구 결과 len={len(fp_result_str)}, preview={fp_result_str[:200]}")

                # instruction에서 순수 질문만 추출 (24h 컨텍스트 제거)
                fp_question = instruction.strip()
                if "\n---\n" in fp_question:
                    fp_question = fp_question.split("\n---\n")[0].strip()
                import re as _re_fp
                _req = _re_fp.search(r"\[요청\s*\d+\].*?\n(.+)", fp_question, _re_fp.DOTALL)
                if _req:
                    fp_question = _req.group(1).strip()

                fp_prompt = f"""현재 시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}{user_identity_context}

[질문]
{fp_question[:300]}

[도구 결과: {fp_tool}]
{fp_result_str}

중요: 반드시 위 [도구 결과]의 데이터만 사용하여 답변하세요. 이전 대화 내용이나 다른 출처의 정보는 절대 사용하지 마세요.
도구 결과에 데이터가 없거나 빈 배열이면 "해당 기간에 해당하는 건이 없습니다"라고 명확히 안내하세요.
위 결과를 한국어로 간결하게 정리하세요. 고객사별 그룹핑, 담당자 표시, UUID 숨김."""

                fp_response = client.chat.completions.create(
                    model=FAST_MODEL,
                    messages=[
                        {"role": "system", "content": FAST_SYSTEM_PROMPT},
                        {"role": "user", "content": fp_prompt},
                    ],
                    temperature=0.3,
                    max_tokens=OPENAI_MAX_TOKENS,
                )
                final_response = fp_response.choices[0].message.content or ""
                log(f"[fast-path] 응답 생성 완료 (len={len(final_response)}, model={FAST_MODEL})")

                # Fast Path 실패 시 (응답 너무 짧으면) 기존 flow로 fallback
                if len(final_response) < 20:
                    log("[fast-path] 응답 너무 짧음 → 기존 flow로 fallback")
                    final_response = ""
            except Exception as e:
                log(f"[fast-path] 실행 실패 → 기존 flow로 fallback: {e}")
                final_response = ""

        # ─── Agent Planning (COMPLEX만) ───
        execution_plan = None
        if not final_response and complexity_level == "COMPLEX" and AGENT_PLANNING_ENABLED:
            log("[agent] COMPLEX 쿼리 → 실행 계획 생성 중...")
            try:
                execution_plan = _generate_plan(instruction, identity, TOOLS)
                if execution_plan:
                    plan_text = "\n".join(
                        f"  {s['step']}. {s['purpose']} (도구: {s['tool']})"
                        for s in execution_plan
                    )
                    log(f"[agent] 실행 계획:\n{plan_text}")

                    # 사용자에게 계획 공유
                    try:
                        _send_message_impl(chat_id, f"📋 실행 계획:\n{plan_text}\n\n처리를 시작합니다...")
                    except Exception:
                        pass

                    # 시스템 프롬프트에 계획 주입
                    plan_guidance = f"""

[실행 계획 - 반드시 모든 단계를 실행하세요]
아래 계획의 모든 단계를 순서대로 실행하세요. 단계를 건너뛰지 마세요.
{plan_text}

[분석 지침]
모든 도구 호출이 끝나면 반드시 다음을 포함하여 종합 분석하세요:
- 핵심 통계 (총 건수, 상태별 비율, 완료율 등)
- 주의 필요 항목 (만료 임박, 미완료 점검, 이상 데이터 등)
- 데이터 간 교차 분석 (계약은 있는데 점검이 없는 경우 등)
단순 나열이 아닌 인사이트와 요약을 제공하세요.
"""
                    oai_messages[0]["content"] += plan_guidance
                else:
                    log("[agent] 계획 생성 실패 → 기존 FC 루프로 진행")
            except Exception as e:
                log(f"[agent] 계획 생성 실패 (무시): {e}")

        # ─── OpenAI Function Calling (Fast Path 미매칭 or fallback) ───
        if not final_response:
            log("[bot_brain] _handle_messages: starting OpenAI function calling loop...")
            for turn in range(MAX_TOOL_TURNS):
                # 첫 턴: 반드시 도구 호출 강제 / 이후: auto
                tc = "required" if turn == 0 else "auto"
                log(f"[bot_brain] _handle_messages: OpenAI turn {turn+1}/{MAX_TOOL_TURNS} (tool_choice={tc})...")
                try:
                    response = client.chat.completions.create(
                        model=OPENAI_MODEL,
                        messages=oai_messages,
                        tools=TOOLS,
                        tool_choice=tc,
                        temperature=0.3,
                        max_tokens=OPENAI_MAX_TOKENS,
                    )
                    log(f"[bot_brain] _handle_messages: OpenAI turn {turn+1} response OK")
                except Exception as e:
                    final_response = f"OpenAI API 오류: {e}"
                    log(f"[bot_brain] OpenAI API error on turn {turn+1}: {e}")
                    log(traceback.format_exc())
                    break

                choice = response.choices[0]
                msg = choice.message

                # 도구 호출이 없으면 최종 응답
                if not msg.tool_calls:
                    final_response = msg.content or ""
                    log(f"[bot_brain] _handle_messages: final response received (len={len(final_response)})")
                    break

                # 도구 호출 처리
                oai_messages.append(msg)
                log(f"[bot_brain] _handle_messages: {len(msg.tool_calls)} tool call(s) on turn {turn+1}")

                for tool_call in msg.tool_calls:
                    fn_name = tool_call.function.name
                    try:
                        fn_args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
                    except json.JSONDecodeError:
                        fn_args = {}

                    log(f"[bot_brain] Tool call: {fn_name}({fn_args})")
                    try:
                        result = execute_tool(fn_name, fn_args)
                    except Exception as e:
                        log(f"[bot_brain] execute_tool({fn_name}) CRASHED: {e}")
                        log(traceback.format_exc())
                        result = {"error": f"Tool execution failed: {e}"}
                    result_str = truncate_json(result)

                    oai_messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result_str,
                    })

                    # ─── Agent: 단계별 검증 (COMPLEX만) ───
                    if execution_plan and complexity_level == "COMPLEX":
                        step_ok, suggestion = _verify_step_result(fn_name, fn_args, result, instruction)
                        if not step_ok and suggestion:
                            log(f"[agent] 단계 검증 실패: {fn_name} → {suggestion}")
                            oai_messages.append({
                                "role": "user",
                                "content": f"[시스템 힌트] {fn_name} 결과가 비어있습니다. {suggestion}",
                            })

                # 중간 경과 보고
                if execution_plan and turn > 0:
                    step_idx = min(turn + 1, len(execution_plan))
                    try:
                        _send_message_impl(chat_id, f"📊 {step_idx}/{len(execution_plan)} 단계 완료...")
                    except Exception:
                        pass
                elif turn == 1:
                    try:
                        _send_message_impl(chat_id, "데이터 분석 중...")
                    except Exception as e:
                        log(f"[bot_brain] progress message send FAILED: {e}")

        # 8.5. 응답 검증 (Reflection)
        if final_response and REFLECTION_ENABLED:
            try:
                verified = _verify_response(instruction, final_response, oai_messages, chat_id)
                if verified:
                    log(f"[reflection] 응답 교체: {len(final_response)}자 → {len(verified)}자")
                    final_response = verified
            except Exception as e:
                log(f"[reflection] 검증 중 예외 (무시): {e}")

        # 9. 결과 전송
        if not final_response:
            final_response = "처리를 완료했으나 응답을 생성하지 못했습니다."

        log("[bot_brain] _handle_messages: sending report_chat()...")
        try:
            report_chat(
                instruction,
                result_text=final_response,
                chat_id=chat_id,
                timestamp=combined['all_timestamps'],
                message_id=message_ids,
            )
            log("[bot_brain] _handle_messages: report_chat() OK")
        except Exception as e:
            log(f"[bot_brain] report_chat() CRASHED: {e}")
            log(traceback.format_exc())
            # 최소한 원본 메시지라도 전송 시도
            try:
                _send_message_impl(chat_id, final_response[:4000])
            except Exception:
                log("[bot_brain] fallback _send_message_impl also FAILED")

        # 10. 처리 완료
        log("[bot_brain] _handle_messages: marking done...")
        try:
            mark_done_chat(message_ids)
            log("[bot_brain] _handle_messages: mark_done OK")
        except Exception as e:
            log(f"[bot_brain] mark_done_chat() CRASHED: {e}")
            log(traceback.format_exc())

        log(f"[bot_brain] Done. Response length: {len(final_response)}")

    except Exception as e:
        log(f"[bot_brain] _handle_messages UNEXPECTED error: {e}")
        log(traceback.format_exc())
        # 오류 발생 시 사용자에게 알림
        try:
            _send_message_impl(chat_id, f"처리 중 오류가 발생했습니다: {e}")
        except Exception:
            log("[bot_brain] error notification send also FAILED")
    finally:
        # 반드시 잠금 해제
        log("[bot_brain] _handle_messages: removing working lock...")
        try:
            remove_working_lock()
        except Exception as e:
            log(f"[bot_brain] remove_working_lock() CRASHED: {e}")

    return True


# ─── 메인 처리 (단발 실행) ───
def process_messages():
    """대기 중인 Google Chat 메시지를 OpenAI로 처리 (단발 실행용)"""

    # API 키 검증
    if not OPENAI_API_KEY or OPENAI_API_KEY == "YOUR_KEY_HERE":
        log("[bot_brain] ERROR: OPENAI_API_KEY not set in .env")
        return
    if not STACK_API_KEY:
        log("[bot_brain] WARN: STACK_API_KEY not set - STACK tools will fail")

    # 1. 대기 중인 메시지 확인
    log("[bot_brain] process_messages: calling check_chat()...")
    pending = check_chat()
    if not pending:
        log("[bot_brain] No pending messages")
        # 메시지 없을 때 Proactive 체크
        if _PROACTIVE_AVAILABLE:
            try:
                run_proactive_checks()
            except Exception as e:
                log(f"[proactive] Non-fatal error: {e}")
        return

    log(f"[bot_brain] process_messages: {len(pending)} pending messages found")
    _handle_messages(pending)


def run_loop(interval=None, idle_timeout=None, daemon=False):
    """
    상시 실행 루프. interval초마다 메시지 확인 + 처리.

    daemon=False: idle_timeout초 동안 메시지 없으면 종료 (스케줄러가 재시작).
    daemon=True:  idle timeout 없이 영구 실행. 크래시 시 자동 재시작.

    이 루프는 절대로 예외로 죽지 않는다.
    SystemExit, KeyboardInterrupt를 포함한 모든 예외를 잡아 로깅한다.
    """
    import time as _time
    import traceback

    if interval is None:
        interval = BOT_LOOP_INTERVAL
    if idle_timeout is None:
        idle_timeout = BOT_IDLE_TIMEOUT

    # API 키 검증
    if not OPENAI_API_KEY or OPENAI_API_KEY == "YOUR_KEY_HERE":
        log("[bot_brain] ERROR: OPENAI_API_KEY not set in .env - loop will not start")
        return
    if not STACK_API_KEY:
        log("[bot_brain] WARN: STACK_API_KEY not set - STACK tools will fail")

    mode_str = "DAEMON" if daemon else "LOOP"
    if daemon:
        idle_timeout = 0  # 데몬: idle timeout 비활성화
        log(f"[bot_brain] {mode_str} started (interval={interval}s, no idle timeout, pid={os.getpid()})")
    else:
        log(f"[bot_brain] {mode_str} started (interval={interval}s, idle_timeout={idle_timeout}s, pid={os.getpid()})")
    last_activity = _time.time()
    last_proactive = 0  # 마지막 proactive 체크 시각
    _proactive_running = False  # proactive 실행 중 플래그
    PROACTIVE_INTERVAL = 60  # proactive 체크 간격 (초)
    poll_count = 0
    consecutive_errors = 0

    while True:
        try:
            poll_count += 1
            now = _time.time()
            idle_secs = int(now - last_activity)

            # 매 iteration 로깅
            log(f"[bot_brain] Poll #{poll_count} | idle={idle_secs}s | errors={consecutive_errors}")

            # ── check_chat() ──
            log(f"[bot_brain] Poll #{poll_count} - calling check_chat()...")
            pending = None
            try:
                pending = check_chat()
                consecutive_errors = 0  # check_chat 성공 시 에러 카운트 리셋
            except Exception as cc_err:
                consecutive_errors += 1
                log(f"[bot_brain] check_chat() CRASHED (err #{consecutive_errors}): {cc_err}")
                log(traceback.format_exc())
                pending = []
                # 연속 에러 시 백오프
                if consecutive_errors >= 5:
                    backoff = min(60, interval * consecutive_errors)
                    log(f"[bot_brain] Too many consecutive errors ({consecutive_errors}), backing off {backoff}s")
                    _time.sleep(backoff)
                    continue

            pending_count = len(pending) if pending else 0
            log(f"[bot_brain] Poll #{poll_count} - check_chat() returned {pending_count} msgs")

            if pending:
                last_activity = _time.time()
                log(f"[bot_brain] Poll #{poll_count} - dispatching to _handle_messages()...")
                try:
                    _handle_messages(pending)
                except Exception as hm_err:
                    log(f"[bot_brain] _handle_messages() CRASHED: {hm_err}")
                    log(traceback.format_exc())
                    # 잠금이 남아있을 수 있으므로 강제 해제
                    try:
                        remove_working_lock()
                    except Exception:
                        pass
                log(f"[bot_brain] Poll #{poll_count} - _handle_messages() finished")
            else:
                # 메시지 없음 - idle timeout 체크
                log(f"[bot_brain] Poll #{poll_count} - no messages, idle check ({idle_secs}s/{idle_timeout}s)")

                # Proactive 체크 (메시지 없을 때, 60초 간격, 백그라운드)
                if _PROACTIVE_AVAILABLE and not _proactive_running and (_time.time() - last_proactive) >= PROACTIVE_INTERVAL:
                    def _run_proactive():
                        nonlocal _proactive_running, last_proactive
                        try:
                            run_proactive_checks()
                        except Exception as e:
                            log(f"[proactive] Non-fatal error: {e}")
                        finally:
                            last_proactive = _time.time()
                            _proactive_running = False
                    _proactive_running = True
                    threading.Thread(target=_run_proactive, daemon=True).start()

                if not daemon and idle_timeout > 0 and idle_secs > idle_timeout:
                    log(f"[bot_brain] Idle for {idle_secs}s (>{idle_timeout}s). Exiting loop normally.")
                    break

        except SystemExit as e:
            log(f"[bot_brain] SystemExit caught in loop (code={e.code}). Ignoring, loop continues.")
        except KeyboardInterrupt:
            log("[bot_brain] KeyboardInterrupt caught in loop. Ignoring, loop continues.")
        except BaseException as e:
            # BaseException catches absolutely everything including GeneratorExit etc.
            log(f"[bot_brain] UNEXPECTED BaseException in loop: {type(e).__name__}: {e}")
            try:
                log(traceback.format_exc())
            except Exception:
                pass

        # Sleep between polls
        log(f"[bot_brain] Poll #{poll_count} - sleeping {interval}s...")
        try:
            _time.sleep(interval)
            log(f"[bot_brain] Poll #{poll_count} - woke up from sleep")
        except (SystemExit, KeyboardInterrupt, BaseException) as e:
            log(f"[bot_brain] Sleep interrupted by {type(e).__name__}. Continuing loop.")

    log(f"[bot_brain] Loop exited normally after {poll_count} polls.")


def _check_duplicate_process():
    """
    Check if another bot_brain.py process is already running.
    Returns True if a duplicate is found (we should exit), False otherwise.
    """
    my_pid = os.getpid()
    try:
        import subprocess
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | "
             "Where-Object { $_.CommandLine -match 'bot_brain' } | "
             "Select-Object ProcessId, CommandLine | "
             "ForEach-Object { \"$($_.ProcessId)|$($_.CommandLine)\" }"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            log(f"[bot_brain] Duplicate check: powershell failed (rc={result.returncode})")
            return False

        lines = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
        other_pids = []
        for line in lines:
            parts = line.split("|", 1)
            if len(parts) >= 1:
                try:
                    pid = int(parts[0].strip())
                    if pid != my_pid:
                        other_pids.append(pid)
                except ValueError:
                    continue

        if other_pids:
            log(f"[bot_brain] Duplicate process detected! Other bot_brain PIDs: {other_pids}. My PID: {my_pid}. Exiting.")
            return True

        return False

    except Exception as e:
        log(f"[bot_brain] Duplicate check failed (non-fatal): {e}")
        return False


if __name__ == "__main__":
    import traceback

    try:
        log("[bot_brain] ========================================")
        log(f"[bot_brain] Starting (pid={os.getpid()}, args={sys.argv[1:]})")
        log("[bot_brain] ========================================")

        # Race condition prevention: exit if another bot_brain is already running
        if _check_duplicate_process():
            log("[bot_brain] Another bot_brain process is already running. Exiting to prevent race condition.")
            sys.exit(0)

        if "--daemon" in sys.argv:
            run_loop(daemon=True)
        elif "--loop" in sys.argv:
            run_loop()
        else:
            process_messages()
        log("[bot_brain] Main completed normally.")
    except SystemExit as e:
        log(f"[bot_brain] SystemExit (code={e.code})")
    except KeyboardInterrupt:
        log("[bot_brain] KeyboardInterrupt - shutting down")
    except Exception as e:
        log(f"[bot_brain] FATAL EXCEPTION: {type(e).__name__}: {e}")
        log(traceback.format_exc())
    except BaseException as e:
        # Catches GeneratorExit and anything else that bypasses Exception
        log(f"[bot_brain] FATAL BaseException: {type(e).__name__}: {e}")
        try:
            log(traceback.format_exc())
        except Exception:
            pass
    finally:
        log("[bot_brain] Process ending.")
