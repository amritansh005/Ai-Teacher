import redis
import json
from typing import List, Optional
from .config import Config

class RedisManager:
    def __init__(self):
        self.redis_client = redis.Redis.from_url(Config.REDIS_URL, decode_responses=True)
    
    def add_message(self, session_id: str, role: str, message: str):
        """Add a message to conversation history"""
        key = f"chat:{session_id}"
        self.redis_client.rpush(key, f"{role}::{message}")
        
    def get_conversation(self, session_id: str) -> List[str]:
        """Get full conversation history"""
        key = f"chat:{session_id}"
        return self.redis_client.lrange(key, 0, -1)
    
    def get_recent_messages(self, session_id: str, count: int = 3) -> List[str]:
        """Get recent messages for sentiment analysis"""
        key = f"chat:{session_id}"
        return self.redis_client.lrange(key, -count, -1)
    
    def clear_conversation(self, session_id: str):
        """Clear conversation history"""
        key = f"chat:{session_id}"
        self.redis_client.delete(key)
    
    def set_current_tts_state(self, session_id: str, text: str, is_speaking: bool):
        """Track current TTS state for interruption handling"""
        key = f"tts_state:{session_id}"
        state = {"text": text, "is_speaking": is_speaking}
        self.redis_client.setex(key, 300, json.dumps(state))  # 5 min expiry
    
    def get_current_tts_state(self, session_id: str) -> Optional[dict]:
        """Get current TTS state"""
        key = f"tts_state:{session_id}"
        state_json = self.redis_client.get(key)
        return json.loads(state_json) if state_json else None
