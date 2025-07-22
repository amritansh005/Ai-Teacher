import json
import os
from datetime import datetime
from typing import List
from .config import Config

class ConversationLogger:
    def __init__(self):
        os.makedirs(Config.LOG_DIR, exist_ok=True)
    
    def log_conversation(self, session_id: str, messages: List[str]):
        """Save conversation to JSON file"""
        log_data = {
            "session_id": session_id,
            "timestamp": datetime.now().isoformat(),
            "messages": []
        }
        
        for msg in messages:
            if "::" in msg:
                role, content = msg.split("::", 1)
                log_data["messages"].append({
                    "role": role,
                    "content": content,
                    "timestamp": datetime.now().isoformat()
                })
        
        log_file = os.path.join(Config.LOG_DIR, f"{session_id}.json")
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(log_data, f, indent=2, ensure_ascii=False)
