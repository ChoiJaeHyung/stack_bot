"""
Google Chat 응답 전송기 (Sender)

역할:
- Claude Code 작업 결과를 Google Chat으로 전송
- 텍스트 메시지 및 파일 첨부 지원 (Google Drive 업로드 + 링크 공유)
- telegram_sender.py와 동일한 인터페이스 제공

사용법:
    from gchat_sender import send_message, send_files

    # 텍스트 메시지 전송
    await send_message(space_name, "메시지 내용")

    # 파일과 함께 전송
    await send_files(space_name, "메시지 내용", ["파일1.txt", "파일2.png"])
"""

import os
import sys
import asyncio
import mimetypes
from datetime import datetime
from dotenv import load_dotenv

# Hidden Window 대응: stdout/stderr 없으면 devnull로
if sys.stdout is None or sys.stderr is None:
    _devnull = open(os.devnull, "w", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = _devnull
    if sys.stderr is None:
        sys.stderr = _devnull

# .env 파일 로드
load_dotenv()

# ─── 로깅 설정 (bot_brain.py와 동일한 패턴) ───
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "bot_brain.log")


def _log(msg):
    """로그 메시지를 bot_brain.log에 직접 기록 (flush 즉시)"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [gchat_sender] {msg}\n"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
    except Exception:
        pass


CREDENTIALS_FILE = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "./service-account-key.json")
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "")

# Google Chat API 스코프
CHAT_SCOPES = ['https://www.googleapis.com/auth/chat.bot']
# Google Drive API 스코프 (파일 업로드용)
DRIVE_SCOPES = ['https://www.googleapis.com/auth/drive.file']

# Google Chat 메시지 길이 제한
GCHAT_MESSAGE_LIMIT = int(os.getenv("GCHAT_MESSAGE_LIMIT", "4096"))
GCHAT_SAFE_LIMIT = GCHAT_MESSAGE_LIMIT - 96  # 안전 마진 포함


def _get_credentials_path():
    """서비스 계정 키 파일의 절대 경로를 반환"""
    cred_path = CREDENTIALS_FILE
    if not os.path.isabs(cred_path):
        # 상대 경로인 경우 프로젝트 루트 기준으로 변환
        project_root = os.path.dirname(os.path.abspath(__file__))
        cred_path = os.path.join(project_root, cred_path)
    return cred_path


def _validate_credentials():
    """서비스 계정 키 파일 존재 여부 확인"""
    try:
        cred_path = _get_credentials_path()
        if not os.path.exists(cred_path):
            _log(f"CREDENTIALS 파일 없음: {cred_path}")
            return False
        return True
    except Exception as e:
        _log(f"CREDENTIALS 검증 오류: {e}")
        return False


def _build_chat_service():
    """Google Chat API 서비스 객체 생성. 실패 시 None 반환."""
    try:
        from googleapiclient.discovery import build
        from google.oauth2 import service_account

        cred_path = _get_credentials_path()
        credentials = service_account.Credentials.from_service_account_file(
            cred_path, scopes=CHAT_SCOPES
        )
        return build('chat', 'v1', credentials=credentials)
    except Exception as e:
        _log(f"Chat 서비스 생성 실패: {e}")
        return None


def _build_drive_service():
    """Google Drive API 서비스 객체 생성. 실패 시 None 반환."""
    try:
        from googleapiclient.discovery import build
        from google.oauth2 import service_account

        cred_path = _get_credentials_path()
        credentials = service_account.Credentials.from_service_account_file(
            cred_path, scopes=DRIVE_SCOPES
        )
        return build('drive', 'v3', credentials=credentials)
    except Exception as e:
        _log(f"Drive 서비스 생성 실패: {e}")
        return None


def _send_message_impl(space_name, text, parse_mode="Markdown"):
    """
    Google Chat 메시지 전송 (동기 구현부)

    Args:
        space_name: Google Chat space 이름 (e.g., "spaces/XXXXXXX")
        text: 전송할 메시지
        parse_mode: 파싱 모드 (호환성을 위해 유지, Google Chat은 자체 포맷 사용)

    Returns:
        bool: 성공 여부. 절대 예외를 발생시키지 않는다.
    """
    try:
        if not _validate_credentials():
            return False

        chat_service = _build_chat_service()
        if chat_service is None:
            _log("메시지 전송 실패: Chat 서비스 객체 생성 불가")
            return False

        # Google Chat 메시지 길이 제한 (~4096자)
        if len(text) > GCHAT_SAFE_LIMIT:
            # 긴 메시지는 분할 전송
            chunks = _split_message(text, GCHAT_SAFE_LIMIT)
            for i, chunk in enumerate(chunks):
                if i > 0:
                    import time
                    time.sleep(0.5)  # 연속 전송 시 잠시 대기
                chat_service.spaces().messages().create(
                    parent=space_name,
                    body={'text': chunk}
                ).execute()
        else:
            chat_service.spaces().messages().create(
                parent=space_name,
                body={'text': text}
            ).execute()

        return True

    except Exception as e:
        _log(f"메시지 전송 실패 (space={space_name}): {e}")
        return False


def _split_message(text, limit):
    """
    긴 메시지를 지정된 길이로 분할

    줄바꿈 기준으로 분할을 시도하고, 불가능하면 강제 분할.

    Args:
        text: 분할할 텍스트
        limit: 최대 글자 수

    Returns:
        list[str]: 분할된 메시지 리스트
    """
    if len(text) <= limit:
        return [text]

    chunks = []
    remaining = text

    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break

        # 줄바꿈 기준으로 분할 시도
        split_pos = remaining.rfind('\n', 0, limit)
        if split_pos == -1 or split_pos < limit // 2:
            # 줄바꿈이 없거나 너무 앞에 있으면 공백 기준 분할
            split_pos = remaining.rfind(' ', 0, limit)
            if split_pos == -1 or split_pos < limit // 2:
                # 공백도 없으면 강제 분할
                split_pos = limit

        chunks.append(remaining[:split_pos])
        remaining = remaining[split_pos:].lstrip('\n')

    return chunks


def _upload_file_to_drive(file_path):
    """
    Google Drive에 파일 업로드 후 공유 링크 반환

    Args:
        file_path: 업로드할 파일의 로컬 경로

    Returns:
        dict: {'id': file_id, 'webViewLink': url, 'name': filename} 또는 실패 시 None
    """
    try:
        from googleapiclient.http import MediaFileUpload

        drive_service = _build_drive_service()
        if drive_service is None:
            _log("파일 업로드 실패: Drive 서비스 객체 생성 불가")
            return None

        filename = os.path.basename(file_path)

        # MIME 타입 추정
        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type is None:
            mime_type = 'application/octet-stream'

        # 파일 업로드
        file_metadata = {'name': filename}
        media = MediaFileUpload(file_path, mimetype=mime_type, resumable=True)
        uploaded_file = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id,webViewLink,name'
        ).execute()

        # 공유 권한 설정 (링크가 있는 모든 사용자가 읽기 가능)
        drive_service.permissions().create(
            fileId=uploaded_file['id'],
            body={'type': 'anyone', 'role': 'reader'}
        ).execute()

        return uploaded_file

    except Exception as e:
        _log(f"파일 업로드 실패 ({os.path.basename(file_path)}): {e}")
        return None


def _send_file_impl(space_name, file_path, caption=None):
    """
    Google Drive 업로드 후 Google Chat에 다운로드 링크 전송 (동기 구현부)

    Args:
        space_name: Google Chat space 이름
        file_path: 파일 경로
        caption: 파일 설명 (선택)

    Returns:
        bool: 성공 여부. 절대 예외를 발생시키지 않는다.
    """
    try:
        if not _validate_credentials():
            return False

        if not os.path.exists(file_path):
            _log(f"파일을 찾을 수 없음: {file_path}")
            return False

        # 파일 크기 확인
        file_size = os.path.getsize(file_path)
        file_size_mb = file_size / (1024 * 1024)

        # Google Drive 업로드 제한: 5TB (사실상 제한 없음)
        # 하지만 서비스 계정 용량 제한이 있을 수 있으므로 경고
        if file_size > 100 * 1024 * 1024:
            _log(f"대용량 파일 업로드 시작 ({file_size_mb:.1f}MB): {file_path}")

        # Google Drive에 업로드
        uploaded = _upload_file_to_drive(file_path)
        if not uploaded:
            return False

        # Google Chat에 링크 메시지 전송
        filename = os.path.basename(file_path)
        file_size_str = _format_file_size(file_size)

        if caption:
            text = f"{caption}\n\n{filename} ({file_size_str})\n{uploaded.get('webViewLink', 'Link unavailable')}"
        else:
            text = f"{filename} ({file_size_str})\n{uploaded.get('webViewLink', 'Link unavailable')}"

        return _send_message_impl(space_name, text)

    except Exception as e:
        _log(f"파일 전송 실패 ({file_path}): {e}")
        return False


def _format_file_size(size_bytes):
    """파일 크기를 사람이 읽기 좋은 형식으로 변환"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


