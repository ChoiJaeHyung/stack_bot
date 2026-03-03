#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""텔레그램 메시지 처리 스크립트"""

import os
import sys

# 프로젝트 루트로 이동 (스크립트 위치 기반 - 어디든 작동!)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)

from telegram_bot import (
    check_telegram,
    combine_tasks,
    create_working_lock,
    reserve_memory_telegram,
    load_memory,
    get_task_dir,
    report_telegram,
    mark_done_telegram,
    remove_working_lock
)
from telegram_sender import send_message_sync

# 1. 대기 중인 메시지 확인
print("📨 텔레그램 메시지 확인 중...")
pending = check_telegram()

if not pending:
    print("✅ 처리할 메시지가 없습니다.")
    sys.exit(0)

# 2. 메시지 합산
print(f"📝 {len(pending)}개 메시지 합산 중...")
combined = combine_tasks(pending)

# 3. 즉시 답장
print("💬 즉시 답장 전송 중...")
if len(combined['message_ids']) > 1:
    msg = f"✅ 작업을 시작했습니다! (총 {len(combined['message_ids'])}개 요청 합산 처리)"
else:
    msg = "✅ 작업을 시작했습니다!"
send_message_sync(combined['chat_id'], msg)

# 4. 작업 잠금 생성
print("🔒 작업 잠금 생성 중...")
if not create_working_lock(combined['message_ids'], combined['combined_instruction']):
    print("⚠️ 잠금 실패. 다른 작업이 진행 중입니다.")
    sys.exit(1)

# 5. 메모리 예약
print("💾 메모리 예약 중...")
reserve_memory_telegram(
    combined['combined_instruction'],
    combined['chat_id'],
    combined['all_timestamps'],
    combined['message_ids']
)

# 6. 기존 메모리 로드
print("📚 기존 메모리 로드 중...")
memories = load_memory()
print(f"   총 {len(memories)}개 메모리 발견")

# 7. 작업 폴더로 이동
task_dir = get_task_dir(combined['message_ids'][0])
print(f"📁 작업 폴더 이동: {task_dir}")
os.chdir(task_dir)

# 작업 정보 출력
print("\n" + "="*60)
print("📋 작업 정보:")
print("="*60)
print(f"메시지 ID: {combined['message_ids']}")
print(f"Chat ID: {combined['chat_id']}")
print(f"사용자: {combined.get('user_name', 'Unknown')}")
print(f"타임스탬프: {combined['all_timestamps']}")
print(f"\n지시사항:\n{combined['combined_instruction']}")
print("="*60)

# 첨부 파일 정보
if combined.get('files'):
    print("\n📎 첨부 파일:")
    for file_info in combined['files']:
        size_mb = file_info['size'] / 1024 / 1024
        print(f"  - {file_info['type']}: {file_info['path']} ({size_mb:.2f} MB)")
    print()

print("\n✅ 스크립트 준비 완료. 이제 Claude Code가 작업을 수행할 수 있습니다.")
