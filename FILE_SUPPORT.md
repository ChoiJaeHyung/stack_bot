# 이미지/파일 지원 가이드

**구현 완료일**: 2026-02-07
**상태**: ✅ 완전 구현

---

## 📌 개요

텔레그램 봇이 이제 **이미지, 문서, 비디오, 오디오 파일**을 받아서 Claude Code에게 전달할 수 있습니다!

---

## 🎯 지원하는 파일 타입

| 타입 | 이모지 | 설명 | Claude Code 읽기 방법 |
|------|--------|------|---------------------|
| **사진** (photo) | 🖼️ | JPG, PNG 등 | `Read(file_path='...')` |
| **문서** (document) | 📄 | PDF, DOCX, TXT, 등 | `Read(file_path='...')` 또는 전용 스킬 |
| **비디오** (video) | 🎥 | MP4, MOV 등 | 파일 경로 전달 |
| **오디오** (audio) | 🎵 | MP3, WAV 등 | 파일 경로 전달 |
| **음성** (voice) | 🎤 | 텔레그램 음성 메시지 | 파일 경로 전달 |
| **🆕 위치** (location) | 📍 | GPS 좌표 (위도/경도) | 위도/경도 값으로 API 호출 |

---

## 🔧 작동 방식

### 1단계: 텔레그램에서 파일 전송
```
사용자 → 텔레그램 앱
      → @mysonol_bot
      → [이미지 첨부] + "이 로고로 명함 만들어줘"
```

### 2단계: 파일 자동 다운로드
```
telegram_listener.py
  ↓ 메시지 감지
  ↓ 파일 다운로드
  ↓ tasks/msg_{message_id}/ 폴더에 저장
  ↓ telegram_messages.json에 파일 정보 기록
```

**저장 위치**: `tasks/msg_{message_id}/`
- 예: `tasks/msg_123/image_123.jpg`
- 예: `tasks/msg_124/design_brief.pdf`

### 3단계: Claude Code에게 전달
```
telegram_bot.py
  ↓ check_telegram() - 메시지 + 파일 정보 반환
  ↓ combine_tasks() - 여러 메시지 합산 (파일 포함)
  ↓ Claude Code - 파일 경로를 지시사항에 포함하여 전달
```

**전달 형식**:
```
[요청 1] (2026-02-07 10:00:00)
이 로고로 명함 디자인해줘

📎 첨부 파일:
  🖼️ logo.png (125.3 KB)
     경로: E:\CLAUDE_PROJECT\mybot_ver2\tasks\msg_123\logo.png
```

### 4단계: Claude Code 파일 읽기
```python
# 이미지 읽기 (Claude는 multimodal!)
Read(file_path=r'E:\CLAUDE_PROJECT\mybot_ver2\tasks\msg_123\logo.png')

# PDF 읽기
Read(file_path=r'E:\CLAUDE_PROJECT\mybot_ver2\tasks\msg_124\document.pdf', pages='1-5')

# DOCX 읽기 (스킬 사용)
Skill(skill='docx')
```

---

## 📝 사용 예시

### 예시 1: 이미지 기반 작업

**사용자**:
```
[이미지 첨부: cafe_logo.png]
이 로고로 카페 홈페이지 배너 만들어줘
```

**Claude Code 실행**:
```python
# 1. 이미지 읽기
logo_path = "E:\\CLAUDE_PROJECT\\mybot_ver2\\tasks\\msg_100\\image_100.jpg"
# Claude Code는 Read 도구로 이미지를 보고 이해함

# 2. 배너 생성 (HTML + CSS)
banner_html = f"""
<div class="banner">
  <img src="logo.png" alt="Cafe Logo">
  <h1>Welcome to Our Cafe</h1>
</div>
"""

# 3. 결과 저장
with open("banner.html", "w") as f:
    f.write(banner_html)
```

**결과**:
- ✅ 배너 HTML 생성
- ✅ 로고 이미지 활용
- ✅ 텔레그램으로 결과 전송

---

### 예시 2: 문서 변환 작업

**사용자**:
```
[문서 첨부: resume.docx]
이거 PDF로 변환해줘
```

**Claude Code 실행**:
```python
# 1. DOCX 읽기 (docx 스킬 사용)
from docx import Document
doc = Document("E:\\CLAUDE_PROJECT\\mybot_ver2\\tasks\\msg_200\\resume.docx")

# 2. PDF 생성 (pdf 스킬 사용)
# ... PDF 변환 로직 ...

# 3. 결과 저장
# resume.pdf 생성
```

