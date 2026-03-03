"""
Proactive Agent 설정 모듈

모든 Proactive 관련 환경변수 로딩 및 상수 정의.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ─── 전체 활성화 ───
PROACTIVE_ENABLED = os.getenv("PROACTIVE_ENABLED", "true").lower() == "true"
PROACTIVE_DRY_RUN = os.getenv("PROACTIVE_DRY_RUN", "false").lower() == "true"

# ─── 아침 브리핑 ───
PROACTIVE_BRIEFING_ENABLED = os.getenv("PROACTIVE_BRIEFING_ENABLED", "true").lower() == "true"
PROACTIVE_BRIEFING_HOUR = int(os.getenv("PROACTIVE_BRIEFING_HOUR", "9"))
PROACTIVE_BRIEFING_MINUTE = int(os.getenv("PROACTIVE_BRIEFING_MINUTE", "0"))

# ─── 주간 데이터 정합성 점검 ───
PROACTIVE_WEEKLY_ENABLED = os.getenv("PROACTIVE_WEEKLY_ENABLED", "true").lower() == "true"
PROACTIVE_WEEKLY_DAY = int(os.getenv("PROACTIVE_WEEKLY_DAY", "0"))  # 0=월요일
PROACTIVE_WEEKLY_HOUR = int(os.getenv("PROACTIVE_WEEKLY_HOUR", "9"))
PROACTIVE_WEEKLY_MINUTE = int(os.getenv("PROACTIVE_WEEKLY_MINUTE", "30"))

# ─── 계약 만료 알림 ───
PROACTIVE_CONTRACT_ALERT_ENABLED = os.getenv("PROACTIVE_CONTRACT_ALERT_ENABLED", "true").lower() == "true"
CONTRACT_ALERT_DAYS = [30, 7, 1]  # D-30, D-7, D-1

# ─── 미완료 점검 리마인더 ───
PROACTIVE_OVERDUE_ENABLED = os.getenv("PROACTIVE_OVERDUE_ENABLED", "true").lower() == "true"
OVERDUE_ESCALATION_DAYS = [1, 3, 7]  # Day+1, +3, +7

# ─── 허용 시간 범위 (분) ───
PROACTIVE_TOLERANCE_MINUTES = int(os.getenv("PROACTIVE_TOLERANCE_MINUTES", "15"))

# ─── STACK API (bot_brain.py와 공유) ───
STACK_API_URL = os.getenv("STACK_API_URL", "")
STACK_API_KEY = os.getenv("STACK_API_KEY", "")
STACK_API_TIMEOUT = int(os.getenv("STACK_API_TIMEOUT", "15"))

# ─── 봇 이름 ───
BOT_NAME = os.getenv("BOT_NAME", "AI비서")
