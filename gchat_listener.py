"""
Google Chat Pub/Sub 메시지 수집기 (Listener)

역할:
- Google Cloud Pub/Sub를 통해 Google Chat 메시지 수신
- gchat_messages.json에 메시지 저장
- 허용 도메인 기반 사용자 검증 (GCHAT_ALLOWED_DOMAIN)
- STACK API 연동으로 등록 사용자 동적 확인 (SSO 매칭)
- 첨부 파일 다운로드 (Google Drive 또는 Chat API)
- 중복 메시지 방지

사용법:
    python gchat_listener.py
    (Ctrl+C로 종료)

환경 변수 (.env):
    GOOGLE_APPLICATION_CREDENTIALS=./service-account-key.json
    GCP_PROJECT_ID=<project-id>
    PUBSUB_SUBSCRIPTION_ID=jaehyung-bot-sub
    GCHAT_ALLOWED_DOMAIN=rsupport.com
"""

import os
import sys
import io
import json
import time
import base64
import traceback
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

GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "./service-account-key.json")
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "")
PUBSUB_SUBSCRIPTION_ID = os.getenv("PUBSUB_SUBSCRIPTION_ID", "")
GCHAT_ALLOWED_DOMAIN = os.getenv("GCHAT_ALLOWED_DOMAIN", "")
STACK_API_URL = os.getenv("STACK_API_URL", "")
STACK_API_KEY = os.getenv("STACK_API_KEY", "")
POLLING_INTERVAL = int(os.getenv("GCHAT_POLLING_INTERVAL", "10"))

# STACK API 사용자 검증 캐시 (TTL: 프로세스 수명)
_verified_users_cache = {}  # email -> bool

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MESSAGES_FILE = os.path.join(_BASE_DIR, "gchat_messages.json")
LOG_FILE = os.path.join(_BASE_DIR, "bot_brain.log")

# GOOGLE_APPLICATION_CREDENTIALS 환경 변수 설정 (google 라이브러리가 참조)
if GOOGLE_APPLICATION_CREDENTIALS:
    # 상대 경로인 경우 프로젝트 루트 기준으로 절대 경로 변환
    if not os.path.isabs(GOOGLE_APPLICATION_CREDENTIALS):
        abs_cred_path = os.path.join(_BASE_DIR, GOOGLE_APPLICATION_CREDENTIALS)
    else:
        abs_cred_path = GOOGLE_APPLICATION_CREDENTIALS
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = abs_cred_path


