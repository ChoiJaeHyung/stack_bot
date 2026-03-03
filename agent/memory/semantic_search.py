import os, json
from typing import Optional

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHROMA_DB_PATH = os.path.join(_BASE_DIR, "chroma_db")
COLLECTION_NAME = "task_episodes"

_client = None
_collection = None

def _get_collection():
    """Lazy-init ChromaDB collection."""
    global _client, _collection
    if _collection is not None:
        return _collection
    try:
        import chromadb
        from chromadb.config import Settings
        _client = chromadb.PersistentClient(path=CHROMA_DB_PATH, settings=Settings(anonymized_telemetry=False))
        _collection = _client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )
        return _collection
    except Exception as e:
        from bot_brain import log
        log(f"[memory] ChromaDB init failed: {e}")
        return None

def _get_embedding(text: str) -> list[float]:
    """OpenAI text-embedding-3-small 호출."""
    from bot_brain import client as oai_client
    response = oai_client.embeddings.create(
        model="text-embedding-3-small",
        input=text[:8000]
    )
    return response.data[0].embedding

def search_similar(query: str, top_k: int = 5) -> list[dict]:
    """벡터 유사도 검색. 실패 시 키워드 폴백."""
    try:
        collection = _get_collection()
        if collection is None or collection.count() == 0:
            raise RuntimeError("ChromaDB empty or unavailable")
        embedding = _get_embedding(query)
        results = collection.query(query_embeddings=[embedding], n_results=top_k)
        matches = []
        if results and results.get("documents"):
            for i, doc in enumerate(results["documents"][0]):
                meta = results["metadatas"][0][i] if results.get("metadatas") else {}
                matches.append({
                    "instruction": meta.get("instruction", doc[:200]),
                    "message_id": meta.get("message_id", ""),
                    "tools_used": meta.get("tools_used", ""),
                    "score": results["distances"][0][i] if results.get("distances") else 0,
                })
        return matches
    except Exception as e:
        from bot_brain import log
        log(f"[memory] Semantic search failed, falling back to keyword: {e}")
        from agent.memory.keyword_fallback import keyword_search
        return keyword_search(query, top_k)

def add_document(doc_id: str, text: str, metadata: dict):
    """ChromaDB에 문서 추가."""
    try:
        collection = _get_collection()
        if collection is None:
            return
        embedding = _get_embedding(text)
        collection.upsert(ids=[doc_id], embeddings=[embedding], documents=[text], metadatas=[metadata])
    except Exception as e:
        from bot_brain import log
        log(f"[memory] Failed to add document: {e}")

def seed_from_index():
    """기존 tasks/index.json에서 초기 데이터 시딩."""
    try:
        index_path = os.path.join(_BASE_DIR, "tasks", "index.json")
        if not os.path.exists(index_path):
            return 0
        with open(index_path, "r", encoding="utf-8") as f:
            index = json.load(f)
        tasks = index.get("tasks", [])
        collection = _get_collection()
        if collection is None:
            return 0
        count = 0
        for task in tasks:
            msg_id = str(task.get("message_id", ""))
            instruction = task.get("instruction", "")
            if not msg_id or not instruction or "(합산됨)" in instruction:
                continue
            doc_id = f"task_{msg_id}"
            text = f"{instruction}\n{task.get('result_summary', '')}"
            metadata = {
                "message_id": msg_id,
                "instruction": instruction[:500],
                "timestamp": task.get("timestamp", ""),
            }
            add_document(doc_id, text, metadata)
            count += 1
        from bot_brain import log
        log(f"[memory] Seeded {count} episodes from index.json")
        return count
    except Exception as e:
        from bot_brain import log
        log(f"[memory] Seeding failed: {e}")
        return 0
