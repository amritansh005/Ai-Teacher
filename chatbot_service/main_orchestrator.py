import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel
import asyncio
import requests
import json
from typing import Dict, List, Optional
import uuid

from shared.config import Config
from shared.redis_manager import RedisManager
from shared.conversation_logger import ConversationLogger
from gemma_handler import GemmaHandler
from sentiment_analyzer import SentimentAnalyzer
from interruption_manager import InterruptionManager

app = FastAPI(title="AI Teacher Orchestrator")

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Or specify ["http://localhost:8080"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize components
redis_manager = RedisManager()
conversation_logger = ConversationLogger()
gemma_handler = GemmaHandler()
sentiment_analyzer = SentimentAnalyzer()
interruption_manager = InterruptionManager()

# Active WebSocket connections
active_connections: Dict[str, WebSocket] = {}

class ChatRequest(BaseModel):
    session_id: str
    message: str

class ChatResponse(BaseModel):
    session_id: str
    user_message: str
    ai_response: str
    emotion: str
    processing_time: float
    audio_url: Optional[str] = None
    audio_duration: float = 0.0
    tts_success: bool = False
    tts_error: Optional[str] = ""

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """Main WebSocket endpoint for real-time AI teacher interaction"""
    await websocket.accept()
    active_connections[session_id] = websocket
    
    try:
        await websocket.send_text(json.dumps({
            "type": "system",
            "message": f"Connected to AI Teacher. Session: {session_id}",
            "session_id": session_id
        }))
        
        while True:
            # Wait for user input or system events
            data = await websocket.receive_text()
            message_data = json.loads(data)
            
            if message_data.get("type") == "start_listening":
                await handle_voice_interaction(websocket, session_id)
            elif message_data.get("type") == "interrupt":
                await handle_interruption(websocket, session_id, message_data.get("text", ""))
            elif message_data.get("type") == "text_input":
                await handle_text_input(websocket, session_id, message_data.get("text", ""))
                
    except WebSocketDisconnect:
        if session_id in active_connections:
            del active_connections[session_id]
        interruption_manager.clear_session(session_id)
        print(f"Client {session_id} disconnected")

async def handle_voice_interaction(websocket: WebSocket, session_id: str):
    """Handle voice-based interaction cycle"""
    try:
        # Step 1: Get speech input via FunASR
        await websocket.send_text(json.dumps({
            "type": "status",
            "message": "Listening...",
            "session_id": session_id
        }))
        
        # Request transcription from FunASR service
        transcription_response = requests.post(
            f"{Config.FUNASR_SERVICE_URL}/transcribe",
            json={"duration": 5.0, "language": "auto"},
            timeout=10
        )
        
        if transcription_response.status_code != 200:
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": "Failed to transcribe audio",
                "session_id": session_id
            }))
            return
        
        transcription_data = transcription_response.json()
        user_text = transcription_data["text"].strip()
        
        if not user_text:
            await websocket.send_text(json.dumps({
                "type": "status",
                "message": "No speech detected. Please try again.",
                "session_id": session_id
            }))
            return
        
        await websocket.send_text(json.dumps({
            "type": "transcription",
            "text": user_text,
            "confidence": transcription_data.get("confidence", 0.0),
            "session_id": session_id
        }))
        
        # Process the user input
        await process_user_input(websocket, session_id, user_text)
        
    except Exception as e:
        await websocket.send_text(json.dumps({
            "type": "error",
            "message": f"Voice interaction failed: {str(e)}",
            "session_id": session_id
        }))

async def handle_text_input(websocket: WebSocket, session_id: str, text: str):
    """Handle text-based input"""
    await process_user_input(websocket, session_id, text)

async def handle_interruption(websocket: WebSocket, session_id: str, interruption_text: str):
    """Handle user interruption during AI speech"""
    result = await interruption_manager.handle_interruption(session_id, interruption_text)
    
    await websocket.send_text(json.dumps({
        "type": "interruption_handled",
        "success": result["success"],
        "message": result.get("message", ""),
        "session_id": session_id
    }))
    
    if result["success"] and interruption_text.strip():
        # Process the interruption as new input
        await process_user_input(websocket, session_id, interruption_text)

async def process_user_input(websocket: WebSocket, session_id: str, user_input: str):
    """Process user input through the AI teacher pipeline"""
    try:
        # Add user message to conversation history
        redis_manager.add_message(session_id, "user", user_input)
        
        # Get conversation history for context
        conversation_history = redis_manager.get_conversation(session_id)
        
        # Generate AI response using Gemma
        await websocket.send_text(json.dumps({
            "type": "status",
            "message": "Thinking...",
            "session_id": session_id
        }))
        
        ai_response = await asyncio.to_thread(gemma_handler.generate_response, conversation_history, user_input)
        
        # Clean response (remove asterisks and formatting)
        clean_response = ai_response.replace("*", "").strip()
        
        # Add AI response to conversation history
        redis_manager.add_message(session_id, "ai", clean_response)
        
        # Analyze sentiment for emotion
        recent_messages = redis_manager.get_recent_messages(session_id, 3)
        emotion = sentiment_analyzer.analyze_conversation(recent_messages)
        
        # Send AI response to user
        await websocket.send_text(json.dumps({
            "type": "ai_response",
            "text": clean_response,
            "emotion": emotion,
            "session_id": session_id
        }))
        
        # Send to TTS for speech synthesis
        await websocket.send_text(json.dumps({
            "type": "status",
            "message": "Speaking...",
            "session_id": session_id
        }))
        
        tts_response = requests.post(
            f"{Config.OPENVOICE_SERVICE_URL}/synthesize",
            json={
                "session_id": session_id,
                "text": clean_response,
                "emotion": emotion,
                "stream": True
            },
            timeout=30
        )
        
        if tts_response.status_code == 200:
            tts_data = tts_response.json()
            await websocket.send_text(json.dumps({
                "type": "tts_complete",
                "success": tts_data["success"],
                "duration": tts_data.get("audio_duration", 0.0),
                "audio_url": tts_data.get("audio_url"),
                "session_id": session_id
            }))
        else:
            await websocket.send_text(json.dumps({
                "type": "tts_error",
                "message": "Failed to synthesize speech",
                "session_id": session_id
            }))
        
        # Log conversation
        updated_history = redis_manager.get_conversation(session_id)
        conversation_logger.log_conversation(session_id, updated_history)
        
        # Check if we need to continue from interruption
        continuation = await interruption_manager.check_continuation_needed(session_id, clean_response)
        if continuation.get("continue", False):
            await websocket.send_text(json.dumps({
                "type": "continuation_available",
                "text": continuation.get("continuation_text", ""),
                "session_id": session_id
            }))
        
    except Exception as e:
        await websocket.send_text(json.dumps({
            "type": "error",
            "message": f"Failed to process input: {str(e)}",
            "session_id": session_id
        }))