def log(msg):
    """로그 메시지를 bot_brain.log에 직접 기록 (flush 즉시)"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [gchat_listener] {msg}\n"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
    except Exception:
        pass


def _is_allowed_user(sender_email):
    """
    사용자 허용 여부를 동적으로 검증

    1단계: 도메인 검증 (GCHAT_ALLOWED_DOMAIN)
    2단계: STACK API에서 사용자 존재 확인 (SSO 매칭: email = STACK username)

    캐시를 사용하여 동일 프로세스 내 반복 API 호출 방지.

    Args:
        sender_email: Google Chat 발신자 이메일

    Returns:
        bool: 허용이면 True
    """
    if not sender_email:
        return False

    # 캐시 확인
    if sender_email in _verified_users_cache:
        return _verified_users_cache[sender_email]

    # 1단계: 도메인 검증
    if GCHAT_ALLOWED_DOMAIN:
        email_domain = sender_email.split("@")[-1] if "@" in sender_email else ""
        if email_domain.lower() != GCHAT_ALLOWED_DOMAIN.lower():
            log(f"[AUTH] 도메인 불일치: {sender_email} (허용: {GCHAT_ALLOWED_DOMAIN})")
            _verified_users_cache[sender_email] = False
            return False

    # 2단계: STACK API 사용자 검증 (SSO 매칭)
    if STACK_API_URL and STACK_API_KEY:
        try:
            import requests as _req
            # STACK에서 username(=email)으로 사용자 검색
            username = sender_email.split("@")[0] if "@" in sender_email else sender_email
            resp = _req.get(
                f"{STACK_API_URL}/api/users/search",
                params={"keyword": username},
                headers={"X-API-Key": STACK_API_KEY},
                timeout=5
            )
            if resp.status_code == 200:
                users = resp.json() if isinstance(resp.json(), list) else resp.json().get("data", [])
                # email 또는 username 매칭 확인
                found = any(
                    u.get("email", "").lower() == sender_email.lower()
                    or u.get("username", "").lower() == sender_email.lower()
                    for u in (users if isinstance(users, list) else [])
                )
                if found:
                    log(f"[AUTH] STACK 사용자 확인됨: {sender_email}")
                    _verified_users_cache[sender_email] = True
                    return True
                else:
                    log(f"[AUTH] STACK에 사용자 없음: {sender_email}")
                    _verified_users_cache[sender_email] = False
                    return False
            else:
                log(f"[AUTH] STACK API 응답 오류 ({resp.status_code}), 도메인만으로 허용")
        except Exception as e:
            log(f"[AUTH] STACK API 호출 실패: {e}, 도메인만으로 허용")

    # STACK API 미설정 또는 오류 시 → 도메인 검증만 통과하면 허용
    _verified_users_cache[sender_email] = True
    return True


def load_messages():
    """저장된 메시지 로드"""
    if os.path.exists(MESSAGES_FILE):
        try:
            with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[WARN] gchat_messages.json 읽기 오류: {e}")

    return {
        "messages": [],
        "last_update_id": 0
    }


def save_messages(data):
    """메시지 저장"""
    with open(MESSAGES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _extract_message_id(resource_name):
    """
    Google Chat 메시지 리소스 이름에서 메시지 ID 추출

    Args:
        resource_name: "spaces/XXX/messages/YYY" 형식

    Returns:
        str: 메시지 ID (마지막 세그먼트, 예: "YYY")
    """
    if not resource_name:
        return None
    parts = resource_name.split("/")
    if len(parts) >= 4 and parts[-2] == "messages":
        return parts[-1]
    # fallback: 마지막 세그먼트 반환
    return parts[-1] if parts else None


def _extract_space_name(event_data):
    """
    이벤트에서 space name 추출

    Args:
        event_data: Pub/Sub 이벤트 JSON

    Returns:
        str: "spaces/XXXXXXX" 형식
    """
    # message.space.name 우선
    space_name = None
    message = event_data.get("message", {})
    if message.get("space", {}).get("name"):
        space_name = message["space"]["name"]
    elif event_data.get("space", {}).get("name"):
        space_name = event_data["space"]["name"]

    return space_name or ""


def _parse_timestamp(time_str):
    """
    Google Chat 타임스탬프를 로컬 포맷으로 변환

    Args:
        time_str: "2026-02-13T10:00:00Z" 또는 "2026-02-13T10:00:00.123456Z" 형식

    Returns:
        str: "2026-02-13 10:00:00" 형식
    """
    if not time_str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        # Z 접미사 제거, 마이크로초 처리
        clean = time_str.rstrip("Z")
        # 마이크로초가 있으면 제거 (6자리 초과 대응)
        if "." in clean:
            date_part, frac = clean.split(".", 1)
            frac = frac[:6]  # 최대 6자리
            clean = f"{date_part}.{frac}"
            dt = datetime.strptime(clean, "%Y-%m-%dT%H:%M:%S.%f")
        else:
            dt = datetime.strptime(clean, "%Y-%m-%dT%H:%M:%S")
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, AttributeError):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _is_duplicate(data, message_id):
    """
    중복 메시지 확인

    Args:
        data: 메시지 데이터
        message_id: 확인할 메시지 ID

    Returns:
        bool: 중복이면 True
    """
    for msg in data.get("messages", []):
        if msg["message_id"] == message_id:
            return True
    return False


def _download_drive_file(drive_file_id, save_dir, file_name):
    """
    Google Drive에서 파일 다운로드

    Args:
        drive_file_id: Google Drive 파일 ID
        save_dir: 저장 디렉토리
        file_name: 저장할 파일명

    Returns:
        str: 다운로드된 파일 경로 (실패 시 None)
    """
    try:
        from googleapiclient.discovery import build
        from google.oauth2 import service_account

        cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
        if not cred_path or not os.path.exists(cred_path):
            print(f"[ERROR] 서비스 계정 키 파일 없음: {cred_path}")
            return None

        credentials = service_account.Credentials.from_service_account_file(
            cred_path,
            scopes=["https://www.googleapis.com/auth/drive.readonly"]
        )
        service = build("drive", "v3", credentials=credentials)

        # 파일 메타데이터 가져오기 (Google Workspace 파일 여부 확인)
        file_meta = service.files().get(
            fileId=drive_file_id,
            fields="mimeType,name,size"
        ).execute()

        google_export_mimes = {
            "application/vnd.google-apps.document": (
                "application/pdf", ".pdf"
            ),
            "application/vnd.google-apps.spreadsheet": (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"
            ),
            "application/vnd.google-apps.presentation": (
                "application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"
            ),
            "application/vnd.google-apps.drawing": (
                "image/png", ".png"
            ),
        }

        mime_type = file_meta.get("mimeType", "")
        os.makedirs(save_dir, exist_ok=True)
        local_path = os.path.join(save_dir, file_name)

        if mime_type in google_export_mimes:
            # Google Workspace 파일은 export 사용
            export_mime, ext = google_export_mimes[mime_type]
            # 확장자가 없으면 추가
            if not os.path.splitext(file_name)[1]:
                local_path = local_path + ext

            request = service.files().export_media(
                fileId=drive_file_id,
                mimeType=export_mime
            )
        else:
            # 일반 파일은 직접 다운로드
            request = service.files().get_media(fileId=drive_file_id)

        from googleapiclient.http import MediaIoBaseDownload
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)

        done = False
        while not done:
            status, done = downloader.next_chunk()

        fh.seek(0)
        with open(local_path, "wb") as f:
            f.write(fh.read())

        file_size = os.path.getsize(local_path)
        print(f"[FILE] Drive 파일 다운로드: {file_name} ({file_size} bytes)")
        return local_path

    except Exception as e:
        print(f"[ERROR] Drive 파일 다운로드 실패 (fileId={drive_file_id}): {e}")
        return None


def _download_chat_attachment(attachment_name, save_dir, file_name):
    """
    Google Chat API media endpoint로 첨부 파일 다운로드

    Args:
        attachment_name: Chat API 리소스 이름 (spaces/XXX/messages/YYY/attachments/ZZZ)
        save_dir: 저장 디렉토리
        file_name: 저장할 파일명

    Returns:
        str: 다운로드된 파일 경로 (실패 시 None)
    """
    try:
        from googleapiclient.discovery import build
        from google.oauth2 import service_account

        cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
        if not cred_path or not os.path.exists(cred_path):
            print(f"[ERROR] 서비스 계정 키 파일 없음: {cred_path}")
            return None

        credentials = service_account.Credentials.from_service_account_file(
            cred_path,
            scopes=["https://www.googleapis.com/auth/chat.bot"]
        )
        service = build("chat", "v1", credentials=credentials)

        os.makedirs(save_dir, exist_ok=True)
        local_path = os.path.join(save_dir, file_name)

        # Chat API media download
        media = service.media().download(resourceName=attachment_name)

        from googleapiclient.http import MediaIoBaseDownload
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, media)

        done = False
        while not done:
            status, done = downloader.next_chunk()

        fh.seek(0)
        with open(local_path, "wb") as f:
            f.write(fh.read())

        file_size = os.path.getsize(local_path)
        print(f"[FILE] Chat 첨부 파일 다운로드: {file_name} ({file_size} bytes)")
        return local_path

    except Exception as e:
        print(f"[ERROR] Chat 첨부 파일 다운로드 실패 ({attachment_name}): {e}")
        return None


def _download_attachment(attachment, message_id):
    """
    첨부 파일 다운로드 (Drive 또는 Chat API)

    Args:
        attachment: Google Chat attachment 객체
        message_id: 메시지 ID

    Returns:
        dict: 파일 정보 {"type": ..., "path": ..., "size": ..., "name": ..., "mime_type": ...}
              실패 시 None
    """
    content_name = attachment.get("contentName", "attachment")
    content_type = attachment.get("contentType", "application/octet-stream")
    source = attachment.get("source", "")
    attachment_name = attachment.get("name", "")

    # 저장 디렉토리
    save_dir = os.path.join(_BASE_DIR, "tasks", f"msg_{message_id}")

    # 파일 타입 결정
    if content_type.startswith("image/"):
        file_type = "photo"
    elif content_type.startswith("video/"):
        file_type = "video"
    elif content_type.startswith("audio/"):
        file_type = "audio"
    else:
        file_type = "document"

    local_path = None

    if source == "DRIVE_FILE":
        # Google Drive에서 다운로드
        drive_ref = attachment.get("driveDataRef", {})
        drive_file_id = drive_ref.get("driveFileId")
        if drive_file_id:
            local_path = _download_drive_file(drive_file_id, save_dir, content_name)
        else:
            print(f"[WARN] Drive 파일 ID 없음: {attachment_name}")
    else:
        # Chat API media endpoint로 다운로드
        if attachment_name:
            local_path = _download_chat_attachment(attachment_name, save_dir, content_name)
        else:
            print(f"[WARN] 첨부 파일 리소스 이름 없음")

    if local_path and os.path.exists(local_path):
        file_size = os.path.getsize(local_path)
        return {
            "type": file_type,
            "path": local_path,
            "name": content_name,
            "mime_type": content_type,
            "size": file_size
        }

    return None


def _process_event(event_data):
    """
    Google Chat Pub/Sub 이벤트를 처리하여 메시지 데이터 구성

    Args:
        event_data: 디코딩된 Pub/Sub 메시지 JSON

    Returns:
        dict: 메시지 데이터 (저장 형식) 또는 None (처리 불가 시)
    """
    event_type = event_data.get("type", "")

    # MESSAGE 이벤트만 처리
    if event_type != "MESSAGE":
        print(f"[INFO] 무시: 이벤트 타입 '{event_type}' (MESSAGE만 처리)")
        return None

    message = event_data.get("message", {})
    if not message:
        print("[WARN] 이벤트에 message 필드 없음")
        return None

    # 발신자 정보
    sender = message.get("sender", {})
    # top-level user 필드에서도 확인 (fallback)
    if not sender.get("email"):
        sender = event_data.get("user", {})

    sender_email = sender.get("email", "")
    sender_display_name = sender.get("displayName", "")
    sender_type = sender.get("type", "")

    # BOT 타입 메시지는 무시 (봇 자신의 메시지)
    if sender_type == "BOT":
        print(f"[INFO] 무시: BOT 메시지")
        return None

    # 허용된 사용자 확인 (도메인 + STACK API 동적 검증)
    if not _is_allowed_user(sender_email):
        print(f"[WARN] 차단: 허용되지 않은 사용자 {sender_email} ({sender_display_name})")
        return None

    # 메시지 ID 추출
    message_name = message.get("name", "")
    message_id = _extract_message_id(message_name)
    if not message_id:
        print(f"[WARN] 메시지 ID 추출 실패: {message_name}")
        return None

    # space name 추출
    space_name = _extract_space_name(event_data)

    # 텍스트 추출
    text = message.get("text", "") or ""
    # 봇 멘션 텍스트 정리 (argumentText가 있으면 사용 - 멘션 부분 제외된 텍스트)
    argument_text = message.get("argumentText", "")
    if argument_text:
        text = argument_text.strip()

    # 타임스탬프
    create_time = message.get("createTime", event_data.get("eventTime", ""))
    timestamp = _parse_timestamp(create_time)

    # 첨부 파일 처리
    files = []
    attachments = message.get("attachment", [])
    if attachments:
        for attachment in attachments:
            file_info = _download_attachment(attachment, message_id)
            if file_info:
                files.append(file_info)

    # 텍스트와 파일 둘 다 없으면 무시
    if not text and not files:
        print(f"[INFO] 무시: 텍스트/파일 없는 메시지 (message_id={message_id})")
        return None

    # 사용자명 추출 (이메일의 @ 앞부분)
    username = sender_email.split("@")[0] if sender_email else ""

    # 메시지 데이터 구성
    message_data = {
        "message_id": message_id,
        "type": "user",
        "user_id": sender_email,
        "username": username,
        "first_name": sender_display_name,
        "last_name": "",
        "chat_id": space_name,
        "text": text,
        "files": files,
        "location": None,  # Google Chat은 위치 정보 미지원
        "timestamp": timestamp,
        "processed": False
    }

    # 사용자-Space 매핑 자동 등록 (Proactive Agent용)
    try:
        from proactive_tracker import register_user_space
        register_user_space(sender_email, sender_display_name, space_name)
    except Exception:
        pass

    return message_data


def fetch_new_messages():
    """
    Pub/Sub에서 새로운 메시지 가져오기 (동기 pull)

    100% crash-proof: 어떤 에러가 발생하더라도 절대 예외를 던지지 않으며,
    항상 list를 반환한다 (새 메시지 dict 리스트, 또는 빈 리스트 []).

    Returns:
        list: 새로 수집된 메시지 dict 리스트 (오류 시 빈 리스트 [])
    """
    # ──────────────────────────────────────────────────────────
    # 최외곽 try/except: 어떤 상황에서도 [] 반환 보장
    # ──────────────────────────────────────────────────────────
    try:
        return _fetch_new_messages_impl()
    except BaseException as e:
        # BaseException: KeyboardInterrupt, SystemExit 포함 모든 예외 캐치
        # (단, 이 함수를 호출하는 daemon이 죽는 것을 방지하기 위함)
        try:
            log(f"[FATAL] fetch_new_messages 최외곽 예외: {type(e).__name__}: {e}")
            log(f"[FATAL] traceback: {traceback.format_exc()}")
        except Exception:
            pass
        return []


def _fetch_new_messages_impl():
    """
    fetch_new_messages()의 실제 구현.
    google-cloud-pubsub 라이브러리 대신 순수 HTTP requests 사용.
    gRPC/REST transport 모두 hidden window에서 hang → 직접 HTTP 호출.

    Returns:
        list: 새 메시지 dict 리스트
    """
    import requests as _req

    # ─── 1. 설정 확인 ───
    if not GCP_PROJECT_ID:
        log("[ERROR] GCP_PROJECT_ID 미설정.")
        return []
    if not PUBSUB_SUBSCRIPTION_ID:
        log("[ERROR] PUBSUB_SUBSCRIPTION_ID 미설정.")
        return []
    cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    if not cred_path or not os.path.exists(cred_path):
        log(f"[ERROR] 서비스 계정 키 파일 없음: '{cred_path}'")
        return []

    subscription_path = f"projects/{GCP_PROJECT_ID}/subscriptions/{PUBSUB_SUBSCRIPTION_ID}"

    # ─── 2. OAuth2 토큰 획득 (서비스 계정) ───
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request as AuthRequest
        credentials = service_account.Credentials.from_service_account_file(
            cred_path,
            scopes=["https://www.googleapis.com/auth/pubsub"]
        )
        credentials.refresh(AuthRequest())
        token = credentials.token
        log(f"[OK] Pub/Sub 인증 성공 (HTTP direct)")
    except Exception as e:
        log(f"[ERROR] 인증 실패: {type(e).__name__}: {e}")
        return []

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # ─── 3. 기존 메시지 로드 ───
    try:
        data = load_messages()
    except Exception as e:
        log(f"[ERROR] load_messages() 실패: {e}")
        data = {"messages": [], "last_update_id": 0}

    # ─── 4. HTTP Pull (즉시 응답 + timeout 15초) ───
    pull_url = f"https://pubsub.googleapis.com/v1/{subscription_path}:pull"
    pull_body = {"maxMessages": 100, "returnImmediately": True}

    try:
        resp = _req.post(pull_url, json=pull_body, headers=headers, timeout=15)
    except _req.exceptions.Timeout:
        # 타임아웃 = 메시지 없음 (정상)
        return []
    except Exception as e:
        log(f"[ERROR] Pub/Sub HTTP pull 실패: {type(e).__name__}: {e}")
        return []

    if resp.status_code != 200:
        log(f"[ERROR] Pub/Sub pull HTTP {resp.status_code}: {resp.text[:300]}")
        return []

    pull_data = resp.json()
    received_messages = pull_data.get("receivedMessages", [])
    if not received_messages:
        return []

    log(f"[OK] Pub/Sub pull: {len(received_messages)}개 메시지 수신")

    # ─── 5. 메시지 파싱 및 저장 ───
    new_messages = []
    ack_ids = []

    for rm in received_messages:
        try:
            ack_ids.append(rm["ackId"])
        except Exception as e:
            log(f"[WARN] ackId 추출 실패: {e}")
            continue

        try:
            raw_b64 = rm.get("message", {}).get("data", "")
            raw_data = base64.b64decode(raw_b64)
            event_json = json.loads(raw_data.decode("utf-8"))
        except Exception as e:
            log(f"[WARN] 메시지 디코딩 오류: {e}")
            continue

        try:
            message_data = _process_event(event_json)
        except Exception as e:
            log(f"[WARN] _process_event 예외: {e}")
            continue

        if message_data is None:
            continue

        try:
            if _is_duplicate(data, message_data["message_id"]):
                continue
        except Exception:
            pass

        new_messages.append(message_data)
        data["messages"].append(message_data)

    # ─── 6. ACK (HTTP) ───
    if ack_ids:
        ack_url = f"https://pubsub.googleapis.com/v1/{subscription_path}:acknowledge"
        try:
            _req.post(ack_url, json={"ackIds": ack_ids}, headers=headers, timeout=10)
        except Exception as e:
            log(f"[WARN] ACK 실패: {e}")

    # ─── 7. 저장 ───
    if new_messages:
        try:
            save_messages(data)
        except Exception as e:
            log(f"[ERROR] save_messages 실패: {e}")

        for msg in new_messages:
            try:
                text_preview = msg["text"][:50] if msg["text"] else "(파일만)"
                file_info = f" + {len(msg['files'])}개 파일" if msg.get("files") else ""
                log(f"[NEW] [{msg['timestamp']}] {msg['first_name']} ({msg['user_id']}): {text_preview}...{file_info}")
            except Exception:
                pass

    return new_messages


def listen_loop():
    """메시지 수신 루프 (standalone 실행용)"""
    print("=" * 60)
    print("Google Chat Pub/Sub 메시지 수집기 시작")
    print("=" * 60)

    # 설정 확인
    if not GCP_PROJECT_ID:
        print("\n[ERROR] GCP_PROJECT_ID가 .env에 설정되지 않았습니다.")
        print("  .env 파일에 GCP_PROJECT_ID=<your-project-id> 추가")
        return

    if not PUBSUB_SUBSCRIPTION_ID:
        print("\n[ERROR] PUBSUB_SUBSCRIPTION_ID가 .env에 설정되지 않았습니다.")
        print("  .env 파일에 PUBSUB_SUBSCRIPTION_ID=<subscription-id> 추가")
        return

    cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    if not cred_path or not os.path.exists(cred_path):
        print(f"\n[ERROR] 서비스 계정 키 파일을 찾을 수 없습니다: {cred_path}")
        print("  .env 파일에 GOOGLE_APPLICATION_CREDENTIALS=./service-account-key.json 추가")
        print("  해당 경로에 서비스 계정 키 파일이 있는지 확인")
        return

    print(f"프로젝트: {GCP_PROJECT_ID}")
    print(f"구독: {PUBSUB_SUBSCRIPTION_ID}")
    print(f"폴링 간격: {POLLING_INTERVAL}초")
    print(f"허용 도메인: {GCHAT_ALLOWED_DOMAIN or '(제한 없음)'}")
    print(f"STACK API 검증: {'활성' if STACK_API_URL and STACK_API_KEY else '비활성'}")
    print(f"메시지 저장 파일: {MESSAGES_FILE}")
    print(f"서비스 계정 키: {cred_path}")
    print("\n대기 중... (Ctrl+C로 종료)\n")

    cycle_count = 0

    try:
        while True:
            cycle_count += 1
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            result = fetch_new_messages()  # 항상 list 반환 (crash-proof)

            if len(result) > 0:
                print(f"[{now}] #{cycle_count} - {len(result)}개 메시지 수집 완료")
            else:
                print(f"[{now}] #{cycle_count} - 대기 중...")

            time.sleep(POLLING_INTERVAL)

    except KeyboardInterrupt:
        print("\n\n종료 신호 감지. 프로그램을 종료합니다.")
        print("=" * 60)


if __name__ == "__main__":
    listen_loop()
