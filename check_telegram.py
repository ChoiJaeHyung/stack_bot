"""
텔레그램 명령 확인 스크립트

Claude Code가 이 스크립트를 실행하여 텔레그램 메시지를 확인합니다.
기존 bot.check()와 동일한 역할을 합니다.

사용법:
    python check_telegram.py

출력:
    - 대기 중인 명령이 있으면 명령 내용 출력
    - 없으면 "임무 완료" 출력
"""

from telegram_bot import check_telegram

def main():
    """텔레그램 명령 확인 메인 함수"""
    print("=" * 60)
    print("텔레그램 명령 확인")
    print("=" * 60)

    pending = check_telegram()

    if not pending:
        print("\n임무 완료")
        return

    print(f"\n📋 대기 중인 명령: {len(pending)}개\n")

    for i, task in enumerate(pending, 1):
        print("=" * 60)
        print(f"명령 #{i}")
        print("=" * 60)
        print(f"사용자: {task['user_name']}")
        print(f"시각: {task['timestamp']}")
        print(f"메시지 ID: {task['message_id']}")
        print(f"Chat ID: {task['chat_id']}")
        print()
        print("[명령] - 실행할 지시사항")
        print("-" * 60)
        print(task['instruction'])
        print()
        print("[참고사항] - 최근 24시간 대화 내역 (정보만 확인)")
        print("-" * 60)
        print(task['context_24h'])
        print()

if __name__ == "__main__":
    main()
