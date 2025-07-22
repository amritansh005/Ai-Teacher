#!/usr/bin/env python
import sys
import os

# Add the correct virtual environment to Python path
venv_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'venv-openvoice')
site_packages = os.path.join(venv_path, 'Lib', 'site-packages')
if os.path.exists(site_packages):
    sys.path.insert(0, site_packages)

# Add OpenVoice directory to path
openvoice_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'OpenVoice')
if os.path.exists(openvoice_path):
    sys.path.insert(0, openvoice_path)

# Verify correct environment
print(f"Using Python from: {sys.executable}")
print(f"Virtual env path: {venv_path}")

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Response
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import torch
import numpy as np
import re
import tempfile
import io
import wave
import soundfile as sf
from scipy.io.wavfile import write

# Import OpenVoice components
try:
    import se_extractor
    from api import BaseSpeakerTTS, ToneColorConverter
    print("OpenVoice modules imported successfully")
except ImportError as e:
    print(f"OpenVoice import error: {e}")
    print("Trying alternative import...")
    try:
        from openvoice import se_extractor
        from openvoice.api import BaseSpeakerTTS, ToneColorConverter
        print("Alternative import successful")
    except ImportError as e2:
        print(f"Alternative import also failed: {e2}")
        se_extractor = None
        BaseSpeakerTTS = None
        ToneColorConverter = None

app = FastAPI(title="OpenVoice TTS Service")

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize components
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Using device: {device}")

# Initialize OpenVoice TTS
ckpt_base = 'checkpoints/base_speakers/EN'
ckpt_converter = 'checkpoints/converter'
base_speaker_tts = None
tone_color_converter = None
source_se = None

# Create temp directory
os.makedirs("temp", exist_ok=True)
os.makedirs("processed", exist_ok=True)

def initialize_models():
    global base_speaker_tts, tone_color_converter, source_se
    
    if not BaseSpeakerTTS or not ToneColorConverter:
        print("OpenVoice classes not available")
        return False
    
    try:
        print(f"Loading base speaker model from {ckpt_base}")
        base_speaker_tts = BaseSpeakerTTS(f'{ckpt_base}/config.json', device=device)
        base_speaker_tts.load_ckpt(f'{ckpt_base}/checkpoint.pth')
        print("Base speaker model loaded successfully")
        
        print(f"Loading tone converter from {ckpt_converter}")
        tone_color_converter = ToneColorConverter(f'{ckpt_converter}/config.json', device=device)
        tone_color_converter.load_ckpt(f'{ckpt_converter}/checkpoint.pth')
        print("Tone converter loaded successfully")
        
        print("Loading source speaker embedding")
        source_se = torch.load(f'{ckpt_base}/en_default_se.pth', map_location=device)
        print("Source speaker embedding loaded successfully")
        
        return True
    except Exception as e:
        print(f"Failed to load OpenVoice models: {e}")
        import traceback
        traceback.print_exc()
        return False

# Initialize models on startup
models_loaded = initialize_models()

class TTSRequest(BaseModel):
    session_id: str
    text: str
    emotion: str = "default"
    stream: bool = True

def clean_text(text: str) -> str:
    """Remove markdown formatting and clean text for TTS"""
    # Remove asterisks and other markdown
    text = re.sub(r'\*+', '', text)
    text = re.sub(r'#+\s*', '', text)
    text = re.sub(r'``````', '', text)
    text = re.sub(r'`([^`]*)`', r'\1', text)
    # Clean up multiple spaces and newlines
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def get_emotion_settings(emotion: str) -> dict:
    """Map emotion to OpenVoice settings"""
    emotion_map = {
        "default": {"speed": 1.0},
        "cheerful": {"speed": 1.1},
        "excited": {"speed": 1.2},
        "sad": {"speed": 0.9},
        "angry": {"speed": 1.1},
        "friendly": {"speed": 1.0},
        "terrified": {"speed": 1.3},
        "whispering": {"speed": 0.8},
        "shouting": {"speed": 1.2}
    }
    return emotion_map.get(emotion.lower(), emotion_map["default"])

