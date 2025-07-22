import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    GEMMA_MODEL = os.getenv("GEMMA_MODEL", "google/gemma-3n-e2b")
    FUNASR_SERVICE_URL = os.getenv("FUNASR_SERVICE_URL", "http://localhost:8001")
    OPENVOICE_SERVICE_URL = os.getenv("OPENVOICE_SERVICE_URL", "http://localhost:8002")
    CHATBOT_SERVICE_URL = os.getenv("CHATBOT_SERVICE_URL", "http://localhost:8000")
    LOG_DIR = os.getenv("LOG_DIR", "./logs")
    
    # Audio settings
    SAMPLE_RATE = 16000
    AUDIO_DURATION = 5
    
    # Model settings
    MAX_CONVERSATION_HISTORY = 10
    SENTIMENT_WINDOW_SIZE = 3
