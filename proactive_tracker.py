"""
Proactive Agent 추적 모듈

알림 중복 방지 + 사용자-Space 매핑 관리.
- proactive_alerts.json — 날짜/계약/이슈별 발송 기록
- user_spaces.json — 사용자 이메일 → Google Chat space 매핑
"""

import os
import json
import threading
from datetime import datetime

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ALERTS_FILE = os.path.join(_BASE_DIR, "proactive_alerts.json")
USER_SPACES_FILE = os.path.join(_BASE_DIR, "user_spaces.json")
LOG_FILE = os.path.join(_BASE_DIR, "bot_brain.log")

# 파일 동시 접근 보호
_alerts_lock = threading.Lock()
_spaces_lock = threading.Lock()


def _log(msg):
    """로그 기록"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [proactive_tracker] {msg}\n")
            f.flush()
    except Exception:
        pass


# ─── 알림 중복 방지 ───

def _load_alerts():
    """발송 기록 로드"""
    if not os.path.exists(ALERTS_FILE):
        return {"alerts": {}}
    try:
        with open(ALERTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        _log(f"alerts.json 읽기 오류: {e}")
        return {"alerts": {}}


def _save_alerts(data):
    """발송 기록 저장"""
    try:
        with open(ALERTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        _log(f"alerts.json 저장 오류: {e}")


def is_already_sent(task_type, key):
    """
    특정 알림이 이미 발송되었는지 확인.

    Args:
        task_type: "briefing", "contract_alert", "overdue_reminder", "weekly_check"
        key: 고유 키 (예: "2026-02-19", "contract_123_D-7", "issue_456_D+3")

    Returns:
        bool: 이미 발송되었으면 True
    """
    with _alerts_lock:
        data = _load_alerts()
        alerts = data.get("alerts", {})
        task_alerts = alerts.get(task_type, {})
        return key in task_alerts


def mark_sent(task_type, key, recipients=None):
    """
    알림 발송 기록.

    Args:
        task_type: 알림 유형
        key: 고유 키
        recipients: 수신자 목록
    """
    with _alerts_lock:
        data = _load_alerts()
        if "alerts" not in data:
            data["alerts"] = {}
        if task_type not in data["alerts"]:
            data["alerts"][task_type] = {}

        data["alerts"][task_type][key] = {
            "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "recipients": recipients or [],
        }
        _save_alerts(data)
    _log(f"알림 기록: {task_type}/{key} → {recipients}")


def cleanup_old_alerts(days=60):
    """오래된 알림 기록 정리 (기본 60일)"""
    with _alerts_lock:
        data = _load_alerts()
        now = datetime.now()
        cleaned = 0

        for task_type in list(data.get("alerts", {}).keys()):
            for key in list(data["alerts"][task_type].keys()):
                entry = data["alerts"][task_type][key]
                try:
                    sent_at = datetime.strptime(entry["sent_at"], "%Y-%m-%d %H:%M:%S")
                    if (now - sent_at).days > days:
                        del data["alerts"][task_type][key]
                        cleaned += 1
                except (KeyError, ValueError):
                    pass

        if cleaned > 0:
            _save_alerts(data)
            _log(f"오래된 알림 {cleaned}개 정리")


# ─── 사용자-Space 매핑 ───

def _load_user_spaces():
    """사용자-Space 매핑 로드"""
    if not os.path.exists(USER_SPACES_FILE):
        return {"users": {}}
    try:
        with open(USER_SPACES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        _log(f"user_spaces.json 읽기 오류: {e}")
        return {"users": {}}


def _save_user_spaces(data):
    """사용자-Space 매핑 저장"""
    try:
        with open(USER_SPACES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        _log(f"user_spaces.json 저장 오류: {e}")


def register_user_space(email, display_name, space_name):
    """
    사용자-Space 매핑 등록/업데이트.

    Args:
        email: 사용자 이메일 (예: jhchoi@rsupport.com)
        display_name: 표시 이름 (예: 최재형)
        space_name: Google Chat space (예: spaces/XXXXXXX)
    """
    if not email or not space_name:
        return

    with _spaces_lock:
        data = _load_user_spaces()
        username = email.split("@")[0] if "@" in email else email

        data["users"][email] = {
            "username": username,
            "display_name": display_name or "",
            "space_name": space_name,
            "last_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        _save_user_spaces(data)


def get_user_space(email):
    """
    이메일로 사용자의 Google Chat space 조회.

    Args:
        email: 사용자 이메일

    Returns:
        dict or None: {"username", "display_name", "space_name", "last_seen"}
    """
    data = _load_user_spaces()
    return data.get("users", {}).get(email)


def get_space_by_username(username):
    """
    STACK username으로 사용자의 Google Chat space 조회.

    Args:
        username: STACK 사용자명 (이메일 @ 앞부분)

    Returns:
        dict or None: {"email", "username", "display_name", "space_name"}
    """
    data = _load_user_spaces()
    for email, info in data.get("users", {}).items():
        if info.get("username") == username:
            return {**info, "email": email}
    return None


def get_all_user_spaces():
    """모든 사용자-Space 매핑 반환"""
    data = _load_user_spaces()
    return data.get("users", {})


def sync_user_spaces_from_messages():
    """
    gchat_messages.json에서 사용자-Space 매핑 구축.
    기존 매핑에 없는 사용자만 추가.
    """
    messages_file = os.path.join(_BASE_DIR, "gchat_messages.json")
    if not os.path.exists(messages_file):
        return 0

    try:
        with open(messages_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return 0

    added = 0
    existing = _load_user_spaces()
    existing_emails = set(existing.get("users", {}).keys())

    for msg in data.get("messages", []):
        if msg.get("type") != "user":
            continue
        email = msg.get("user_id", "")
        if email and email not in existing_emails:
            register_user_space(
                email=email,
                display_name=msg.get("first_name", ""),
                space_name=msg.get("chat_id", ""),
            )
            existing_emails.add(email)
            added += 1

    if added > 0:
        _log(f"메시지에서 {added}명 사용자-Space 매핑 추가")
    return added
