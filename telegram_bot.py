"""
텔레그램 봇 통합 로직

기존 bot.py와 유사한 구조로 텔레그램 메시지 처리

주요 기능:
- check_telegram() - 새로운 명령 확인 (최근 24시간 대화 내역 포함)
- report_telegram() - 결과 전송 및 메모리 저장
- mark_done_telegram() - 처리 완료 표시
- load_memory() - 기존 메모리 로드 (bot.py와 공유)
- reserve_memory_telegram() - 작업 시작 시 메모리 예약
"""

import os
import json
import time
from datetime import datetime, timedelta
from telegram_sender import send_files_sync, run_async_safe

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MESSAGES_FILE = os.path.join(_BASE_DIR, "telegram_messages.json")
TASKS_DIR = os.path.join(_BASE_DIR, "tasks")
INDEX_FILE = os.path.join(_BASE_DIR, "tasks", "index.json")
WORKING_LOCK_FILE = os.path.join(_BASE_DIR, "working.json")
NEW_INSTRUCTIONS_FILE = os.path.join(_BASE_DIR, "new_instructions.json")  # 🆕 작업 중 새 지시사항
WORKING_LOCK_TIMEOUT = 1800  # 30분: 이 시간 이상 잠금 파일이 있으면 스탈로 판단


def load_telegram_messages():
    """telegram_messages.json 로드"""
    if not os.path.exists(MESSAGES_FILE):
        return {"messages": [], "last_update_id": 0}

    try:
        with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ telegram_messages.json 읽기 오류: {e}")
        return {"messages": [], "last_update_id": 0}


