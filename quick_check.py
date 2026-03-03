#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
빠른 Google Chat 메시지 확인 (bot_brain 실행 전)

Exit Codes:
  0: 새 메시지 없음 (즉시 종료)
  1: 새 메시지 있음 (bot_brain 실행 필요)
  2: 다른 작업 진행 중 (working.json 잠금)
"""

import os
import sys
import io
import time

# Windows cp949 인코딩 문제 방지
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 프로젝트 루트로 이동 (스크립트 위치 기반 - 어디든 작동!)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)

from chat_bot import check_chat

try:
    # 새 메시지 확인 (working.json도 자동으로 확인됨)
    pending = check_chat()

    if not pending:
        # Pub/Sub 지연 대비 2초 후 재시도
        time.sleep(2)
        pending = check_chat()

    if not pending:
        # 새 메시지 없음 또는 다른 작업 진행 중
        sys.exit(0)

    # 새 메시지 있음
    print(f"[NEW_MSG] {len(pending)} new messages found")
    sys.exit(1)

except Exception as e:
    print(f"[ERROR] {e}")
    # 오류 발생 시에도 0 반환 (다음 주기에 재시도)
    sys.exit(0)
