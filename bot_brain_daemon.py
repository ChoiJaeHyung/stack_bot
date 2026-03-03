#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
비서최재형 데몬 래퍼

bot_brain.py --daemon을 자동 재시작으로 감싸는 래퍼.
크래시 발생 시 30초 대기 후 자동 재시작.
pythonw로 실행하면 콘솔 창 없이 백그라운드 동작.
"""

import os
import sys
import time
import subprocess
import signal

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

LOG_FILE = os.path.join(BASE_DIR, "bot_brain.log")
PID_FILE = os.path.join(BASE_DIR, "daemon.pid")

# 데몬 PID 기록
RESTART_DELAY = 30  # 크래시 후 재시작 대기(초)
MAX_RAPID_RESTARTS = 5  # 연속 빠른 재시작 허용 횟수
RAPID_RESTART_WINDOW = 60  # 이 시간(초) 내 재시작이면 "빠른 재시작"


def log(msg):
    """bot_brain.log에 기록"""
    try:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [daemon] {msg}\n")
    except Exception:
        pass


def write_pid():
    """데몬 PID 기록"""
    try:
        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass


def remove_pid():
    """PID 파일 삭제"""
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except Exception:
        pass


def main():
    write_pid()
    log(f"데몬 시작 (PID={os.getpid()})")

    restart_times = []
    restart_count = 0

    try:
        while True:
            start_time = time.time()
            restart_count += 1
            log(f"bot_brain.py --daemon 시작 (#{restart_count})")

            try:
                # bot_brain.py --daemon 실행
                proc = subprocess.Popen(
                    [sys.executable, os.path.join(BASE_DIR, "bot_brain.py"), "--daemon"],
                    cwd=BASE_DIR,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

                # 프로세스 종료 대기
                exit_code = proc.wait()
                elapsed = time.time() - start_time
                log(f"bot_brain.py 종료 (code={exit_code}, 실행시간={int(elapsed)}초)")

            except Exception as e:
                elapsed = time.time() - start_time
                log(f"bot_brain.py 실행 오류: {e}")

            # 빠른 재시작 감지
            now = time.time()
            restart_times.append(now)
            # 오래된 기록 제거
            restart_times = [t for t in restart_times if now - t < RAPID_RESTART_WINDOW]

            if len(restart_times) >= MAX_RAPID_RESTARTS:
                cooldown = RESTART_DELAY * 3  # 90초 대기
                log(f"빠른 재시작 {len(restart_times)}회 감지! {cooldown}초 대기...")
                time.sleep(cooldown)
                restart_times.clear()
            else:
                log(f"{RESTART_DELAY}초 후 재시작...")
                time.sleep(RESTART_DELAY)

    except KeyboardInterrupt:
        log("KeyboardInterrupt - 데몬 종료")
    except Exception as e:
        log(f"데몬 예외: {e}")
    finally:
        remove_pid()
        log("데몬 종료")


if __name__ == "__main__":
    main()
