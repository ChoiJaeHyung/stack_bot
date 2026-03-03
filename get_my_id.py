"""
텔레그램 사용자 ID 확인 스크립트

사용 방법:
1. .env 파일에 TELEGRAM_BOT_TOKEN 설정 (봇 토큰만 있으면 됨)
2. python get_my_id.py 실행
3. 텔레그램 앱에서 본인의 봇에게 아무 메시지나 보내기
4. 이 스크립트가 당신의 ID를 출력합니다!
"""

import os
from dotenv import load_dotenv
from telegram import Bot
import asyncio

# .env 파일 로드
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

async def get_user_id():
    """봇에게 메시지를 보낸 사용자의 ID 확인"""
    print("=" * 60)
    print("텔레그램 사용자 ID 확인")
    print("=" * 60)

    if not BOT_TOKEN or BOT_TOKEN == "your_bot_token_here":
        print("\n❌ 오류: .env 파일에 TELEGRAM_BOT_TOKEN을 먼저 설정하세요!")
        print("\n순서:")
        print("1. 텔레그램 앱에서 @BotFather 찾기")
        print("2. /newbot 명령으로 봇 생성")
        print("3. 받은 토큰을 .env 파일에 입력")
        print("   TELEGRAM_BOT_TOKEN=1234567890:ABCdef...")
        return

    try:
        bot = Bot(token=BOT_TOKEN)
        me = await bot.get_me()

        print(f"\n✅ 봇: @{me.username}")
        print("\n📱 지금 텔레그램 앱에서 @{} 에게".format(me.username))
        print("   아무 메시지나 보내주세요! (예: 안녕)")
        print("\n대기 중", end="", flush=True)

        # 기존 업데이트 offset 확인
        existing_updates = await bot.get_updates()
        last_update_id = existing_updates[-1].update_id if existing_updates else 0

        # 새로운 메시지 대기 (60초)
        for i in range(60):
            await asyncio.sleep(1)
            print(".", end="", flush=True)

            updates = await bot.get_updates(offset=last_update_id + 1)

            if updates:
                print("\n\n✅ 메시지 감지!\n")

                for update in updates:
                    if update.message:
                        user = update.message.from_user
                        print("=" * 60)
                        print("발견한 사용자 정보:")
                        print("=" * 60)
                        print(f"이름: {user.first_name} {user.last_name or ''}")
                        print(f"유저네임: @{user.username}" if user.username else "유저네임: 없음")
                        print(f"사용자 ID: {user.id}")
                        print(f"메시지: {update.message.text}")
                        print("=" * 60)
                        print(f"\n✨ 당신의 텔레그램 ID는: {user.id}")
                        print("\n이 ID를 .env 파일에 추가하세요:")
                        print(f"TELEGRAM_ALLOWED_USERS={user.id}")
                        print("=" * 60)
                        return

        print("\n\n⏱️  시간 초과!")
        print("60초 동안 메시지가 없었습니다.")
        print("다시 실행하고 봇에게 메시지를 보내주세요.")

    except Exception as e:
        print(f"\n\n❌ 오류: {e}")
        print("\n봇 토큰이 올바른지 확인하세요.")

if __name__ == "__main__":
    asyncio.run(get_user_id())