# ============================================================
# Public API - telegram_sender.py와 동일한 인터페이스
# ============================================================

async def send_message(space_name, text, parse_mode="Markdown"):
    """
    Google Chat 메시지 전송 (비동기)

    Args:
        space_name: Google Chat space 이름 (e.g., "spaces/XXXXXXX")
        text: 전송할 메시지
        parse_mode: 파싱 모드 (호환성 유지, Google Chat은 자체 포맷 사용)

    Returns:
        bool: 성공 여부
    """
    # Google API 클라이언트는 동기식이므로 to_thread로 래핑
    return await asyncio.to_thread(_send_message_impl, space_name, text, parse_mode)


async def send_file(space_name, file_path, caption=None):
    """
    Google Drive 업로드 후 Google Chat에 파일 링크 전송 (비동기)

    Args:
        space_name: Google Chat space 이름
        file_path: 파일 경로
        caption: 파일 설명 (선택)

    Returns:
        bool: 성공 여부
    """
    return await asyncio.to_thread(_send_file_impl, space_name, file_path, caption)


async def send_files(space_name, text, file_paths):
    """
    Google Chat 메시지 + 여러 파일 전송 (비동기)

    Args:
        space_name: Google Chat space 이름
        text: 메시지 내용
        file_paths: 파일 경로 리스트

    Returns:
        bool: 성공 여부. 절대 예외를 발생시키지 않는다.
    """
    try:
        # 먼저 메시지 전송
        success = await send_message(space_name, text)

        if not success:
            return False

        # 파일이 없으면 종료
        if not file_paths:
            return True

        # 파일들 전송
        for i, file_path in enumerate(file_paths):
            if i > 0:
                await asyncio.sleep(0.5)  # 연속 전송 시 잠시 대기

            file_name = os.path.basename(file_path)
            _log(f"파일 전송 중: {file_name}")

            success = await send_file(space_name, file_path, caption=f"  {file_name}")

            if success:
                _log(f"파일 전송 완료: {file_name}")
            else:
                _log(f"파일 전송 실패: {file_name}")

        return True

    except Exception as e:
        _log(f"send_files 오류 (space={space_name}): {e}")
        return False


