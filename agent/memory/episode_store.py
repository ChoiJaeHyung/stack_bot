import os, json, time
from datetime import datetime, timedelta

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EPISODES_FILE = os.path.join(_BASE_DIR, "agent_episodes.json")
MAX_EPISODES = 500
CLEANUP_DAYS = 90

def save_episode(episode: dict):
    """에피소드 저장 (JSON 파일 + ChromaDB)."""
    try:
        episode["saved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        episodes = _load_episodes()
        episodes.append(episode)
        # 오래된 에피소드 정리
        if len(episodes) > MAX_EPISODES:
            cutoff = (datetime.now() - timedelta(days=CLEANUP_DAYS)).strftime("%Y-%m-%d")
            episodes = [e for e in episodes if e.get("saved_at", "") >= cutoff]
            episodes = episodes[-MAX_EPISODES:]  # still cap
        _save_episodes(episodes)
        # ChromaDB에도 저장
        try:
            from agent.memory.semantic_search import add_document
            doc_id = f"episode_{episode.get('message_id', int(time.time()))}"
            text = f"{episode.get('instruction', '')}\nTools: {episode.get('tools_used', [])}\nResult: {episode.get('result_summary', '')}"
            metadata = {
                "message_id": str(episode.get("message_id", "")),
                "instruction": str(episode.get("instruction", ""))[:500],
                "tools_used": json.dumps(episode.get("tools_used", []), ensure_ascii=False),
                "complexity": episode.get("complexity", ""),
                "fast_path_hit": str(episode.get("fast_path_hit", False)),
                "success": str(episode.get("success", True)),
            }
            add_document(doc_id, text, metadata)
        except Exception:
            pass
    except Exception as e:
        try:
            from bot_brain import log
            log(f"[episode] Save failed: {e}")
        except Exception:
            pass

def load_recent_episodes(n: int = 10) -> list[dict]:
    """최근 N개 에피소드 로드."""
    episodes = _load_episodes()
    return episodes[-n:] if episodes else []

def _load_episodes() -> list[dict]:
    if not os.path.exists(EPISODES_FILE):
        return []
    try:
        with open(EPISODES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def _save_episodes(episodes: list[dict]):
    with open(EPISODES_FILE, "w", encoding="utf-8") as f:
        json.dump(episodes, f, ensure_ascii=False, indent=2)
