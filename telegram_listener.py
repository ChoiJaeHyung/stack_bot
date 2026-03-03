"""
텔레그램 메시지 수집기 (Listener)

역할:
- 텔레그램 봇 API를 통해 새로운 메시지 수신
- telegram_messages.json에 메시지 저장
- 허용된 사용자만 처리
- 중복 메시지 방지

사용법:
    python telegram_listener.py
    (Ctrl+C로 종료)
"""

import os
import json
import time
from datetime import datetime
from dotenv import load_dotenv
from telegram import Bot
import asyncio

# .env 파일 로드
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USERS = [int(uid.strip()) for uid in os.getenv("TELEGRAM_ALLOWED_USERS", "").split(",") if uid.strip()]
POLLING_INTERVAL = int(os.getenv("TELEGRAM_POLLING_INTERVAL", "10"))

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MESSAGES_FILE = os.path.join(_BASE_DIR, "telegram_messages.json")
ENV_PATH = os.path.join(_BASE_DIR, ".env")


def setup_bot_token():
    """토큰이 .env에 없으면 사용자에게 입력받아 저장"""
    global BOT_TOKEN

    if BOT_TOKEN and BOT_TOKEN not in ("", "YOUR_BOT_TOKEN", "your_bot_token_here"):
        return True

    print("\n" + "=" * 60)
    print("⚠️  TELEGRAM_BOT_TOKEN이 .env에 설정되지 않았습니다.")
    print("=" * 60)
    print()
    print("📌 설정 방법:")
    print("   1. 텔레그램에서 @BotFather를 검색하여 시작")
    print("   2. /newbot 명령으로 새 봇 생성")
    print("   3. @BotFather가 주어준 토큰을 아래에 붙여넣기")
    print()
    print("   예시: 1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ")
    print()

    token = input("▶ 봇 토큰 입력: ").strip()

    if not token:
        print("❌ 토큰이 비어있습니다. 프로그램을 종료합니다.")
        return False

    from dotenv import set_key

    if not os.path.exists(ENV_PATH):
        with open(ENV_PATH, "w", encoding="utf-8") as f:
            f.write("")

    set_key(ENV_PATH, "TELEGRAM_BOT_TOKEN", token)
    BOT_TOKEN = token
    os.environ["TELEGRAM_BOT_TOKEN"] = token

    print(f"✅ .env에 TELEGRAM_BOT_TOKEN 저장 완료!")
    print()
    return True


def load_messages():
    """저장된 메시지 로드"""
    if os.path.exists(MESSAGES_FILE):
        try:
            with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ telegram_messages.json 읽기 오류: {e}")

    return {
        "messages": [],
        "last_update_id": 0
    }