def save_telegram_messages(data):
    """telegram_messages.json 저장"""
    with open(MESSAGES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_bot_response(chat_id, text, reply_to_message_ids, files=None):
    """
    봇 응답을 telegram_messages.json에 저장 (대화 컨텍스트 유지)

    Args:
        chat_id: 채팅 ID
        text: 봇 응답 메시지
        reply_to_message_ids: 응답 대상 메시지 ID (리스트)
        files: 전송한 파일 리스트 (선택)
    """
    data = load_telegram_messages()

    # 봇 응답 메시지 데이터
    bot_message = {
        "message_id": f"bot_{reply_to_message_ids[0]}",  # 봇 메시지 ID (고유)
        "type": "bot",  # 메시지 타입
        "chat_id": chat_id,
        "text": text,
        "files": files or [],
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "reply_to": reply_to_message_ids,  # 어떤 메시지에 대한 응답인지
        "processed": True  # 봇 메시지는 항상 processed
    }

    data["messages"].append(bot_message)
    save_telegram_messages(data)

    print(f"📝 봇 응답 저장 완료 (reply_to: {reply_to_message_ids})")


def check_working_lock():
    """
    작업 잠금 파일 확인. 마지막 활동(경과 보고) 기준 30분 타임아웃.

    Returns:
        dict or None: 잠금 정보 (존재하면) 또는 None
        특수 케이스: {"stale": True, ...} - 스탈 작업 (재시작 필요)
    """
    if not os.path.exists(WORKING_LOCK_FILE):
        return None

    try:
        with open(WORKING_LOCK_FILE, "r", encoding="utf-8") as f:
            lock_info = json.load(f)
    except Exception as e:
        print(f"⚠️ working.json 읽기 오류: {e}")
        return None

    # 마지막 활동 시각 확인 (없으면 started_at 사용)
    last_activity_str = lock_info.get("last_activity", lock_info.get("started_at"))

    try:
        last_activity = datetime.strptime(last_activity_str, "%Y-%m-%d %H:%M:%S")
        now = datetime.now()
        idle_seconds = (now - last_activity).total_seconds()

        # 스탈네스 확인: 마지막 활동으로부터 30분 이상 경과
        if idle_seconds > WORKING_LOCK_TIMEOUT:
            print(f"⚠️ 스탈 작업 감지 (마지막 활동: {int(idle_seconds/60)}분 전)")
            print(f"   메시지 ID: {lock_info.get('message_id')}")
            print(f"   지시사항: {lock_info.get('instruction_summary')}")

            # 스탈 플래그 추가하여 반환 (삭제하지 않음 - 재시작 필요)
            lock_info["stale"] = True
            return lock_info

        # 활동 중인 작업
        print(f"ℹ️ 작업 진행 중 (마지막 활동: {int(idle_seconds/60)}분 전)")
        return lock_info

    except Exception as e:
        print(f"⚠️ 타임스탬프 파싱 오류: {e}")
        # 파싱 실패 시 파일 수정 시각으로 fallback
        lock_age = time.time() - os.path.getmtime(WORKING_LOCK_FILE)
        if lock_age > WORKING_LOCK_TIMEOUT:
            try:
                os.remove(WORKING_LOCK_FILE)
            except OSError:
                pass
            return None
        return lock_info


def create_working_lock(message_id, instruction):
    """
    원자적으로 작업 잠금 파일 생성. 이미 존재하면 False 반환.

    Args:
        message_id: 메시지 ID (또는 리스트)
        instruction: 지시사항

    Returns:
        bool: 생성 성공 여부
    """
    # message_id가 리스트인 경우 (여러 메시지 합산)
    if isinstance(message_id, list):
        message_ids = message_id
        msg_id_str = f"{', '.join(map(str, message_ids))} (합산 {len(message_ids)}개)"
    else:
        message_ids = [message_id]
        msg_id_str = str(message_id)

    summary = instruction.replace("\n", " ")[:50]
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lock_data = {
        "message_id": message_ids[0] if len(message_ids) == 1 else message_ids,
        "instruction_summary": summary,
        "started_at": now_str,
        "last_activity": now_str,  # 🆕 마지막 활동 시각
        "count": len(message_ids)
    }

    try:
        with open(WORKING_LOCK_FILE, "x", encoding="utf-8") as f:
            json.dump(lock_data, f, ensure_ascii=False, indent=2)
        print(f"🔒 작업 잠금 생성: message_id={msg_id_str}")
        return True
    except FileExistsError:
        print(f"⚠️ 잠금 파일 이미 존재. 다른 작업이 진행 중입니다.")
        return False


def update_working_activity():
    """
    작업 잠금의 마지막 활동 시각 갱신 (경과 보고 시 호출)

    중간 경과 보고(send_message_sync)를 할 때마다 호출하여
    작업이 여전히 진행 중임을 표시합니다.
    """
    if not os.path.exists(WORKING_LOCK_FILE):
        return

    try:
        with open(WORKING_LOCK_FILE, "r", encoding="utf-8") as f:
            lock_data = json.load(f)

        # last_activity 갱신
        lock_data["last_activity"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with open(WORKING_LOCK_FILE, "w", encoding="utf-8") as f:
            json.dump(lock_data, f, ensure_ascii=False, indent=2)

    except Exception as e:
        print(f"⚠️ working.json 활동 갱신 오류: {e}")


def check_new_messages_during_work():
    """
    작업 중 새 메시지 확인 (working.json이 있을 때만)

    Returns:
        list: 새로운 메시지 리스트
        [
            {
                "message_id": int,
                "instruction": str,
                "timestamp": str,
                "chat_id": int,
                "user_name": str,
                "detected_at": str
            },
            ...
        ]
    """
    # working.json이 없으면 작업 중이 아니므로 확인 안 함
    if not os.path.exists(WORKING_LOCK_FILE):
        return []

    try:
        with open(WORKING_LOCK_FILE, "r", encoding="utf-8") as f:
            lock_info = json.load(f)
    except Exception:
        return []

    # 스탈 작업이면 확인 안 함
    if lock_info.get("stale"):
        return []

    # 현재 처리 중인 메시지 ID
    current_message_ids = lock_info.get("message_id")
    if not isinstance(current_message_ids, list):
        current_message_ids = [current_message_ids]

    # 🆕 이미 new_instructions.json에 저장된 메시지 ID 확인
    already_saved = load_new_instructions()
    saved_message_ids = {inst["message_id"] for inst in already_saved}

    # Telegram API에서 새 메시지 수집
    _poll_telegram_once()

    # 새 메시지 확인
    data = load_telegram_messages()
    messages = data.get("messages", [])

    new_messages = []
    for msg in messages:
        # 이미 처리된 메시지 제외
        if msg.get("processed", False):
            continue

        # 현재 처리 중인 메시지 제외
        if msg["message_id"] in current_message_ids:
            continue

        # 🆕 이미 저장된 메시지 제외 (중복 알림 방지)
        if msg["message_id"] in saved_message_ids:
            continue

        # 새 메시지 발견!
        new_messages.append({
            "message_id": msg["message_id"],
            "instruction": msg["text"],
            "timestamp": msg["timestamp"],
            "chat_id": msg["chat_id"],
            "user_name": msg["first_name"],
            "detected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

    return new_messages


def save_new_instructions(new_messages):
    """
    새 지시사항을 파일에 저장

    Args:
        new_messages: check_new_messages_during_work()가 반환한 메시지 리스트
    """
    if not new_messages:
        return

    # 기존 파일 읽기 (있으면)
    if os.path.exists(NEW_INSTRUCTIONS_FILE):
        try:
            with open(NEW_INSTRUCTIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {"instructions": []}
    else:
        data = {"instructions": []}

    # 새 메시지 추가 (중복 제거)
    existing_ids = {inst["message_id"] for inst in data["instructions"]}
    for msg in new_messages:
        if msg["message_id"] not in existing_ids:
            data["instructions"].append(msg)

    # 파일에 저장
    with open(NEW_INSTRUCTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"💾 새 지시사항 저장: {len(new_messages)}개")


def load_new_instructions():
    """
    저장된 새 지시사항 읽기

    Returns:
        list: 새 지시사항 리스트
    """
    if not os.path.exists(NEW_INSTRUCTIONS_FILE):
        return []

    try:
        with open(NEW_INSTRUCTIONS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("instructions", [])
    except Exception as e:
        print(f"⚠️ new_instructions.json 읽기 오류: {e}")
        return []


def clear_new_instructions():
    """
    새 지시사항 파일 삭제 (작업 완료 후 호출)
    """
    if os.path.exists(NEW_INSTRUCTIONS_FILE):
        try:
            os.remove(NEW_INSTRUCTIONS_FILE)
            print("🧹 새 지시사항 파일 정리 완료")
        except OSError as e:
            print(f"⚠️ new_instructions.json 삭제 오류: {e}")


def remove_working_lock():
    """작업 잠금 파일 삭제"""
    if os.path.exists(WORKING_LOCK_FILE):
        os.remove(WORKING_LOCK_FILE)
        print("🔓 작업 잠금 해제")


def load_index():
    """인덱스 파일 로드"""
    if not os.path.exists(INDEX_FILE):
        return {"tasks": [], "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    try:
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ index.json 읽기 오류: {e}")
        return {"tasks": [], "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


def save_index(index_data):
    """인덱스 파일 저장"""
    # tasks 폴더가 없으면 생성
    if not os.path.exists(TASKS_DIR):
        os.makedirs(TASKS_DIR)

    index_data["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index_data, f, ensure_ascii=False, indent=2)


def update_index(message_id, instruction, result_summary="", files=None, chat_id=None, timestamp=None):
    """
    인덱스 업데이트 (작업 추가 또는 수정)

    Args:
        message_id: 메시지 ID
        instruction: 지시사항
        result_summary: 결과 요약
        files: 파일 리스트
        chat_id: 채팅 ID
        timestamp: 메시지 시각
    """
    index = load_index()

    # 키워드 추출 (간단한 방식: 명사 추출 대신 단어 분리)
    keywords = []
    for word in instruction.split():
        if len(word) >= 2:  # 2글자 이상만
            keywords.append(word)
    keywords = list(set(keywords))[:10]  # 중복 제거, 최대 10개

    # 기존 작업 찾기
    existing_task = None
    for task in index["tasks"]:
        if task["message_id"] == message_id:
            existing_task = task
            break

    task_data = {
        "message_id": message_id,
        "timestamp": timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "instruction": instruction,
        "keywords": keywords,
        "result_summary": result_summary,
        "files": files or [],
        "chat_id": chat_id,
        "task_dir": os.path.join(TASKS_DIR, f"msg_{message_id}")
    }

    if existing_task:
        # 기존 작업 업데이트
        existing_task.update(task_data)
    else:
        # 새 작업 추가
        index["tasks"].append(task_data)

    # message_id 역순 정렬 (최신순)
    index["tasks"].sort(key=lambda x: x["message_id"], reverse=True)

    save_index(index)
    print(f"📇 인덱스 업데이트: message_id={message_id}")


def search_memory(keyword=None, message_id=None):
    """
    인덱스에서 작업 검색

    Args:
        keyword: 검색할 키워드 (instruction, keywords에서 검색)
        message_id: 특정 메시지 ID

    Returns:
        list: 매칭된 작업 메타데이터
    """
    index = load_index()

    if message_id is not None:
        # 특정 message_id로 검색
        for task in index["tasks"]:
            if task["message_id"] == message_id:
                return [task]
        return []

    if keyword:
        # 키워드로 검색
        matches = []
        keyword_lower = keyword.lower()

        for task in index["tasks"]:
            # instruction 또는 keywords에 포함되어 있으면 매칭
            if (keyword_lower in task["instruction"].lower() or
                any(keyword_lower in kw.lower() for kw in task["keywords"])):
                matches.append(task)

        return matches

    # 조건 없으면 전체 반환
    return index["tasks"]


def get_task_dir(message_id):
    """
    메시지 ID 기반 작업 폴더 경로 반환

    Args:
        message_id: 텔레그램 메시지 ID

    Returns:
        str: 작업 폴더 경로 (예: "tasks/msg_5/")
    """
    task_dir = os.path.join(TASKS_DIR, f"msg_{message_id}")

    # 폴더가 없으면 생성
    if not os.path.exists(task_dir):
        os.makedirs(task_dir)
        print(f"📁 작업 폴더 생성: {task_dir}")

    return task_dir


def get_24h_context(messages, current_message_id):
    """
    최근 24시간 대화 내역 생성 (사용자 + 봇 응답 모두 포함)

    Args:
        messages: 전체 메시지 리스트
        current_message_id: 현재 처리 중인 메시지 ID

    Returns:
        str: 24시간 대화 내역 텍스트
    """
    now = datetime.now()
    cutoff_time = now - timedelta(hours=24)

    context_lines = ["=== 최근 24시간 대화 내역 ===\n"]

    for msg in messages:
        # 현재 메시지까지만 포함
        if msg.get("type") == "user" and msg["message_id"] == current_message_id:
            break

        # 24시간 이내 메시지만 포함
        msg_time = datetime.strptime(msg["timestamp"], "%Y-%m-%d %H:%M:%S")
        if msg_time < cutoff_time:
            continue

        # 메시지 타입에 따라 포맷 다르게
        msg_type = msg.get("type", "user")  # 기본값 user (하위 호환)

        if msg_type == "user":
            # 사용자 메시지
            user_name = msg.get("first_name", "사용자")
            text = msg.get("text", "")

            # 파일 정보 추가
            files = msg.get("files", [])
            if files:
                file_info = f" [첨부: {len(files)}개 파일]"
            else:
                file_info = ""

            # 🆕 위치 정보 추가
            location = msg.get("location")
            if location:
                location_info = f" [위치: {location['latitude']}, {location['longitude']}]"
            else:
                location_info = ""

            context_lines.append(f"[{msg['timestamp']}] {user_name}: {text}{file_info}{location_info}")

        elif msg_type == "bot":
            # 봇 응답
            text = msg.get("text", "")

            # 긴 응답은 요약
            if len(text) > 150:
                text_preview = text[:150] + "..."
            else:
                text_preview = text

            # 파일 정보 추가
            files = msg.get("files", [])
            if files:
                file_info = f" [전송: {', '.join(files)}]"
            else:
                file_info = ""

            context_lines.append(f"[{msg['timestamp']}] 🤖 소놀봇: {text_preview}{file_info}")

    if len(context_lines) == 1:
        return "최근 24시간 이내 대화 내역이 없습니다."

    return "\n".join(context_lines)


def _poll_telegram_once():
    """Telegram API에서 새 메시지를 한 번 가져와서 json 업데이트 (Listener 별도 실행 불필요)"""
    from telegram_listener import fetch_new_messages
    try:
        run_async_safe(fetch_new_messages())
    except Exception as e:
        print(f"⚠️ 폴링 중 오류: {e}")


def _cleanup_old_messages():
    """30일 초과 처리된 메시지 정리. 24시간 이내는 컨텍스트용, 30일까지는 참조용 보관."""
    data = load_telegram_messages()
    messages = data.get("messages", [])

    cutoff = datetime.now() - timedelta(days=30)

    cleaned = [
        msg for msg in messages
        if not msg.get("processed", False)
        or datetime.strptime(msg["timestamp"], "%Y-%m-%d %H:%M:%S") > cutoff
    ]

    removed = len(messages) - len(cleaned)
    if removed > 0:
        data["messages"] = cleaned
        save_telegram_messages(data)
        print(f"🧹 30일 초과 메시지 {removed}개 정리 완료")


def check_telegram():
    """
    새로운 텔레그램 명령 확인

    Returns:
        list: 대기 중인 지시사항 리스트
        [
            {
                "instruction": str,      # 실행할 명령
                "message_id": int,       # 메시지 ID
                "chat_id": int,          # 채팅 ID
                "timestamp": str,        # 메시지 시각
                "context_24h": str,      # 최근 24시간 대화 내역
                "user_name": str,        # 사용자 이름
                "stale_resume": bool     # 스탈 작업 재개 여부
            },
            ...
        ]
    """
    # 작업 잠금 확인
    lock_info = check_working_lock()

    if lock_info:
        # 스탈 작업인 경우 - 재시작
        if lock_info.get("stale"):
            print("🔄 스탈 작업 재시작")

            # 텔레그램 알림 전송
            from telegram_sender import send_message_sync
            message_ids = lock_info.get("message_id")
            if not isinstance(message_ids, list):
                message_ids = [message_ids]

            # 첫 번째 메시지의 chat_id 찾기
            data = load_telegram_messages()
            messages = data.get("messages", [])
            chat_id = None
            for msg in messages:
                if msg["message_id"] in message_ids:
                    chat_id = msg["chat_id"]
                    break

            if chat_id:
                alert_msg = (
                    "⚠️ **이전 작업이 중단되었습니다**\n\n"
                    f"지시사항: {lock_info.get('instruction_summary')}...\n"
                    f"시작 시각: {lock_info.get('started_at')}\n"
                    f"마지막 활동: {lock_info.get('last_activity')}\n\n"
                    "처음부터 다시 시작합니다."
                )
                send_message_sync(chat_id, alert_msg)

            # 잠금 파일 삭제
            try:
                os.remove(WORKING_LOCK_FILE)
                print("🔓 스탈 잠금 삭제 완료")
            except OSError:
                pass

            # 미처리 메시지 찾아서 재시작 플래그 추가
            pending = []
            for msg in messages:
                if msg["message_id"] in message_ids and not msg.get("processed", False):
                    instruction = msg.get("text", "")
                    message_id = msg["message_id"]
                    chat_id = msg["chat_id"]
                    timestamp = msg["timestamp"]
                    user_name = msg["first_name"]
                    files = msg.get("files", [])  # 🆕 파일 정보
                    location = msg.get("location")  # 🆕 위치 정보
                    context_24h = get_24h_context(messages, message_id)

                    pending.append({
                        "instruction": instruction,
                        "message_id": message_id,
                        "chat_id": chat_id,
                        "timestamp": timestamp,
                        "context_24h": context_24h,
                        "user_name": user_name,
                        "files": files,  # 🆕 파일 정보
                        "location": location,  # 🆕 위치 정보
                        "stale_resume": True  # 🆕 스탈 작업 재개 플래그
                    })

            return pending

        # 활동 중인 작업 - 대기
        print(f"⚠️ 다른 작업이 진행 중입니다: message_id={lock_info.get('message_id')}")
        print(f"   지시사항: {lock_info.get('instruction_summary')}")
        print(f"   시작 시각: {lock_info.get('started_at')}")
        print(f"   마지막 활동: {lock_info.get('last_activity')}")
        return []

    # Telegram API에서 새 메시지 수집 (Listener 별도 실행 불필요)
    _poll_telegram_once()

    # 30일 초과 처리된 메시지 정리 (24h 이내는 컨텍스트용, 30일까지 참조용 보관)
    _cleanup_old_messages()

    data = load_telegram_messages()
    messages = data.get("messages", [])

    pending = []

    for msg in messages:
        # 이미 처리된 메시지는 건너뛰기
        if msg.get("processed", False):
            continue

        # 새로운 명령 발견
        instruction = msg.get("text", "")
        message_id = msg["message_id"]
        chat_id = msg["chat_id"]
        timestamp = msg["timestamp"]
        user_name = msg["first_name"]
        files = msg.get("files", [])  # 🆕 파일 정보
        location = msg.get("location")  # 🆕 위치 정보

        # 최근 24시간 대화 내역 생성
        context_24h = get_24h_context(messages, message_id)

        pending.append({
            "instruction": instruction,
            "message_id": message_id,
            "chat_id": chat_id,
            "timestamp": timestamp,
            "context_24h": context_24h,
            "user_name": user_name,
            "files": files,  # 🆕 파일 정보
            "location": location,  # 🆕 위치 정보
            "stale_resume": False  # 일반 작업
        })

    return pending


def _format_file_size(size_bytes):
    """파일 크기를 사람이 읽기 쉬운 형식으로 변환"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / 1024 / 1024:.1f} MB"


def combine_tasks(pending_tasks):
    """
    여러 미처리 메시지를 하나의 통합 작업으로 합산

    Args:
        pending_tasks: check_telegram()이 반환한 작업 리스트

    Returns:
        dict: {
            "combined_instruction": str,
            "message_ids": list,
            "chat_id": int,
            "timestamp": str,  # 첫 메시지 시각
            "user_name": str,
            "all_timestamps": list,  # 모든 메시지 시각
            "files": list,  # 🆕 모든 파일 정보
            "stale_resume": bool  # 스탈 작업 재개 여부
        }
    """
    if not pending_tasks:
        return None

    # 시간순 정렬 (오래된 것부터)
    sorted_tasks = sorted(pending_tasks, key=lambda x: x['timestamp'])

    # 스탈 작업 재개 여부 확인
    is_stale_resume = any(task.get('stale_resume', False) for task in sorted_tasks)

    # 합산된 지시사항 생성
    combined_parts = []

    # 🆕 스탈 작업 재개인 경우 컨텍스트 추가
    if is_stale_resume:
        combined_parts.append("⚠️ [중단된 작업 재시작]")
        combined_parts.append("이전 작업의 진행 상태를 확인한 후, 합리적으로 진행할 것.")
        combined_parts.append("tasks/ 폴더에서 이전 작업 결과물을 확인하고, 이어서 작업할 수 있는 경우 이어서 진행하되,")
        combined_parts.append("처음부터 다시 시작하는 것이 더 안전하다면 처음부터 다시 시작할 것.")
        combined_parts.append("")
        combined_parts.append("---")
        combined_parts.append("")

    # 🆕 모든 파일 수집
    all_files = []

    for i, task in enumerate(sorted_tasks, 1):
        combined_parts.append(f"[요청 {i}] ({task['timestamp']})")

        # 텍스트가 있으면 추가
        if task['instruction']:
            combined_parts.append(task['instruction'])

        # 🆕 파일 정보 추가
        files = task.get('files', [])
        if files:
            combined_parts.append("")
            combined_parts.append("📎 첨부 파일:")
            for file_info in files:
                file_path = file_info['path']
                file_name = os.path.basename(file_path)
                file_type = file_info['type']
                file_size = _format_file_size(file_info.get('size', 0))

                # 파일 타입별 이모지
                type_emoji = {
                    'photo': '🖼️',
                    'document': '📄',
                    'video': '🎥',
                    'audio': '🎵',
                    'voice': '🎤'
                }
                emoji = type_emoji.get(file_type, '📎')

                combined_parts.append(f"  {emoji} {file_name} ({file_size})")
                combined_parts.append(f"     경로: {file_path}")

                # 전체 파일 리스트에 추가
                all_files.append(file_info)

        # 🆕 위치 정보 추가
        location = task.get('location')
        if location:
            combined_parts.append("")
            combined_parts.append("📍 위치 정보:")
            combined_parts.append(f"  위도: {location['latitude']}")
            combined_parts.append(f"  경도: {location['longitude']}")

            # 정확도 정보 (있으면)
            if 'accuracy' in location:
                combined_parts.append(f"  정확도: ±{location['accuracy']}m")

            # Google Maps 링크 생성
            maps_url = f"https://www.google.com/maps?q={location['latitude']},{location['longitude']}"
            combined_parts.append(f"  Google Maps: {maps_url}")

        combined_parts.append("")  # 빈 줄

    combined_instruction = "\n".join(combined_parts).strip()

    # 24시간 컨텍스트를 combined_instruction에 포함 (Claude가 직접 볼 수 있도록)
    context_24h = sorted_tasks[0]['context_24h']
    if context_24h and context_24h != "최근 24시간 이내 대화 내역이 없습니다.":
        combined_instruction = combined_instruction + "\n\n---\n\n[참고사항]\n" + context_24h

    return {
        "combined_instruction": combined_instruction,
        "message_ids": [task['message_id'] for task in sorted_tasks],
        "chat_id": sorted_tasks[0]['chat_id'],
        "timestamp": sorted_tasks[0]['timestamp'],
        "user_name": sorted_tasks[0]['user_name'],
        "all_timestamps": [task['timestamp'] for task in sorted_tasks],
        "context_24h": context_24h,
        "files": all_files,  # 🆕 모든 파일 정보
        "stale_resume": is_stale_resume  # 🆕 스탈 작업 재개 플래그
    }


def reserve_memory_telegram(instruction, chat_id, timestamp, message_id):
    """
    작업 시작 시 즉시 메모리 예약 (중복 방지)

    Args:
        instruction: 지시사항 (여러 메시지 합산 가능)
        chat_id: 채팅 ID
        timestamp: 메시지 시각 (또는 리스트)
        message_id: 메시지 ID (또는 리스트)
    """
    # message_id가 리스트인 경우 (여러 메시지 합산)
    if isinstance(message_id, list):
        message_ids = message_id
        main_message_id = message_ids[0]
        timestamps = timestamp if isinstance(timestamp, list) else [timestamp] * len(message_ids)
    else:
        message_ids = [message_id]
        main_message_id = message_id
        timestamps = [timestamp]

    # 메인 작업 폴더 생성 (첫 번째 메시지 ID)
    task_dir = get_task_dir(main_message_id)
    filepath = os.path.join(task_dir, "task_info.txt")

    now = datetime.now()

    # 메시지 ID 정보
    if len(message_ids) > 1:
        msg_id_info = f"{', '.join(map(str, message_ids))} (합산 {len(message_ids)}개)"
        msg_date_info = "\n".join([f"  - msg_{mid}: {ts}" for mid, ts in zip(message_ids, timestamps)])
    else:
        msg_id_info = str(main_message_id)
        msg_date_info = timestamps[0]

    # 메모리 파일 생성 (지시만 먼저 기록)
    content = f"""[시간] {now.strftime("%Y-%m-%d %H:%M:%S")}
[메시지ID] {msg_id_info}
[출처] Telegram (chat_id: {chat_id})
[메시지날짜]
{msg_date_info}
[지시] {instruction}
[결과] (작업 진행 중...)
"""

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    # 메인 메시지 인덱스 업데이트
    update_index(
        message_id=main_message_id,
        instruction=instruction,
        result_summary="(작업 진행 중...)",
        files=[],
        chat_id=chat_id,
        timestamp=timestamps[0]
    )

    # 추가 메시지들도 참조 파일 생성
    for i, (msg_id, ts) in enumerate(zip(message_ids[1:], timestamps[1:]), 2):
        ref_dir = get_task_dir(msg_id)
        ref_file = os.path.join(ref_dir, "task_info.txt")
        ref_content = f"""[시간] {now.strftime("%Y-%m-%d %H:%M:%S")}
[메시지ID] {msg_id}
[출처] Telegram (chat_id: {chat_id})
[메시지날짜] {ts}
[지시] (메인 작업 msg_{main_message_id}에 합산됨)
[참조] tasks/msg_{main_message_id}/
[결과] (작업 진행 중...)
"""
        with open(ref_file, "w", encoding="utf-8") as f:
            f.write(ref_content)

        # 인덱스에도 추가
        update_index(
            message_id=msg_id,
            instruction=f"(msg_{main_message_id}에 합산됨)",
            result_summary="(작업 진행 중...)",
            files=[],
            chat_id=chat_id,
            timestamp=ts
        )

    print(f"📝 메모리 예약 완료: {task_dir}/task_info.txt")
    if len(message_ids) > 1:
        print(f"   합산 메시지: {len(message_ids)}개 ({', '.join(map(str, message_ids))})")


def report_telegram(instruction, result_text, chat_id, timestamp, message_id, files=None):
    """
    작업 결과를 텔레그램으로 전송하고 메모리에 저장

    Args:
        instruction: 원본 지시사항 (여러 메시지 합산 가능)
        result_text: 실행 결과
        chat_id: 채팅 ID
        timestamp: 메시지 시각 (또는 리스트)
        message_id: 메시지 ID (또는 리스트)
        files: 첨부 파일 리스트 (선택)
    """
    # message_id가 리스트인 경우 (여러 메시지 합산)
    if isinstance(message_id, list):
        message_ids = message_id
        main_message_id = message_ids[0]
        timestamps = timestamp if isinstance(timestamp, list) else [timestamp] * len(message_ids)
    else:
        message_ids = [message_id]
        main_message_id = message_id
        timestamps = [timestamp]

    # 결과 메시지 작성 (지시사항/참고사항 생략 - 텔레그램 대화창에 이미 있음)
    message = f"""🤖 **소놀봇 작업 완료**

**✅ 결과:**
{result_text}
"""

    if files:
        file_names = [os.path.basename(f) for f in files]
        message += f"\n**📎 첨부 파일:** {', '.join(file_names)}"

    if len(message_ids) > 1:
        message += f"\n\n_합산 처리: {len(message_ids)}개 메시지_"

    # 텔레그램으로 전송
    print(f"\n📤 텔레그램으로 결과 전송 중... (chat_id: {chat_id})")
    success = send_files_sync(chat_id, message, files or [])

    if success:
        print("✅ 결과 전송 완료!")

        # 🆕 봇 응답을 telegram_messages.json에 저장 (대화 컨텍스트 유지)
        save_bot_response(
            chat_id=chat_id,
            text=message,
            reply_to_message_ids=message_ids,
            files=[os.path.basename(f) for f in (files or [])]
        )
    else:
        print("❌ 결과 전송 실패!")
        result_text = f"[전송 실패] {result_text}"
        files = []  # 파일 미전송이므로 보낸파일 비움

    # 메인 작업 폴더에 메모리 업데이트
    task_dir = get_task_dir(main_message_id)
    filepath = os.path.join(task_dir, "task_info.txt")

    now = datetime.now()

    # 메시지 ID 정보
    if len(message_ids) > 1:
        msg_id_info = f"{', '.join(map(str, message_ids))} (합산 {len(message_ids)}개)"
        msg_date_info = "\n".join([f"  - msg_{mid}: {ts}" for mid, ts in zip(message_ids, timestamps)])
    else:
        msg_id_info = str(main_message_id)
        msg_date_info = timestamps[0]

    # 메모리 내용 작성
    content = f"""[시간] {now.strftime("%Y-%m-%d %H:%M:%S")}
[메시지ID] {msg_id_info}
[출처] Telegram (chat_id: {chat_id})
[메시지날짜]
{msg_date_info}
[지시] {instruction}
[결과] {result_text}
"""

    if files:
        file_names = [os.path.basename(f) for f in files]
        content += f"[보낸파일] {', '.join(file_names)}\n"

    # 메인 메모리 저장 (덮어쓰기)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    # 메인 메시지 인덱스 업데이트 (작업 완료 상태)
    update_index(
        message_id=main_message_id,
        instruction=instruction,
        result_summary=result_text[:100],  # 결과 요약 (최대 100자)
        files=[os.path.basename(f) for f in (files or [])],
        chat_id=chat_id,
        timestamp=timestamps[0]
    )

    # 추가 메시지들 참조 파일 업데이트
    for i, (msg_id, ts) in enumerate(zip(message_ids[1:], timestamps[1:]), 2):
        ref_dir = get_task_dir(msg_id)
        ref_file = os.path.join(ref_dir, "task_info.txt")
        ref_content = f"""[시간] {now.strftime("%Y-%m-%d %H:%M:%S")}
[메시지ID] {msg_id}
[출처] Telegram (chat_id: {chat_id})
[메시지날짜] {ts}
[지시] (메인 작업 msg_{main_message_id}에 합산됨)
[참조] tasks/msg_{main_message_id}/
[결과] {result_text[:100]}...
"""
        with open(ref_file, "w", encoding="utf-8") as f:
            f.write(ref_content)

        # 인덱스 업데이트
        update_index(
            message_id=msg_id,
            instruction=f"(msg_{main_message_id}에 합산됨)",
            result_summary=result_text[:100],
            files=[],
            chat_id=chat_id,
            timestamp=ts
        )

    print(f"💾 메모리 저장 완료: {task_dir}/task_info.txt")
    if len(message_ids) > 1:
        print(f"   합산 메시지: {len(message_ids)}개 처리 완료")


def mark_done_telegram(message_id):
    """
    텔레그램 메시지 처리 완료 표시

    Args:
        message_id: 메시지 ID (또는 리스트)
    """
    # message_id가 리스트인 경우 (여러 메시지 합산)
    if isinstance(message_id, list):
        message_ids = message_id
    else:
        message_ids = [message_id]

    # 🆕 작업 중에 추가된 새 지시사항도 함께 처리
    new_instructions = load_new_instructions()
    if new_instructions:
        print(f"📝 작업 중 추가된 지시사항 {len(new_instructions)}개 함께 처리")
        for inst in new_instructions:
            message_ids.append(inst["message_id"])

    data = load_telegram_messages()
    messages = data.get("messages", [])

    for msg in messages:
        if msg["message_id"] in message_ids:
            msg["processed"] = True

    save_telegram_messages(data)

    # 🆕 새 지시사항 파일 정리
    clear_new_instructions()

    if len(message_ids) > 1:
        print(f"✅ 메시지 {len(message_ids)}개 처리 완료 표시: {', '.join(map(str, message_ids))}")
    else:
        print(f"✅ 메시지 {message_ids[0]} 처리 완료 표시")


def load_memory():
    """
    기존 메모리 파일 전부 읽기 (tasks/*/task_info.txt)

    Returns:
        list: 메모리 내용 리스트
        [
            {
                "message_id": int,
                "task_dir": str,
                "content": str
            },
            ...
        ]
    """
    if not os.path.exists(TASKS_DIR):
        return []

    memories = []

    # tasks/ 폴더 내 모든 msg_* 폴더 탐색
    for task_folder in os.listdir(TASKS_DIR):
        if task_folder.startswith("msg_"):
            task_dir = os.path.join(TASKS_DIR, task_folder)
            task_info_file = os.path.join(task_dir, "task_info.txt")

            if os.path.exists(task_info_file):
                try:
                    # message_id 추출 (msg_5 → 5)
                    message_id = int(task_folder.split("_")[1])

                    with open(task_info_file, "r", encoding="utf-8") as f:
                        content = f.read()
                        memories.append({
                            "message_id": message_id,
                            "task_dir": task_dir,
                            "content": content
                        })
                except Exception as e:
                    print(f"⚠️ {task_folder}/task_info.txt 읽기 오류: {e}")

    # message_id 역순 정렬 (최신순)
    memories.sort(key=lambda x: x["message_id"], reverse=True)

    return memories


# 테스트 코드
if __name__ == "__main__":
    print("=" * 60)
    print("텔레그램 봇 - 대기 중인 명령 확인")
    print("=" * 60)

    pending = check_telegram()

    if not pending:
        print("\n✅ 대기 중인 명령이 없습니다. 임무 완료!")
    else:
        print(f"\n📋 대기 중인 명령: {len(pending)}개\n")

        for i, task in enumerate(pending, 1):
            print(f"--- 명령 #{i} ---")
            print(f"메시지 ID: {task['message_id']}")
            print(f"사용자: {task['user_name']}")
            print(f"시각: {task['timestamp']}")
            print(f"명령: {task['instruction']}")
            print(f"\n[참고사항 - 최근 24시간 대화]")
            print(task['context_24h'])
            print()
