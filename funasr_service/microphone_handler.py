import sounddevice as sd
import numpy as np
from typing import Optional
import threading
import queue
import time

class MicrophoneHandler:
    def __init__(self, sample_rate: int = 16000, channels: int = 1):
        self.sample_rate = sample_rate
        self.channels = channels
        self.is_recording = False
        self.audio_queue = queue.Queue()
        
    def start_continuous_recording(self):
        """Start continuous microphone recording"""
        def audio_callback(indata, frames, time, status):
            if status:
                print(f"Audio callback status: {status}")
            if self.is_recording:
                self.audio_queue.put(indata.copy())
        
        self.is_recording = True
        self.stream = sd.InputStream(
            callback=audio_callback,
            channels=self.channels,
            samplerate=self.sample_rate,
            blocksize=1024
        )
        self.stream.start()
    
    def stop_recording(self):
        """Stop continuous recording"""
        self.is_recording = False
        if hasattr(self, 'stream'):
            self.stream.stop()
            self.stream.close()
    
    def get_audio_chunk(self, duration: float = 3.0) -> Optional[np.ndarray]:
        """Get audio chunk of specified duration"""
        if not self.is_recording:
            return None
            
        audio_data = []
        samples_needed = int(duration * self.sample_rate)
        samples_collected = 0
        
        start_time = time.time()
        timeout = duration + 2.0  # 2 second timeout buffer
        
        while samples_collected < samples_needed and (time.time() - start_time) < timeout:
            try:
                chunk = self.audio_queue.get(timeout=0.1)
                audio_data.append(chunk)
                samples_collected += len(chunk)
            except queue.Empty:
                continue
        
        if audio_data:
            return np.concatenate(audio_data, axis=0)[:samples_needed]
        return None