def run_async_safe(coro):
    """이벤트 루프가 이미 실행 중이면 별도 스레드에서 실행. 실패 시 False 반환."""
    try:
        asyncio.get_running_loop()
        # 루프가 실행 중 -> 별도 스레드에서 새 루프 생성
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    except RuntimeError:
        # 실행 중인 루프 없음 -> 직접 실행
        return asyncio.run(coro)
    except Exception as e:
        _log(f"run_async_safe 오류: {e}")
        return False


# ============================================================
# 동기 함수 래퍼 (가장 자주 사용됨)
# ============================================================

def send_message_sync(space_name, text, parse_mode="Markdown"):
    """
    동기 방식 메시지 전송

    메시지 전송 시마다:
    1. working.json의 last_activity 갱신
    2. 새 메시지 확인 및 저장 (작업 중일 때만)

    Args:
        space_name: Google Chat space 이름 (e.g., "spaces/XXXXXXX")
        text: 전송할 메시지
        parse_mode: 파싱 모드 (호환성 유지)

    Returns:
        bool: 성공 여부. 절대 예외를 발생시키지 않는다.
    """
    try:
        # 동기 구현부를 직접 호출 (async 래핑 불필요)
        result = _send_message_impl(space_name, text, parse_mode)

        # 메시지 전송 성공 시 부수 효과 실행
        if result:
            try:
                from chat_bot import (
                    update_working_activity,
                    check_new_messages_during_work,
                    save_new_instructions
                )

                # 1. 활동 시각 갱신
                update_working_activity()

                # 2. 새 메시지 확인
                new_msgs = check_new_messages_during_work()
                if new_msgs:
                    # 파일에 저장
                    save_new_instructions(new_msgs)

                    # 알림 전송
                    alert_text = f"**새로운 요청 {len(new_msgs)}개 확인**\n\n"
                    for i, msg in enumerate(new_msgs, 1):
                        instruction_preview = msg.get('instruction', '')[:50]
                        alert_text += f"{i}. {instruction_preview}...\n"
                    alert_text += "\n진행 중인 작업에 반영하겠습니다."

                    # 재귀 호출 방지 (알림은 활동 갱신만 하고 새 메시지 확인 안 함)
                    _send_message_impl(space_name, alert_text, parse_mode)

            except ImportError:
                # chat_bot 모듈이 아직 없는 경우 무시
                pass
            except Exception as e:
                # 갱신 실패해도 메시지 전송 결과에는 영향 없음
                _log(f"send_message_sync 부수 효과 오류 (메시지 전송은 성공): {e}")

        return result

    except Exception as e:
        _log(f"send_message_sync 치명적 오류 (space={space_name}): {e}")
        return False


def send_files_sync(space_name, text, file_paths):
    """
    동기 방식 파일 전송

    Args:
        space_name: Google Chat space 이름
        text: 메시지 내용
        file_paths: 파일 경로 리스트

    Returns:
        bool: 성공 여부. 절대 예외를 발생시키지 않는다.
    """
    try:
        return run_async_safe(send_files(space_name, text, file_paths))
    except Exception as e:
        _log(f"send_files_sync 오류 (space={space_name}): {e}")
        return False


# ============================================================
# 테스트
# ============================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python gchat_sender.py <space_name> <message>")
        print("Example: python gchat_sender.py spaces/XXXXXXX 'Test message'")
        sys.exit(1)

    space_name = sys.argv[1]
    message = sys.argv[2]

    print(f"Sending message to: {space_name}")
    success = send_message_sync(space_name, message)

    if success:
        print("Success!")
    else:
        print("Failed!")