def save_messages(data):
    """메시지 저장"""
    with open(MESSAGES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


async def download_file(bot, file_id, message_id, file_type, file_name=None):
    """
    텔레그램 파일 다운로드

    Args:
        bot: Telegram Bot 인스턴스
        file_id: 텔레그램 파일 ID
        message_id: 메시지 ID
        file_type: 파일 타입 (photo, document, video, audio, voice)
        file_name: 파일명 (document의 경우)

    Returns:
        str: 다운로드된 파일 경로 (실패 시 None)
    """
    try:
        # tasks/msg_{message_id} 폴더 생성
        task_dir = os.path.join(_BASE_DIR, "tasks", f"msg_{message_id}")
        os.makedirs(task_dir, exist_ok=True)

        # 파일 정보 가져오기
        file = await bot.get_file(file_id)

        # 파일 확장자 결정
        if file_name:
            # document의 경우 원본 파일명 사용
            filename = file_name
        else:
            # photo, video 등의 경우 확장자 추출
            file_path = file.file_path
            ext = os.path.splitext(file_path)[1] or '.jpg'

            # 타입별 기본 파일명
            type_prefix = {
                'photo': 'image',
                'video': 'video',
                'audio': 'audio',
                'voice': 'voice'
            }
            prefix = type_prefix.get(file_type, 'file')
            filename = f"{prefix}_{message_id}{ext}"

        # 파일 다운로드
        local_path = os.path.join(task_dir, filename)
        await file.download_to_drive(local_path)

        print(f"📎 파일 다운로드: {filename} ({file.file_size} bytes)")
        return local_path

    except Exception as e:
        print(f"❌ 파일 다운로드 실패: {e}")
        return None


async def fetch_new_messages():
    """새로운 메시지 가져오기 (텍스트 + 이미지 + 파일 지원)"""
    if not BOT_TOKEN or BOT_TOKEN in ("your_bot_token_here", "YOUR_BOT_TOKEN"):
        print("❌ TELEGRAM_BOT_TOKEN 미설정. 프로그램을 종료합니다.")
        return None

    bot = Bot(token=BOT_TOKEN)
    data = load_messages()
    last_update_id = data.get("last_update_id", 0)

    try:
        # 새로운 업데이트 가져오기 (long polling)
        updates = await bot.get_updates(
            offset=last_update_id + 1,
            timeout=5,
            allowed_updates=["message"]
        )

        new_messages = []

        for update in updates:
            if not update.message:
                continue

            msg = update.message
            user = msg.from_user

            # 허용된 사용자 체크
            if ALLOWED_USERS and user.id not in ALLOWED_USERS:
                print(f"⚠️  차단: 허용되지 않은 사용자 {user.id} ({user.first_name})")
                continue

            # 텍스트 추출 (caption 또는 text)
            text = msg.caption or msg.text or ""

            # 파일 다운로드
            files = []

            # 사진 (여러 장 가능 - 가장 큰 크기 선택)
            if msg.photo:
                # photo는 여러 크기의 배열 - 마지막이 가장 큼
                largest_photo = msg.photo[-1]
                file_path = await download_file(
                    bot,
                    largest_photo.file_id,
                    msg.message_id,
                    'photo'
                )
                if file_path:
                    files.append({
                        "type": "photo",
                        "path": file_path,
                        "size": largest_photo.file_size
                    })

            # 문서 (PDF, DOCX, 등)
            if msg.document:
                file_path = await download_file(
                    bot,
                    msg.document.file_id,
                    msg.message_id,
                    'document',
                    msg.document.file_name
                )
                if file_path:
                    files.append({
                        "type": "document",
                        "path": file_path,
                        "name": msg.document.file_name,
                        "mime_type": msg.document.mime_type,
                        "size": msg.document.file_size
                    })

            # 비디오
            if msg.video:
                file_path = await download_file(
                    bot,
                    msg.video.file_id,
                    msg.message_id,
                    'video'
                )
                if file_path:
                    files.append({
                        "type": "video",
                        "path": file_path,
                        "duration": msg.video.duration,
                        "size": msg.video.file_size
                    })

            # 오디오
            if msg.audio:
                file_path = await download_file(
                    bot,
                    msg.audio.file_id,
                    msg.message_id,
                    'audio',
                    msg.audio.file_name
                )
                if file_path:
                    files.append({
                        "type": "audio",
                        "path": file_path,
                        "duration": msg.audio.duration,
                        "size": msg.audio.file_size
                    })

            # 음성 메시지
            if msg.voice:
                file_path = await download_file(
                    bot,
                    msg.voice.file_id,
                    msg.message_id,
                    'voice'
                )
                if file_path:
                    files.append({
                        "type": "voice",
                        "path": file_path,
                        "duration": msg.voice.duration,
                        "size": msg.voice.file_size
                    })

            # 🆕 위치 정보 (Location)
            location_info = None
            if msg.location:
                location_info = {
                    "latitude": msg.location.latitude,
                    "longitude": msg.location.longitude
                }

                # 선택적 정보 (있으면 추가)
                if hasattr(msg.location, 'horizontal_accuracy') and msg.location.horizontal_accuracy:
                    location_info["accuracy"] = msg.location.horizontal_accuracy

                print(f"📍 위치 수신: 위도 {msg.location.latitude}, 경도 {msg.location.longitude}")

            # 텍스트나 파일이나 위치가 하나라도 있어야 처리
            if not text and not files and not location_info:
                continue

            # 메시지 데이터 구성
            message_data = {
                "message_id": msg.message_id,
                "update_id": update.update_id,
                "type": "user",  # 🆕 메시지 타입 (user/bot)
                "user_id": user.id,
                "username": user.username or "",
                "first_name": user.first_name or "",
                "last_name": user.last_name or "",
                "chat_id": msg.chat_id,
                "text": text,
                "files": files,  # 🆕 파일 정보
                "location": location_info,  # 🆕 위치 정보
                "timestamp": msg.date.strftime("%Y-%m-%d %H:%M:%S"),
                "processed": False
            }

            new_messages.append(message_data)
            data["messages"].append(message_data)

            # last_update_id 업데이트
            if update.update_id > data["last_update_id"]:
                data["last_update_id"] = update.update_id

        if new_messages:
            save_messages(data)
            for msg in new_messages:
                text_preview = msg['text'][:50] if msg['text'] else "(파일만)" if msg['files'] else "(위치)" if msg.get('location') else ""
                file_info = f" + {len(msg['files'])}개 파일" if msg['files'] else ""
                location_info = f" + 위치 정보" if msg.get('location') else ""
                print(f"📨 새 메시지: [{msg['timestamp']}] {msg['first_name']}: {text_preview}...{file_info}{location_info}")
            return len(new_messages)

        return 0

    except Exception as e:
        print(f"❌ 오류: {e}")
        return None


async def listen_loop():
    """메시지 수신 루프"""
    print("=" * 60)
    print("텔레그램 메시지 수집기 시작")
    print("=" * 60)

    # 토큰 확인 및 초기 설정
    if not setup_bot_token():
        return

    print(f"폴링 간격: {POLLING_INTERVAL}초")
    print(f"허용된 사용자: {ALLOWED_USERS}")
    print(f"메시지 저장 파일: {MESSAGES_FILE}")
    print("\n대기 중... (Ctrl+C로 종료)\n")

    cycle_count = 0

    try:
        while True:
            cycle_count += 1
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            result = await fetch_new_messages()

            if result is None:
                print(f"[{now}] #{cycle_count} - 오류 발생, 재시도 대기...")
            elif result > 0:
                print(f"[{now}] #{cycle_count} - ✅ {result}개 메시지 수집")
            else:
                print(f"[{now}] #{cycle_count} - 대기 중...")

            await asyncio.sleep(POLLING_INTERVAL)

    except KeyboardInterrupt:
        print("\n\n종료 신호 감지. 프로그램을 종료합니다.")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(listen_loop())
