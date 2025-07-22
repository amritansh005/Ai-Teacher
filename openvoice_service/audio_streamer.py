import sounddevice as sd
import numpy as np
import threading
import queue
from typing import Optional, Iterator
import time

class AudioStreamer:
    def __init__(self, sample_rate: int = 22050):
        self.sample_rate = sample_rate
        self.audio_queue = queue.Queue()
        self.is_playing = False
        self.current_session = None
        self._stop_event = threading.Event()
        
    def start_streaming(self, session_id: str):
        """Start audio streaming for a session"""
        self.current_session = session_id
        self.is_playing = True
        self._stop_event.clear()
        
        # Start playback thread
        playback_thread = threading.Thread(
            target=self._playback_worker,
            args=(session_id,),
            daemon=True
        )
        playback_thread.start()
        
    def add_audio_chunk(self, audio_chunk: np.ndarray):
        """Add audio chunk to playback queue"""
        if self.is_playing:
            self.audio_queue.put(audio_chunk)
    
    def stop_streaming(self):
        """Stop current audio streaming"""
        self.is_playing = False
        self._stop_event.set()
        # Clear remaining audio chunks
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break
    
    def is_currently_speaking(self) -> bool:
        """Check if currently playing audio"""
        return self.is_playing and not self.audio_queue.empty()
    
    def _playback_worker(self, session_id: str):
        """Worker thread for audio playback"""
        while self.is_playing and not self._stop_event.is_set():
            try:
                audio_chunk = self.audio_queue.get(timeout=0.1)
                if audio_chunk is not None:
                    # Play audio chunk
                    sd.play(audio_chunk, samplerate=self.sample_rate)
                    sd.wait()  # Wait for playback to complete
            except queue.Empty:
                continue
            except Exception as e:
                print(f"Playback error: {e}")
                break
        
        self.is_playing = False
