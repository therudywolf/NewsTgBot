"""Deduplication service using LLM."""
from typing import List, Dict, Any
from llm_client import LLMClient


class Deduplicator:
    """Service for deduplicating news using LLM."""
    
    def __init__(self, llm_client: LLMClient = None):
        """Initialize deduplicator."""
        self.llm_client = llm_client or LLMClient()
    
    async def deduplicate(self, news_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Deduplicate news items using LLM."""
        if not news_items:
            return []
        
        # Filter out empty or very short news items
        valid_news = [item for item in news_items if item.get('text', '').strip() and len(item.get('text', '').strip()) > 10]
        
        if not valid_news:
            return []
        
        # If there's only one item, no need to deduplicate
        if len(valid_news) == 1:
            return valid_news
        
        # Use LLM to deduplicate
        unique_news = await self.llm_client.deduplicate_news(valid_news)
        
        return unique_news

