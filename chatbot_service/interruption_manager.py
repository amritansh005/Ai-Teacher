import asyncio
from typing import Optional, Dict, Any
import requests
from shared.config import Config
from shared.redis_manager import RedisManager

class InterruptionManager:
    def __init__(self):
        self.redis_manager = RedisManager()
        self.active_sessions: Dict[str, Dict[str, Any]] = {}
    
    async def handle_interruption(self, session_id: str, interruption_text: str) -> Dict[str, Any]:
        """Handle user interruption during TTS playback"""
        try:
            # Stop current TTS
            stop_response = requests.post(f"{Config.OPENVOICE_SERVICE_URL}/stop/{session_id}")
            
            # Get the interrupted state
            tts_status = requests.get(f"{Config.OPENVOICE_SERVICE_URL}/status/{session_id}")
            interrupted_text = ""
            
            if tts_status.status_code == 200:
                status_data = tts_status.json()
                interrupted_text = status_data.get("current_text", "")
            
            # Store interruption context
            self.active_sessions[session_id] = {
                "interrupted_text": interrupted_text,
                "interruption_reason": interruption_text,
                "timestamp": asyncio.get_event_loop().time()
            }
            
            # Add interruption to conversation history
            self.redis_manager.add_message(session_id, "user", f"[INTERRUPTION]: {interruption_text}")
            
            return {
                "success": True,
                "interrupted_text": interrupted_text,
                "message": "Interruption handled successfully"
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to handle interruption: {str(e)}"
            }
    
    async def check_continuation_needed(self, session_id: str, ai_response: str) -> Dict[str, Any]:
        """Check if we need to continue from interrupted content"""
        if session_id not in self.active_sessions:
            return {"continue": False}
        
        interruption_data = self.active_sessions[session_id]
        interrupted_text = interruption_data.get("interrupted_text", "")
        
        # Simple check: if AI response addresses the interruption and it was substantial
        if len(interrupted_text) > 50:  # If there was substantial interrupted content
            continuation_prompt = f"After addressing the question, should I continue explaining: '{interrupted_text}'?"
            return {
                "continue": True,
                "continuation_text": interrupted_text,
                "continuation_prompt": continuation_prompt
            }
        
        # Clear the session after handling
        del self.active_sessions[session_id]
        return {"continue": False}
    
    def clear_session(self, session_id: str):
        """Clear interruption data for a session"""
        if session_id in self.active_sessions:
            del self.active_sessions[session_id]
