def keyword_search(query: str, top_k: int = 5) -> list[dict]:
    """기존 키워드 기반 메모리 검색 (chat_bot.search_memory 래핑)"""
    from chat_bot import search_memory
    matches = search_memory(keyword=query)
    return matches[:top_k] if matches else []