**결과**:
- ✅ DOCX → PDF 변환
- ✅ 텔레그램으로 PDF 전송

---

### 예시 3: 여러 파일 동시 처리

**사용자**:
```
메시지 1 (10:00):
[이미지 첨부: photo1.jpg]
이 사진 배경 제거해줘

메시지 2 (10:01):
[이미지 첨부: photo2.jpg]
이것도

메시지 3 (10:02):
정사각형으로 해줘
```

**Claude Code 실행**:
```
✅ 작업을 시작했습니다! (총 3개 요청 합산 처리)

통합 지시사항:
[요청 1] (10:00)
이 사진 배경 제거해줘
📎 첨부 파일:
  🖼️ image_101.jpg (1.2 MB)

[요청 2] (10:01)
이것도
📎 첨부 파일:
  🖼️ image_102.jpg (950.3 KB)

[요청 3] (10:02)
정사각형으로 해줘
```

**결과**:
- ✅ 2개 이미지 배경 제거
- ✅ 정사각형 크롭
- ✅ 텔레그램으로 2개 결과 전송

---

## 🔍 파일 정보 구조

### telegram_messages.json
```json
{
  "messages": [
    {
      "message_id": 123,
      "text": "이 로고로 명함 만들어줘",
      "files": [
        {
          "type": "photo",
          "path": "E:\\CLAUDE_PROJECT\\mybot_ver2\\tasks\\msg_123\\image_123.jpg",
          "size": 128345
        }
      ],
      "processed": false
    }
  ]
}
```

### check_telegram() 반환값
```python
[
  {
    "instruction": "이 로고로 명함 만들어줘",
    "message_id": 123,
    "files": [
      {
        "type": "photo",
        "path": "...",
        "size": 128345
      }
    ]
  }
]
```

### combine_tasks() 반환값
```python
{
  "combined_instruction": "[요청 1] ...\n📎 첨부 파일: ...",
  "message_ids": [123, 124],
  "files": [
    {"type": "photo", "path": "...", "size": 128345},
    {"type": "document", "path": "...", "size": 2145728}
  ]
}
```

---

## 🧪 테스트 방법

### 1. 리스너 실행
```bash
python telegram_listener.py
```

### 2. 텔레그램에서 파일 전송
```
@mysonol_bot에게 이미지/파일 첨부하여 메시지 보내기
```

### 3. 테스트 스크립트 실행
```bash
# 포맷 테스트 (가상 데이터)
python test_file_message_format.py

# 실제 메시지 테스트
python test_file_support.py
```

### 4. 자동 실행 확인
```bash
# Windows 작업 스케줄러 로그 확인
type claude_task.log
```

---

## 📊 파일 크기 제한

| 항목 | 제한 | 비고 |
|------|------|------|
| 텔레그램 파일 | 50 MB | 봇 API 제한 |
| 텔레그램 사진 | 10 MB | 압축됨 |
| Claude Code 읽기 | 제한 없음* | 메모리에 따라 다름 |

*단, 매우 큰 파일은 처리 시간이 오래 걸릴 수 있습니다.

---

## 🔧 주요 함수

### telegram_listener.py

```python
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
```

### telegram_bot.py

```python
def _format_file_size(size_bytes):
    """파일 크기를 사람이 읽기 쉬운 형식으로 변환"""

def combine_tasks(pending_tasks):
    """
    여러 메시지를 하나로 합산 (파일 포함)

    Returns:
        - combined_instruction: 통합 지시사항 (파일 정보 포함)
        - files: 모든 첨부 파일 정보
    """
```

---

## ✅ 체크리스트

- [x] telegram_listener.py - 파일 다운로드 기능
- [x] telegram_bot.py - 파일 정보 전달
- [x] CLAUDE.md - 문서 업데이트
- [x] 테스트 스크립트 작성
- [x] 여러 메시지 + 여러 파일 합산 처리
- [x] 파일 크기 포맷팅
- [x] 파일 타입별 이모지
- [x] Claude Code 읽기 가이드

---

## 🚀 다음 단계

1. ⬜ 음성 메시지 → 텍스트 변환 (STT)
2. ⬜ 비디오 썸네일 추출
3. ⬜ 이미지 리사이징 (자동)
4. ⬜ 파일 타입 검증 (악성 파일 차단)
5. ⬜ 파일 저장소 정리 (오래된 파일 삭제)

---

**문의**: CLAUDE.md 참조
**테스트 파일**:
- `test_file_message_format.py` (포맷 테스트)
- `test_file_support.py` (실제 메시지 테스트)