from fastapi import Request as FastAPIRequest
from fastapi.responses import StreamingResponse

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest, fastapi_request: FastAPIRequest):
    """REST API endpoint for chat (alternative to WebSocket)"""
    try:
        # Add user message
        redis_manager.add_message(request.session_id, "user", request.message)
        
        # Get conversation history
        conversation_history = redis_manager.get_conversation(request.session_id)
        
        # Generate AI response
        ai_response = await asyncio.to_thread(gemma_handler.generate_response, conversation_history, request.message)
        clean_response = ai_response.replace("*", "").strip()
        
        # Add AI response
        redis_manager.add_message(request.session_id, "ai", clean_response)
        
        # Analyze sentiment
        recent_messages = redis_manager.get_recent_messages(request.session_id, 3)
        emotion = sentiment_analyzer.analyze_conversation(recent_messages)
        
        # Log conversation
        updated_history = redis_manager.get_conversation(request.session_id)
        conversation_logger.log_conversation(request.session_id, updated_history)

        # Check if audio streaming is requested
        stream_audio = fastapi_request.query_params.get("stream_audio", "false").lower() == "true"
        if stream_audio:
            # Stream audio directly from TTS service
            tts_response = requests.post(
                f"{Config.OPENVOICE_SERVICE_URL}/synthesize_stream",
                json={
                    "session_id": request.session_id,
                    "text": clean_response,
                    "emotion": emotion,
                    "stream": True
                },
                timeout=60,
                stream=True
            )
            if tts_response.status_code == 200:
                def iter_audio():
                    for chunk in tts_response.iter_content(chunk_size=4096):
                        if chunk:
                            yield chunk
                return StreamingResponse(iter_audio(), media_type="audio/wav")
            else:
                raise HTTPException(status_code=500, detail="Failed to stream TTS audio")
        else:
            # Default: return JSON metadata
            tts_response = requests.post(
                f"{Config.OPENVOICE_SERVICE_URL}/synthesize",
                json={
                    "session_id": request.session_id,
                    "text": clean_response,
                    "emotion": emotion,
                    "stream": True
                },
                timeout=30
            )
            
            tts_success = False
            tts_error = None
            audio_url = None
            audio_duration = 0.0
            
            if tts_response.status_code == 200:
                tts_data = tts_response.json()
                tts_success = tts_data.get("success", False)
                audio_url = tts_data.get("audio_url")
                if audio_url:
                    audio_url = f"{Config.OPENVOICE_SERVICE_URL}{audio_url}"
                audio_duration = tts_data.get("audio_duration", 0.0)
            else:
                tts_error = "Failed to synthesize speech"

            return ChatResponse(
                session_id=request.session_id,
                user_message=request.message,
                ai_response=clean_response,
                emotion=emotion,
                processing_time=0.0,
                audio_url=audio_url,
                audio_duration=audio_duration,
                tts_success=tts_success,
                tts_error=tts_error or ""
            )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Chat processing failed: {str(e)}")

@app.get("/health")
async def health_check():
    """Health check for all services"""
    health_status = {"orchestrator": "healthy"}
    
    # Check FunASR service
    try:
        funasr_response = requests.get(f"{Config.FUNASR_SERVICE_URL}/health", timeout=5)
        health_status["funasr"] = "healthy" if funasr_response.status_code == 200 else "unhealthy"
    except:
        health_status["funasr"] = "unreachable"
    
    # Check OpenVoice service
    try:
        openvoice_response = requests.get(f"{Config.OPENVOICE_SERVICE_URL}/health", timeout=5)
        health_status["openvoice"] = "healthy" if openvoice_response.status_code == 200 else "unhealthy"
    except:
        health_status["openvoice"] = "unreachable"
    
    return health_status

@app.get("/sessions/{session_id}/history")
async def get_conversation_history(session_id: str):
    """Get conversation history for a session"""
    history = redis_manager.get_conversation(session_id)
    return {"session_id": session_id, "history": history}

@app.delete("/sessions/{session_id}")
async def clear_session(session_id: str):
    """Clear a conversation session"""
    redis_manager.clear_conversation(session_id)
    interruption_manager.clear_session(session_id)
    return {"session_id": session_id, "message": "Session cleared"}

if __name__ == "__main__":
    import uvicorn
uvicorn.run(app, host="0.0.0.0", port=8001)
