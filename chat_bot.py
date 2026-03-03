"""
Google Chat 봇 통합 로직 (비서최재형)

telegram_bot.py에서 변환됨. 핵심 비즈니스 로직은 동일.

주요 기능:
- check_chat() - 새로운 명령 확인 (최근 24시간 대화 내역 포함)
- report_chat() - 결과 전송 및 메모리 저장
- mark_done_chat() - 처리 완료 표시
- load_memory() - 기존 메모리 로드
- reserve_memory_chat() - 작업 시작 시 메모리 예약
"""

import os
import sys
import json
import time
from datetime import datetime, timedelta

# Hidden Window 대응: stdout/stderr 없으면 devnull로
if sys.stdout is None or sys.stderr is None:
    _devnull = open(os.devnull, "w", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = _devnull
    if sys.stderr is None:
        sys.stderr = _devnull

from dotenv import load_dotenv
from gchat_sender import send_files_sync, run_async_safe

load_dotenv()

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MESSAGES_FILE = os.path.join(_BASE_DIR, "gchat_messages.json")
TASKS_DIR = os.path.join(_BASE_DIR, "tasks")
INDEX_FILE = os.path.join(_BASE_DIR, "tasks", "index.json")
WORKING_LOCK_FILE = os.path.join(_BASE_DIR, "working.json")
NEW_INSTRUCTIONS_FILE = os.path.join(_BASE_DIR, "new_instructions.json")
WORKING_LOCK_TIMEOUT = int(os.getenv("WORKING_LOCK_TIMEOUT", "180"))
MESSAGE_CLEANUP_DAYS = int(os.getenv("MESSAGE_CLEANUP_DAYS", "30"))
BOT_NAME = os.getenv("BOT_NAME", "AI비서")


def _log_to_brain(msg):
    """bot_brain.log에 직접 기록 (절대 예외를 던지지 않음)"""
    try:
        from datetime import datetime as _dt
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_brain.log"), "a", encoding="utf-8") as f:
            f.write(f"[{_dt.now().strftime('%Y-%m-%d %H:%M:%S')}] [chat_bot] {msg}\n")
            f.flush()
    except:
        pass


def load_chat_messages():
    """gchat_messages.json 로드"""
    if not os.path.exists(MESSAGES_FILE):
        return {"messages": [], "last_update_id": 0}

    try:
        with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        _log_to_brain(f"⚠️ gchat_messages.json 읽기 오류: {e}")
        return {"messages": [], "last_update_id": 0}


def save_chat_messages(data):
    """gchat_messages.json 저장"""
    with open(MESSAGES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_bot_response(chat_id, text, reply_to_message_ids, files=None):
    """
    봇 응답을 gchat_messages.json에 저장 (대화 컨텍스트 유지)

    Args:
        chat_id: Space name (spaces/XXXX)
        text: 봇 응답 메시지
        reply_to_message_ids: 응답 대상 메시지 ID (리스트)
        files: 전송한 파일 리스트 (선택)
    """
    data = load_chat_messages()

    bot_message = {
        "message_id": f"bot_{reply_to_message_ids[0]}",
        "type": "bot",
        "chat_id": chat_id,
        "text": text,
        "files": files or [],
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "reply_to": reply_to_message_ids,
        "processed": True
    }

    data["messages"].append(bot_message)
    save_chat_messages(data)

    _log_to_brain(f"📝 봇 응답 저장 완료 (reply_to: {reply_to_message_ids})")


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
        _log_to_brain(f"⚠️ working.json 읽기 오류: {e}")
        return None

    # PID 생존 확인: 잠금을 생성한 프로세스가 이미 죽었으면 즉시 스탈 처리
    lock_pid = lock_info.get("pid")
    if lock_pid:
        try:
            import subprocess
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {lock_pid}", "/NH"],
                capture_output=True, text=True, timeout=5
            )
            if str(lock_pid) not in result.stdout:
                _log_to_brain(f"⚠️ 잠금 프로세스(PID={lock_pid})가 종료됨 → 스탈 잠금 즉시 해제")
                lock_info["stale"] = True
                return lock_info
        except Exception:
            pass  # 확인 실패 시 타임아웃 기반 체크로 진행

    last_activity_str = lock_info.get("last_activity", lock_info.get("started_at"))

    try:
        last_activity = datetime.strptime(last_activity_str, "%Y-%m-%d %H:%M:%S")
        now = datetime.now()
        idle_seconds = (now - last_activity).total_seconds()

        if idle_seconds > WORKING_LOCK_TIMEOUT:
            _log_to_brain(f"⚠️ 스탈 작업 감지 (마지막 활동: {int(idle_seconds/60)}분 전)")
            _log_to_brain(f"   메시지 ID: {lock_info.get('message_id')}")
            _log_to_brain(f"   지시사항: {lock_info.get('instruction_summary')}")
            lock_info["stale"] = True
            return lock_info

        _log_to_brain(f"ℹ️ 작업 진행 중 (마지막 활동: {int(idle_seconds/60)}분 전)")
        return lock_info

    except Exception as e:
        _log_to_brain(f"⚠️ 타임스탬프 파싱 오류: {e}")
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
    원자적으로 작업 잠금 파일 생성. 이미 존재하면 False 반환. (crash-proof)

    Args:
        message_id: 메시지 ID (또는 리스트)
        instruction: 지시사항

    Returns:
        bool: 생성 성공 여부
    """
    try:
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
            "last_activity": now_str,
            "count": len(message_ids),
            "pid": os.getpid()
        }

        try:
            with open(WORKING_LOCK_FILE, "x", encoding="utf-8") as f:
                json.dump(lock_data, f, ensure_ascii=False, indent=2)
            _log_to_brain(f"🔒 작업 잠금 생성: message_id={msg_id_str}")
            return True
        except FileExistsError:
            _log_to_brain(f"⚠️ 잠금 파일 이미 존재. 다른 작업이 진행 중입니다.")
            return False

    except Exception as e:
        import traceback
        _log_to_brain(f"create_working_lock() CRASHED: {e}\n{traceback.format_exc()}")
        return False


def update_working_activity():
    """작업 잠금의 마지막 활동 시각 갱신 (경과 보고 시 호출)"""
    if not os.path.exists(WORKING_LOCK_FILE):
        return

    try:
        with open(WORKING_LOCK_FILE, "r", encoding="utf-8") as f:
            lock_data = json.load(f)

        lock_data["last_activity"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with open(WORKING_LOCK_FILE, "w", encoding="utf-8") as f:
            json.dump(lock_data, f, ensure_ascii=False, indent=2)

    except Exception as e:
        _log_to_brain(f"⚠️ working.json 활동 갱신 오류: {e}")


def check_new_messages_during_work():
    """
    작업 중 새 메시지 확인 (working.json이 있을 때만)

    Returns:
        list: 새로운 메시지 리스트
    """
    if not os.path.exists(WORKING_LOCK_FILE):
        return []

    try:
        with open(WORKING_LOCK_FILE, "r", encoding="utf-8") as f:
            lock_info = json.load(f)
    except Exception:
        return []

    if lock_info.get("stale"):
        return []

    current_message_ids = lock_info.get("message_id")
    if not isinstance(current_message_ids, list):
        current_message_ids = [current_message_ids]

    already_saved = load_new_instructions()
    saved_message_ids = {inst["message_id"] for inst in already_saved}

    # Google Chat Pub/Sub에서 새 메시지 수집
    _poll_gchat_once()

    data = load_chat_messages()
    messages = data.get("messages", [])

    new_messages = []
    for msg in messages:
        if msg.get("processed", False):
            continue
        if msg["message_id"] in current_message_ids:
            continue
        if msg["message_id"] in saved_message_ids:
            continue

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
    """새 지시사항을 파일에 저장"""
    if not new_messages:
        return

    if os.path.exists(NEW_INSTRUCTIONS_FILE):
        try:
            with open(NEW_INSTRUCTIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {"instructions": []}
    else:
        data = {"instructions": []}

    existing_ids = {inst["message_id"] for inst in data["instructions"]}
    for msg in new_messages:
        if msg["message_id"] not in existing_ids:
            data["instructions"].append(msg)

    with open(NEW_INSTRUCTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    _log_to_brain(f"💾 새 지시사항 저장: {len(new_messages)}개")


def load_new_instructions():
    """저장된 새 지시사항 읽기"""
    if not os.path.exists(NEW_INSTRUCTIONS_FILE):
        return []

    try:
        with open(NEW_INSTRUCTIONS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("instructions", [])
    except Exception as e:
        _log_to_brain(f"⚠️ new_instructions.json 읽기 오류: {e}")
        return []


def clear_new_instructions():
    """새 지시사항 파일 삭제 (작업 완료 후 호출)"""
    if os.path.exists(NEW_INSTRUCTIONS_FILE):
        try:
            os.remove(NEW_INSTRUCTIONS_FILE)
            _log_to_brain("🧹 새 지시사항 파일 정리 완료")
        except OSError as e:
            _log_to_brain(f"⚠️ new_instructions.json 삭제 오류: {e}")


def remove_working_lock():
    """작업 잠금 파일 삭제 (crash-proof)"""
    try:
        if os.path.exists(WORKING_LOCK_FILE):
            os.remove(WORKING_LOCK_FILE)
            _log_to_brain("🔓 작업 잠금 해제")
    except Exception as e:
        import traceback
        _log_to_brain(f"remove_working_lock() CRASHED: {e}\n{traceback.format_exc()}")


def load_index():
    """인덱스 파일 로드"""
    if not os.path.exists(INDEX_FILE):
        return {"tasks": [], "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    try:
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        _log_to_brain(f"⚠️ index.json 읽기 오류: {e}")
        return {"tasks": [], "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


def save_index(index_data):
    """인덱스 파일 저장"""
    if not os.path.exists(TASKS_DIR):
        os.makedirs(TASKS_DIR)

    index_data["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index_data, f, ensure_ascii=False, indent=2)


def update_index(message_id, instruction, result_summary="", files=None, chat_id=None, timestamp=None):
    """인덱스 업데이트 (작업 추가 또는 수정)"""
    index = load_index()

    keywords = []
    for word in instruction.split():
        if len(word) >= 2:
            keywords.append(word)
    keywords = list(set(keywords))[:10]

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
        existing_task.update(task_data)
    else:
        index["tasks"].append(task_data)

    index["tasks"].sort(key=lambda x: str(x["message_id"]), reverse=True)

    save_index(index)
    _log_to_brain(f"📇 인덱스 업데이트: message_id={message_id}")


def search_memory(keyword=None, message_id=None):
    """인덱스에서 작업 검색 (crash-proof)"""
    try:
        index = load_index()

        if message_id is not None:
            for task in index["tasks"]:
                if task["message_id"] == message_id:
                    return [task]
            return []

        if keyword:
            matches = []
            keyword_lower = keyword.lower()

            for task in index["tasks"]:
                if (keyword_lower in task["instruction"].lower() or
                    any(keyword_lower in kw.lower() for kw in task["keywords"])):
                    matches.append(task)

            return matches

        return index["tasks"]

    except Exception as e:
        import traceback
        _log_to_brain(f"search_memory() CRASHED: {e}\n{traceback.format_exc()}")
        return []


def get_task_dir(message_id):
    """메시지 ID 기반 작업 폴더 경로 반환 (crash-proof)"""
    try:
        task_dir = os.path.join(TASKS_DIR, f"msg_{message_id}")

        if not os.path.exists(task_dir):
            os.makedirs(task_dir)
            _log_to_brain(f"📁 작업 폴더 생성: {task_dir}")

        return task_dir

    except Exception as e:
        import traceback
        _log_to_brain(f"get_task_dir() CRASHED: {e}\n{traceback.format_exc()}")
        # Fallback: return a path even if makedirs failed
        return os.path.join(TASKS_DIR, f"msg_{message_id}")


def get_24h_context(messages, current_message_id, chat_id=None):
    """최근 24시간 대화 내역 생성 (사용자 + 봇 응답 모두 포함, chat_id로 필터링)"""
    now = datetime.now()
    cutoff_time = now - timedelta(hours=24)

    context_lines = ["=== 최근 24시간 대화 내역 ===\n"]

    for msg in messages:
        if msg.get("type") == "user" and msg["message_id"] == current_message_id:
            break

        # chat_id(space)가 지정되면 같은 space의 메시지만 포함
        if chat_id and msg.get("chat_id") and msg["chat_id"] != chat_id:
            continue

        msg_time = datetime.strptime(msg["timestamp"], "%Y-%m-%d %H:%M:%S")
        if msg_time < cutoff_time:
            continue

        msg_type = msg.get("type", "user")

        if msg_type == "user":
            user_name = msg.get("first_name", "사용자")
            text = msg.get("text", "")

            files = msg.get("files", [])
            if files:
                file_info = f" [첨부: {len(files)}개 파일]"
            else:
                file_info = ""

            location = msg.get("location")
            if location:
                location_info = f" [위치: {location['latitude']}, {location['longitude']}]"
            else:
                location_info = ""

            context_lines.append(f"[{msg['timestamp']}] {user_name}: {text}{file_info}{location_info}")

        elif msg_type == "bot":
            text = msg.get("text", "")

            if len(text) > 150:
                text_preview = text[:150] + "..."
            else:
                text_preview = text

            files = msg.get("files", [])
            if files:
                file_info = f" [전송: {', '.join(files)}]"
            else:
                file_info = ""

            context_lines.append(f"[{msg['timestamp']}] 🤖 {BOT_NAME}: {text_preview}{file_info}")

    if len(context_lines) == 1:
        return "최근 24시간 이내 대화 내역이 없습니다."

    return "\n".join(context_lines)


def _poll_gchat_once():
    """Google Chat Pub/Sub에서 새 메시지를 한 번 가져와서 json 업데이트"""
    from gchat_listener import fetch_new_messages
    try:
        fetch_new_messages()
    except Exception as e:
        _log_to_brain(f"⚠️ 폴링 중 오류: {e}")


def _cleanup_old_messages():
    """오래된 처리 완료 메시지 정리"""
    data = load_chat_messages()
    messages = data.get("messages", [])

    cutoff = datetime.now() - timedelta(days=MESSAGE_CLEANUP_DAYS)

    cleaned = [
        msg for msg in messages
        if not msg.get("processed", False)
        or datetime.strptime(msg["timestamp"], "%Y-%m-%d %H:%M:%S") > cutoff
    ]

    removed = len(messages) - len(cleaned)
    if removed > 0:
        data["messages"] = cleaned
        save_chat_messages(data)
        _log_to_brain(f"🧹 30일 초과 메시지 {removed}개 정리 완료")


def check_chat():
    """
    새로운 Google Chat 명령 확인 (crash-proof)

    Returns:
        list: 대기 중인 지시사항 리스트
        [
            {
                "instruction": str,
                "message_id": str,
                "chat_id": str,       # space_name (spaces/XXXX)
                "timestamp": str,
                "context_24h": str,
                "user_name": str,
                "stale_resume": bool
            },
            ...
        ]
    """
    try:
        lock_info = check_working_lock()

        if lock_info:
            if lock_info.get("stale"):
                _log_to_brain("🔄 스탈 작업 재시작")

                from gchat_sender import send_message_sync
                message_ids = lock_info.get("message_id")
                if not isinstance(message_ids, list):
                    message_ids = [message_ids]

                data = load_chat_messages()
                messages = data.get("messages", [])
                chat_id = None
                for msg in messages:
                    if msg["message_id"] in message_ids:
                        chat_id = msg["chat_id"]
                        break

                if chat_id:
                    alert_msg = (
                        "⚠️ *이전 작업이 중단되었습니다*\n\n"
                        f"지시사항: {lock_info.get('instruction_summary')}...\n"
                        f"시작 시각: {lock_info.get('started_at')}\n"
                        f"마지막 활동: {lock_info.get('last_activity')}\n\n"
                        "처음부터 다시 시작합니다."
                    )
                    send_message_sync(chat_id, alert_msg)

                try:
                    os.remove(WORKING_LOCK_FILE)
                    _log_to_brain("🔓 스탈 잠금 삭제 완료")
                except OSError:
                    pass

                pending = []
                for msg in messages:
                    if msg["message_id"] in message_ids and not msg.get("processed", False):
                        instruction = msg.get("text", "")
                        message_id = msg["message_id"]
                        chat_id = msg["chat_id"]
                        timestamp = msg["timestamp"]
                        user_name = msg["first_name"]
                        sender_email = msg.get("user_id", "")
                        files = msg.get("files", [])
                        location = msg.get("location")
                        context_24h = get_24h_context(messages, message_id, chat_id)

                        pending.append({
                            "instruction": instruction,
                            "message_id": message_id,
                            "chat_id": chat_id,
                            "timestamp": timestamp,
                            "context_24h": context_24h,
                            "user_name": user_name,
                            "sender_email": sender_email,
                            "files": files,
                            "location": location,
                            "stale_resume": True
                        })

                return pending

            _log_to_brain(f"⚠️ 다른 작업이 진행 중입니다: message_id={lock_info.get('message_id')}")
            _log_to_brain(f"   지시사항: {lock_info.get('instruction_summary')}")
            _log_to_brain(f"   시작 시각: {lock_info.get('started_at')}")
            _log_to_brain(f"   마지막 활동: {lock_info.get('last_activity')}")
            return []

        # Google Chat Pub/Sub에서 새 메시지 수집
        _poll_gchat_once()

        # 30일 초과 처리된 메시지 정리
        _cleanup_old_messages()

        data = load_chat_messages()
        messages = data.get("messages", [])

        pending = []

        for msg in messages:
            if msg.get("processed", False):
                continue

            # bot 메시지는 건너뛰기
            if msg.get("type") == "bot":
                continue

            instruction = msg.get("text", "")
            message_id = msg["message_id"]
            chat_id = msg["chat_id"]
            timestamp = msg["timestamp"]
            user_name = msg["first_name"]
            sender_email = msg.get("user_id", "")
            files = msg.get("files", [])
            location = msg.get("location")

            context_24h = get_24h_context(messages, message_id, chat_id)

            pending.append({
                "instruction": instruction,
                "message_id": message_id,
                "chat_id": chat_id,
                "timestamp": timestamp,
                "context_24h": context_24h,
                "user_name": user_name,
                "sender_email": sender_email,
                "files": files,
                "location": location,
                "stale_resume": False
            })

        return pending

    except Exception as e:
        import traceback
        _log_to_brain(f"check_chat() CRASHED: {e}\n{traceback.format_exc()}")
        return []


def _format_file_size(size_bytes):
    """파일 크기를 사람이 읽기 쉬운 형식으로 변환"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / 1024 / 1024:.1f} MB"


def combine_tasks(pending_tasks):
    """여러 미처리 메시지를 하나의 통합 작업으로 합산 (crash-proof)"""
    try:
        if not pending_tasks:
            return None

        sorted_tasks = sorted(pending_tasks, key=lambda x: x['timestamp'])

        is_stale_resume = any(task.get('stale_resume', False) for task in sorted_tasks)

        combined_parts = []

        if is_stale_resume:
            combined_parts.append("⚠️ [중단된 작업 재시작]")
            combined_parts.append("이전 작업의 진행 상태를 확인한 후, 합리적으로 진행할 것.")
            combined_parts.append("tasks/ 폴더에서 이전 작업 결과물을 확인하고, 이어서 작업할 수 있는 경우 이어서 진행하되,")
            combined_parts.append("처음부터 다시 시작하는 것이 더 안전하다면 처음부터 다시 시작할 것.")
            combined_parts.append("")
            combined_parts.append("---")
            combined_parts.append("")

        all_files = []

        for i, task in enumerate(sorted_tasks, 1):
            combined_parts.append(f"[요청 {i}] ({task['timestamp']})")

            if task['instruction']:
                combined_parts.append(task['instruction'])

            files = task.get('files', [])
            if files:
                combined_parts.append("")
                combined_parts.append("📎 첨부 파일:")
                for file_info in files:
                    file_path = file_info['path']
                    file_name = os.path.basename(file_path)
                    file_type = file_info['type']
                    file_size = _format_file_size(file_info.get('size', 0))

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

                    all_files.append(file_info)

            location = task.get('location')
            if location:
                combined_parts.append("")
                combined_parts.append("📍 위치 정보:")
                combined_parts.append(f"  위도: {location['latitude']}")
                combined_parts.append(f"  경도: {location['longitude']}")

                if 'accuracy' in location:
                    combined_parts.append(f"  정확도: ±{location['accuracy']}m")

                maps_url = f"https://www.google.com/maps?q={location['latitude']},{location['longitude']}"
                combined_parts.append(f"  Google Maps: {maps_url}")

            combined_parts.append("")

        combined_instruction = "\n".join(combined_parts).strip()

        context_24h = sorted_tasks[0]['context_24h']
        if context_24h and context_24h != "최근 24시간 이내 대화 내역이 없습니다.":
            combined_instruction = combined_instruction + "\n\n---\n\n[참고사항]\n" + context_24h

        return {
            "combined_instruction": combined_instruction,
            "message_ids": [task['message_id'] for task in sorted_tasks],
            "chat_id": sorted_tasks[0]['chat_id'],
            "timestamp": sorted_tasks[0]['timestamp'],
            "user_name": sorted_tasks[0]['user_name'],
            "sender_email": sorted_tasks[0].get('sender_email', ''),
            "all_timestamps": [task['timestamp'] for task in sorted_tasks],
            "context_24h": context_24h,
            "files": all_files,
            "stale_resume": is_stale_resume
        }

    except Exception as e:
        import traceback
        _log_to_brain(f"combine_tasks() CRASHED: {e}\n{traceback.format_exc()}")
        return None


def reserve_memory_chat(instruction, chat_id, timestamp, message_id):
    """작업 시작 시 즉시 메모리 예약 (중복 방지, crash-proof)"""
    try:
        if isinstance(message_id, list):
            message_ids = message_id
            main_message_id = message_ids[0]
            timestamps = timestamp if isinstance(timestamp, list) else [timestamp] * len(message_ids)
        else:
            message_ids = [message_id]
            main_message_id = message_id
            timestamps = [timestamp]

        task_dir = get_task_dir(main_message_id)
        filepath = os.path.join(task_dir, "task_info.txt")

        now = datetime.now()

        if len(message_ids) > 1:
            msg_id_info = f"{', '.join(map(str, message_ids))} (합산 {len(message_ids)}개)"
            msg_date_info = "\n".join([f"  - msg_{mid}: {ts}" for mid, ts in zip(message_ids, timestamps)])
        else:
            msg_id_info = str(main_message_id)
            msg_date_info = timestamps[0]

        content = f"""[시간] {now.strftime("%Y-%m-%d %H:%M:%S")}
[메시지ID] {msg_id_info}
[출처] Google Chat (space: {chat_id})
[메시지날짜]
{msg_date_info}
[지시] {instruction}
[결과] (작업 진행 중...)
"""

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        update_index(
            message_id=main_message_id,
            instruction=instruction,
            result_summary="(작업 진행 중...)",
            files=[],
            chat_id=chat_id,
            timestamp=timestamps[0]
        )

        for i, (msg_id, ts) in enumerate(zip(message_ids[1:], timestamps[1:]), 2):
            ref_dir = get_task_dir(msg_id)
            ref_file = os.path.join(ref_dir, "task_info.txt")
            ref_content = f"""[시간] {now.strftime("%Y-%m-%d %H:%M:%S")}
[메시지ID] {msg_id}
[출처] Google Chat (space: {chat_id})
[메시지날짜] {ts}
[지시] (메인 작업 msg_{main_message_id}에 합산됨)
[참조] tasks/msg_{main_message_id}/
[결과] (작업 진행 중...)
"""
            with open(ref_file, "w", encoding="utf-8") as f:
                f.write(ref_content)

            update_index(
                message_id=msg_id,
                instruction=f"(msg_{main_message_id}에 합산됨)",
                result_summary="(작업 진행 중...)",
                files=[],
                chat_id=chat_id,
                timestamp=ts
            )

        _log_to_brain(f"📝 메모리 예약 완료: {task_dir}/task_info.txt")
        if len(message_ids) > 1:
            _log_to_brain(f"   합산 메시지: {len(message_ids)}개 ({', '.join(map(str, message_ids))})")

    except Exception as e:
        import traceback
        _log_to_brain(f"reserve_memory_chat() CRASHED: {e}\n{traceback.format_exc()}")


def report_chat(instruction, result_text, chat_id, timestamp, message_id, files=None):
    """작업 결과를 Google Chat으로 전송하고 메모리에 저장 (crash-proof)"""
    try:
        if isinstance(message_id, list):
            message_ids = message_id
            main_message_id = message_ids[0]
            timestamps = timestamp if isinstance(timestamp, list) else [timestamp] * len(message_ids)
        else:
            message_ids = [message_id]
            main_message_id = message_id
            timestamps = [timestamp]

        message = f"""🤖 *{BOT_NAME} 작업 완료*

*✅ 결과:*
{result_text}
"""

        if files:
            file_names = [os.path.basename(f) for f in files]
            message += f"\n*📎 첨부 파일:* {', '.join(file_names)}"

        if len(message_ids) > 1:
            message += f"\n\n_합산 처리: {len(message_ids)}개 메시지_"

        _log_to_brain(f"\n📤 Google Chat으로 결과 전송 중... (space: {chat_id})")
        success = send_files_sync(chat_id, message, files or [])

        if success:
            _log_to_brain("✅ 결과 전송 완료!")
            save_bot_response(
                chat_id=chat_id,
                text=message,
                reply_to_message_ids=message_ids,
                files=[os.path.basename(f) for f in (files or [])]
            )
        else:
            _log_to_brain("❌ 결과 전송 실패!")
            result_text = f"[전송 실패] {result_text}"
            files = []

        task_dir = get_task_dir(main_message_id)
        filepath = os.path.join(task_dir, "task_info.txt")

        now = datetime.now()

        if len(message_ids) > 1:
            msg_id_info = f"{', '.join(map(str, message_ids))} (합산 {len(message_ids)}개)"
            msg_date_info = "\n".join([f"  - msg_{mid}: {ts}" for mid, ts in zip(message_ids, timestamps)])
        else:
            msg_id_info = str(main_message_id)
            msg_date_info = timestamps[0]

        content = f"""[시간] {now.strftime("%Y-%m-%d %H:%M:%S")}
[메시지ID] {msg_id_info}
[출처] Google Chat (space: {chat_id})
[메시지날짜]
{msg_date_info}
[지시] {instruction}
[결과] {result_text}
"""

        if files:
            file_names = [os.path.basename(f) for f in files]
            content += f"[보낸파일] {', '.join(file_names)}\n"

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        update_index(
            message_id=main_message_id,
            instruction=instruction,
            result_summary=result_text[:100],
            files=[os.path.basename(f) for f in (files or [])],
            chat_id=chat_id,
            timestamp=timestamps[0]
        )

        for i, (msg_id, ts) in enumerate(zip(message_ids[1:], timestamps[1:]), 2):
            ref_dir = get_task_dir(msg_id)
            ref_file = os.path.join(ref_dir, "task_info.txt")
            ref_content = f"""[시간] {now.strftime("%Y-%m-%d %H:%M:%S")}
[메시지ID] {msg_id}
[출처] Google Chat (space: {chat_id})
[메시지날짜] {ts}
[지시] (메인 작업 msg_{main_message_id}에 합산됨)
[참조] tasks/msg_{main_message_id}/
[결과] {result_text[:100]}...
"""
            with open(ref_file, "w", encoding="utf-8") as f:
                f.write(ref_content)

            update_index(
                message_id=msg_id,
                instruction=f"(msg_{main_message_id}에 합산됨)",
                result_summary=result_text[:100],
                files=[],
                chat_id=chat_id,
                timestamp=ts
            )

        _log_to_brain(f"💾 메모리 저장 완료: {task_dir}/task_info.txt")
        if len(message_ids) > 1:
            _log_to_brain(f"   합산 메시지: {len(message_ids)}개 처리 완료")

    except Exception as e:
        import traceback
        _log_to_brain(f"report_chat() CRASHED: {e}\n{traceback.format_exc()}")


def mark_done_chat(message_id):
    """Google Chat 메시지 처리 완료 표시 (crash-proof)"""
    try:
        if isinstance(message_id, list):
            message_ids = message_id
        else:
            message_ids = [message_id]

        new_instructions = load_new_instructions()
        if new_instructions:
            _log_to_brain(f"📝 작업 중 추가된 지시사항 {len(new_instructions)}개 함께 처리")
            for inst in new_instructions:
                message_ids.append(inst["message_id"])

        data = load_chat_messages()
        messages = data.get("messages", [])

        for msg in messages:
            if msg["message_id"] in message_ids:
                msg["processed"] = True

        save_chat_messages(data)

        clear_new_instructions()

        if len(message_ids) > 1:
            _log_to_brain(f"✅ 메시지 {len(message_ids)}개 처리 완료 표시: {', '.join(map(str, message_ids))}")
        else:
            _log_to_brain(f"✅ 메시지 {message_ids[0]} 처리 완료 표시")

    except Exception as e:
        import traceback
        _log_to_brain(f"mark_done_chat() CRASHED: {e}\n{traceback.format_exc()}")


def load_memory():
    """기존 메모리 파일 전부 읽기 (tasks/*/task_info.txt, crash-proof)"""
    try:
        if not os.path.exists(TASKS_DIR):
            return []

        memories = []

        for task_folder in os.listdir(TASKS_DIR):
            if task_folder.startswith("msg_"):
                task_dir = os.path.join(TASKS_DIR, task_folder)
                task_info_file = os.path.join(task_dir, "task_info.txt")

                if os.path.exists(task_info_file):
                    try:
                        message_id = task_folder.split("_", 1)[1]
                        # 숫자면 int로, 아니면 str 유지 (Google Chat은 문자열 ID)
                        try:
                            message_id = int(message_id)
                        except ValueError:
                            pass

                        with open(task_info_file, "r", encoding="utf-8") as f:
                            content = f.read()
                            memories.append({
                                "message_id": message_id,
                                "task_dir": task_dir,
                                "content": content
                            })
                    except Exception as e:
                        _log_to_brain(f"⚠️ {task_folder}/task_info.txt 읽기 오류: {e}")

        memories.sort(key=lambda x: str(x["message_id"]), reverse=True)

        return memories

    except Exception as e:
        import traceback
        _log_to_brain(f"load_memory() CRASHED: {e}\n{traceback.format_exc()}")
        return []


# ===== 하위 호환 별칭 (기존 코드에서 telegram 함수명으로 호출해도 동작) =====
check_telegram = check_chat
report_telegram = report_chat
mark_done_telegram = mark_done_chat
reserve_memory_telegram = reserve_memory_chat
load_telegram_messages = load_chat_messages
save_telegram_messages = save_chat_messages


# 테스트 코드
if __name__ == "__main__":
    _log_to_brain("=" * 60)
    _log_to_brain(f"Google Chat {BOT_NAME} - 대기 중인 명령 확인")
    _log_to_brain("=" * 60)

    pending = check_chat()

    if not pending:
        _log_to_brain("\n✅ 대기 중인 명령이 없습니다. 임무 완료!")
    else:
        _log_to_brain(f"\n📋 대기 중인 명령: {len(pending)}개\n")

        for i, task in enumerate(pending, 1):
            _log_to_brain(f"--- 명령 #{i} ---")
            _log_to_brain(f"메시지 ID: {task['message_id']}")
            _log_to_brain(f"사용자: {task['user_name']}")
            _log_to_brain(f"시각: {task['timestamp']}")
            _log_to_brain(f"명령: {task['instruction']}")
            _log_to_brain(f"\n[참고사항 - 최근 24시간 대화]")
            _log_to_brain(task['context_24h'])
            _log_to_brain("")