@app.post("/synthesize_stream")
async def synthesize_speech_stream(request: TTSRequest):
    """Synthesize speech and stream directly"""
    if not models_loaded or not base_speaker_tts:
        # Try to initialize again
        if not initialize_models():
            raise HTTPException(status_code=503, detail="TTS models not available")
    
    try:
        # Clean text
        clean_text_input = clean_text(request.text)
        if not clean_text_input.strip():
            raise HTTPException(status_code=400, detail="Empty text after cleaning")
        
        print(f"Generating TTS for: '{clean_text_input[:50]}...' with emotion: {request.emotion}")
        
        # Get emotion settings
        emotion_settings = get_emotion_settings(request.emotion)
        
        # Generate unique temp file names
        import uuid
        unique_id = str(uuid.uuid4())
        temp_path = f"temp/temp_{unique_id}.wav"
        
        try:
            # Generate base TTS
            print("Generating base TTS...")
            base_speaker_tts.tts(
                clean_text_input, 
                temp_path, 
                speaker='default', 
                language='English',
                speed=emotion_settings["speed"]
            )
            
            if not os.path.exists(temp_path):
                raise Exception("Base TTS failed to generate audio file")
            
            # For now, skip tone conversion to test basic TTS
            # Just read the generated audio and return it
            with open(temp_path, 'rb') as f:
                audio_data = f.read()
            
            # Clean up temp file
            if os.path.exists(temp_path):
                os.remove(temp_path)
            
            print("Audio generated successfully")
            
            # Return audio as streaming response
            return Response(
                content=audio_data,
                media_type="audio/wav",
                headers={
                    "Content-Disposition": f"inline; filename=tts_{request.session_id}.wav",
                    "Cache-Control": "no-cache",
                    "Access-Control-Allow-Origin": "*"
                }
            )
            
        except Exception as e:
            # Clean up temp files on error
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise e
            
    except Exception as e:
        import traceback
        print(f"TTS synthesis error: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"TTS synthesis failed: {str(e)}")

@app.post("/synthesize")
async def synthesize_speech(request: TTSRequest):
    """Synthesize speech and return JSON metadata with audio URL"""
    if not models_loaded or not base_speaker_tts:
        if not initialize_models():
            raise HTTPException(status_code=503, detail="TTS models not available")

    try:
        clean_text_input = clean_text(request.text)
        if not clean_text_input.strip():
            raise HTTPException(status_code=400, detail="Empty text after cleaning")

        emotion_settings = get_emotion_settings(request.emotion)
        import uuid
        unique_id = str(uuid.uuid4())
        audio_filename = f"tts_{request.session_id}_{unique_id}.wav"
        audio_path = os.path.join("processed", audio_filename)

        # Generate base TTS
        base_speaker_tts.tts(
            clean_text_input,
            audio_path,
            speaker='default',
            language='English',
            speed=emotion_settings["speed"]
        )

        if not os.path.exists(audio_path):
            raise HTTPException(status_code=500, detail="Base TTS failed to generate audio file")

        # Get audio duration
        try:
            f = sf.SoundFile(audio_path)
            audio_duration = len(f) / f.samplerate
            f.close()
        except Exception:
            audio_duration = 0.0

        audio_url = f"/audio/{audio_filename}"

        return {
            "success": True,
            "audio_url": audio_url,
            "audio_duration": audio_duration
        }
    except Exception as e:
        import traceback
        print(f"TTS synthesis error: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"TTS synthesis failed: {str(e)}")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "device": device,
        "models_loaded": models_loaded,
        "base_speaker_loaded": base_speaker_tts is not None,
        "tone_converter_loaded": tone_color_converter is not None
    }

@app.post("/stop/{session_id}")
async def stop_speech(session_id: str):
    """Stop current speech synthesis/playback"""
    return {"success": True, "message": "Speech stopped"}

@app.get("/status/{session_id}")
async def get_tts_status(session_id: str):
    """Get current TTS status"""
    return {
        "session_id": session_id,
        "is_speaking": False,
        "current_text": "",
        "tts_active": False
    }

# Mount static files if needed
AUDIO_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "processed"))
os.makedirs(AUDIO_DIR, exist_ok=True)
if os.path.exists(AUDIO_DIR):
    app.mount("/audio", StaticFiles(directory=AUDIO_DIR), name="audio")

if __name__ == "__main__":
    import uvicorn
    print("\nStarting OpenVoice TTS Server...")
    print(f"Models loaded: {models_loaded}")
    print(f"Device: {device}")
    print(f"Checkpoint base: {ckpt_base}")
    print(f"Checkpoint converter: {ckpt_converter}")
    uvicorn.run(app, host="0.0.0.0", port=8002)
