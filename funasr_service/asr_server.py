from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
import numpy as np
import sounddevice as sd
import queue, threading, asyncio
from funasr import AutoModel
from pathlib import Path
import time

# Silero VAD imports
import torch
import torchaudio

# Load Silero VAD model
silero_vad_model, silero_utils = torch.hub.load(repo_or_dir='snakers4/silero-vad', model='silero_vad', force_reload=False)
(get_speech_timestamps, _, read_audio, _, _) = silero_utils

app = FastAPI()

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Or ["http://localhost:8080"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Load FunASR without VAD - let Silero handle VAD entirely
model = AutoModel(
    model="damo/speech_UniASR_asr_2pass-en-16k-common-vocab1080-tensorflow1-online",
    model_revision="v2.0.4",
    # Removed vad_model parameter - using only Silero VAD
    disable_update=True
)

def detect_speech_in_chunk(audio_data):
    """
    Use Silero VAD to detect speech in a chunk
    """
    try:
        # Ensure we have exactly 512 samples for 16kHz
        if len(audio_data) != 512:
            return False
            
        audio_tensor = torch.from_numpy(audio_data).unsqueeze(0)
        
        # Get speech probability for the chunk
        speech_probs = silero_vad_model(audio_tensor, 16000)
        
        # Return whether speech is detected (probability > threshold)
        return speech_probs.item() > 0.5
    except Exception as e:
        print(f"❌ Silero VAD error: {e}")
        return False

@app.get("/")
async def get():
    index_path = Path(__file__).parent.parent / "Frontend/index.html"
    return HTMLResponse(index_path.read_text(encoding="utf-8"))

@app.get("/health")
async def health_check():
    return {"asr": "healthy", "vad": "silero"}

@app.websocket("/ws/{session_id}")
async def ws_endpoint(ws: WebSocket, session_id: str):
    # Authenticate WebSocket connection
    token = ws.query_params.get("token")
    if token != "my_secure_token":
        await ws.close(code=403)
        print("❌ WebSocket connection rejected: Invalid token")
        return

    await ws.accept()
    print(f"🔌 WebSocket connected for session: {session_id}")

    cache = {}

    # Buffer for accumulating audio
    audio_buffer = []
    speech_buffer = []  # Buffer specifically for speech segments
    
    # State tracking
    is_speaking = False
    silence_duration = 0
    speech_start_time = None
    
    # Configuration
    CHUNK_SIZE = 512  # Exactly 512 samples for 16kHz as required by Silero
    SILENCE_THRESHOLD = 2.0  # 1 second of silence to end speech
    MIN_SPEECH_DURATION = 0.0  # Allow any speech duration, even single words
    VAD_THRESHOLD = 0.5  # Speech probability threshold
    
    print("🎤 Waiting for audio from frontend...")

    try:
        while True:
            # Receive audio from frontend as binary PCM (16-bit little endian)
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                print("🔌 WebSocket disconnected by client")
                break
            if msg["type"] == "websocket.receive":
                if "bytes" in msg:
                    # Convert bytes to float32 PCM
                    pcm_bytes = msg["bytes"]
                    int16_audio = np.frombuffer(pcm_bytes, dtype=np.int16)
                    float_audio = int16_audio.astype(np.float32) / 32768.0
                    
                    # Add to rolling buffer
                    audio_buffer.extend(float_audio)
                    
                    # Process in chunks
                    while len(audio_buffer) >= CHUNK_SIZE:
                        # Extract chunk
                        chunk = np.array(audio_buffer[:CHUNK_SIZE], dtype=np.float32)
                        audio_buffer = audio_buffer[CHUNK_SIZE:]
                        
                        # Check for speech in this chunk
                        has_speech = detect_speech_in_chunk(chunk)
                        
                        if has_speech:
                            # Add to speech buffer
                            speech_buffer.extend(chunk)
                            
                            if not is_speaking:
                                is_speaking = True
                                speech_start_time = time.time()
                                silence_duration = 0
                                print(f"🗣️ Speech started! (prob > {VAD_THRESHOLD})")
                                try:
                                    await ws.send_json({"type": "status", "message": "Speech detected"})
                                except:
                                    break
                        else:
                            # No speech in this chunk
                            if is_speaking:
                                # Add to speech buffer (include some silence)
                                speech_buffer.extend(chunk)
                                silence_duration += len(chunk) / 16000.0  # Convert to seconds
                                
                                # Check if we've had enough silence to end speech
                                if silence_duration >= SILENCE_THRESHOLD:
                                    speech_duration = time.time() - speech_start_time
                                    
                                    # Only process if speech was long enough
                                    if speech_duration >= MIN_SPEECH_DURATION:
                                        print(f"🛑 Speech ended after {speech_duration:.2f}s, processing...")
                                        
                                        # Process the accumulated speech
                                        try:
                                            speech_array = np.array(speech_buffer, dtype=np.float32)
                                            print(f"[DEBUG] Processing {len(speech_array)/16000:.2f}s of audio")
                                            
                                            result = model.generate(
                                                input=speech_array,
                                                cache=cache,
                                                is_final=True,
                                                encoder_chunk_look_back=4,
                                                decoder_chunk_look_back=1,
                                                segmentation="intelligent"  # Enable intelligent segmentation
                                            )
                                            
                                            print(f"[DEBUG] ASR result: {result}")
                                            
                                            if result and isinstance(result, list) and len(result) > 0:
                                                res = result[0]
                                                text = res.get('text', '').strip()
                                                if text:
                                                    print(f"🎯 Transcription: '{text}'")
                                                    await ws.send_json({
                                                        "type": "transcription",
                                                        "text": text,
                                                        "confidence": 1.0,
                                                        "final": True
                                                    })
                                                    # Forward transcript to chatbot_service for inference
                                                    try:
                                                        import requests
                                                        chatbot_url = "http://localhost:8001/chat"
                                                        payload = {
                                                            "session_id": session_id,
                                                            "message": text
                                                        }
                                                        resp = requests.post(chatbot_url, json=payload, timeout=50)
                                                        if resp.status_code == 200:
                                                            ai_data = resp.json()
                                                            await ws.send_json({
                                                                "type": "ai_response",
                                                                "text": ai_data.get("ai_response", ""),
                                                                "emotion": ai_data.get("emotion", "default"),
                                                                "session_id": session_id
                                                            })
                                                        else:
                                                            await ws.send_json({
                                                                "type": "error",
                                                                "message": f"Chatbot service error: {resp.text}",
                                                                "session_id": session_id
                                                            })
                                                    except Exception as e:
                                                        await ws.send_json({
                                                            "type": "error",
                                                            "message": f"Failed to contact chatbot service: {str(e)}",
                                                            "session_id": session_id
                                                        })
                                                else:
                                                    print("[DEBUG] Empty transcription")
                                            
                                            # Clear cache for next utterance
                                            cache = {}
                                            
                                        except Exception as e:
                                            print(f"❌ ASR error: {e}")
                                            await ws.send_json({
                                                "type": "error",
                                                "message": f"ASR error: {str(e)}"
                                            })
                                    else:
                                        print(f"[DEBUG] Speech too short: {speech_duration:.2f}s")
                                    
                                    # Reset state
                                    is_speaking = False
                                    speech_buffer = []
                                    silence_duration = 0
                
                elif "text" in msg:
                    # Handle text messages if needed
                    pass

            await asyncio.sleep(0.001)  # Small delay to prevent CPU spinning

    except Exception as e:
        print(f"❌ WebSocket error: {e}")
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except:
            pass
    finally:
        try:
            await ws.close()
        except:
            pass
        print(f"🔌 WebSocket closed for session: {session_id}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
