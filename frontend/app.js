class AITeacher {
    constructor() {
        this.ws = null;
        this.sessionId = this.generateSessionId();
        this.isConnected = false;
        this.isListening = false;
        this.isSpeaking = false;
        this.useBrowserTTS = false; // Default to OpenVoice TTS
        this.ttsWebSocket = null;
        this.audioContext = null;
        this.audioQueue = [];
        this.isPlayingTTS = false;
        this.currentAudio = null;
        
        this.initializeElements();
        this.attachEventListeners();
        this.connect();
        this.startHealthCheck();
        this.initializeWebAudio();
        
        // Load browser TTS voices
        if ('speechSynthesis' in window) {
            window.speechSynthesis.onvoiceschanged = () => {
                console.log('Browser TTS voices loaded:', window.speechSynthesis.getVoices().length);
            };
        }
    }
    
    generateSessionId() {
        return 'session_' + Math.random().toString(36).substr(2, 9);
    }
    
    initializeElements() {
        this.elements = {
            sessionId: document.getElementById('session-id'),
            connectionStatus: document.getElementById('connection-status'),
            chatMessages: document.getElementById('chat-messages'),
            textInput: document.getElementById('text-input'),
            sendTextBtn: document.getElementById('send-text-btn'),
            voiceBtn: document.getElementById('voice-btn'),
            interruptBtn: document.getElementById('interrupt-btn'),
            stopBtn: document.getElementById('stop-btn'),
            currentState: document.getElementById('current-state'),
            currentEmotion: document.getElementById('current-emotion'),
            serviceStatus: document.getElementById('service-status'),
            clearSessionBtn: document.getElementById('clear-session-btn'),
            downloadHistoryBtn: document.getElementById('download-history-btn'),
            ttsAudio: document.getElementById('tts-audio')
        };
        
        this.elements.sessionId.textContent = `Session: ${this.sessionId}`;
        
        // Add TTS toggle to controls
        const ttsToggleHtml = `
            <div class="tts-toggle" style="margin: 10px 0; padding: 10px; background: #f0f0f0; border-radius: 4px;">
                <label style="display: flex; align-items: center; justify-content: center; gap: 10px; cursor: pointer;">
                    <input type="checkbox" id="tts-toggle" style="width: 18px; height: 18px;">
                    <span>Use Browser TTS (Check if OpenVoice fails)</span>
                </label>
            </div>
        `;
        document.querySelector('.voice-controls').insertAdjacentHTML('afterend', ttsToggleHtml);
        
        this.elements.ttsToggle = document.getElementById('tts-toggle');
        this.elements.ttsToggle.addEventListener('change', (e) => {
            this.useBrowserTTS = e.target.checked;
            console.log('TTS Mode:', this.useBrowserTTS ? 'Browser TTS' : 'OpenVoice TTS');
        });
    }
    
    // Initialize Web Audio API for TTS playback
    initializeWebAudio() {
        try {
            this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
            console.log('Web Audio API initialized');
        } catch (error) {
            console.error('Failed to initialize Web Audio API:', error);
        }
    }
    
    attachEventListeners() {
        // Text input
        this.elements.sendTextBtn.addEventListener('click', () => this.sendTextMessage());
        this.elements.textInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.sendTextMessage();
        });
        
        // Voice controls
        this.elements.voiceBtn.addEventListener('click', () => this.toggleVoice());
        this.elements.interruptBtn.addEventListener('click', () => this.interrupt());
        this.elements.stopBtn.addEventListener('click', () => this.stop());
        
        // Session controls
        this.elements.clearSessionBtn.addEventListener('click', () => this.clearSession());
        this.elements.downloadHistoryBtn.addEventListener('click', () => this.downloadHistory());
        
        // Audio events
        this.elements.ttsAudio.addEventListener('ended', () => {
            this.isSpeaking = false;
            this.elements.interruptBtn.disabled = true;
            this.updateState('Idle');
        });
        
        this.elements.ttsAudio.addEventListener('error', (e) => {
            console.error('Audio playback error:', e);
            this.addMessage('error', 'Failed to play audio response');
            this.isSpeaking = false;
            this.elements.interruptBtn.disabled = true;
        });
    }
    
    // Browser TTS method
    speakWithBrowserTTS(text, emotion = 'default') {
        if ('speechSynthesis' in window) {
            // Cancel any ongoing speech
            window.speechSynthesis.cancel();
            
            const utterance = new SpeechSynthesisUtterance(text);
            
            // Set voice properties based on emotion
            const emotionSettings = {
                'default': { rate: 1.0, pitch: 1.0, volume: 1.0 },
                'cheerful': { rate: 1.1, pitch: 1.2, volume: 1.0 },
                'excited': { rate: 1.2, pitch: 1.3, volume: 1.0 },
                'sad': { rate: 0.9, pitch: 0.8, volume: 0.8 },
                'angry': { rate: 1.1, pitch: 0.9, volume: 1.0 },
                'friendly': { rate: 1.0, pitch: 1.1, volume: 0.9 },
                'terrified': { rate: 1.3, pitch: 1.4, volume: 0.9 },
                'whispering': { rate: 0.8, pitch: 0.7, volume: 0.5 },
                'shouting': { rate: 1.2, pitch: 1.0, volume: 1.0 }
            };
            
            const settings = emotionSettings[emotion] || emotionSettings['default'];
            utterance.rate = settings.rate;
            utterance.pitch = settings.pitch;
            utterance.volume = settings.volume;
            
            // Select a voice (prefer English voices)
            const voices = window.speechSynthesis.getVoices();
            const englishVoice = voices.find(voice => voice.lang.startsWith('en-'));
            if (englishVoice) {
                utterance.voice = englishVoice;
            }
            
            // Handle speech events
            utterance.onstart = () => {
                this.isSpeaking = true;
                this.elements.interruptBtn.disabled = false;
                this.updateState('Speaking (Browser TTS)...');
            };
            
            utterance.onend = () => {
                this.isSpeaking = false;
                this.elements.interruptBtn.disabled = true;
                this.updateState('Ready');
            };
            
            utterance.onerror = (event) => {
                console.error('Browser TTS error:', event);
                this.isSpeaking = false;
                this.elements.interruptBtn.disabled = true;
                this.updateState('Ready');
            };
            
            // Speak
            window.speechSynthesis.speak(utterance);
        } else {
            this.addMessage('error', 'Browser TTS not supported.');
        }
    }
    
    // OpenVoice TTS using fetch (streaming)
    async speakWithOpenVoice(text, emotion = 'default') {
        try {
            this.updateState('Generating speech...');
            console.log(`Requesting OpenVoice TTS for: "${text.substring(0, 50)}..." with emotion: ${emotion}`);
            
            const response = await fetch('http://localhost:8002/synthesize_stream', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    session_id: this.sessionId,
                    text: text,
                    emotion: emotion,
                    stream: true
                })
            });
            
            console.log('TTS Response status:', response.status);
            
            if (!response.ok) {
                const errorText = await response.text();
                console.error('TTS request failed:', errorText);
                throw new Error(`TTS request failed: ${errorText}`);
            }
            
            // Get audio as blob
            const audioBlob = await response.blob();
            console.log('Audio blob size:', audioBlob.size);
            
            if (audioBlob.size === 0) {
                throw new Error('Received empty audio data');
            }
            
            const audioUrl = URL.createObjectURL(audioBlob);
            
            // Create and play audio element
            this.currentAudio = new Audio(audioUrl);
            
            // Set up event handlers before playing
            this.currentAudio.onloadedmetadata = () => {
                console.log('Audio metadata loaded, duration:', this.currentAudio.duration);
            };
            
            this.currentAudio.onplay = () => {
                console.log('Audio playback started');
                this.isSpeaking = true;
                this.elements.interruptBtn.disabled = false;
                this.updateState('Speaking (OpenVoice)...');
            };
            
            this.currentAudio.onended = () => {
                console.log('Audio playback ended');
                this.isSpeaking = false;
                this.elements.interruptBtn.disabled = true;
                this.updateState('Ready');
                URL.revokeObjectURL(audioUrl);
                this.currentAudio = null;
            };
            
            this.currentAudio.onerror = (error) => {
                console.error('Audio playback error:', error);
                this.isSpeaking = false;
                this.elements.interruptBtn.disabled = true;
                this.updateState('Error');
                URL.revokeObjectURL(audioUrl);
                this.currentAudio = null;
                
                // Fallback to browser TTS
                console.log('Falling back to browser TTS');
                this.addMessage('system', 'OpenVoice failed, using browser TTS as fallback');
                this.speakWithBrowserTTS(text, emotion);
            };
            
            // Play the audio
            console.log('Attempting to play audio...');
            await this.currentAudio.play();
            
        } catch (error) {
            console.error('OpenVoice TTS error:', error);
            this.addMessage('error', 'OpenVoice TTS failed, falling back to browser TTS');
            // Fallback to browser TTS
            this.speakWithBrowserTTS(text, emotion);
        }
    }
    
    connect() {
        const token = "my_secure_token";
        const wsUrl = `ws://localhost:8000/ws/${this.sessionId}?token=${token}`;
        this.ws = new WebSocket(wsUrl);
        
        this.ws.onopen = () => {
            this.isConnected = true;
            this.updateConnectionStatus('Connected', 'status-connected');
            this.addMessage('system', 'Connected to AI Teacher');
        };
        
        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.handleWebSocketMessage(data);
        };
        
        this.ws.onclose = () => {
            this.isConnected = false;
            this.updateConnectionStatus('Disconnected', 'status-disconnected');
            this.addMessage('system', 'Disconnected from AI Teacher');
            
            // Attempt to reconnect after 5 seconds
            setTimeout(() => this.connect(), 5000);
        };
        
        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            this.addMessage('error', 'Connection error occurred');
        };
    }
    
    handleWebSocketMessage(data) {
        console.log('WebSocket message received:', data);
        
        switch (data.type) {
            case 'system':
                this.addMessage('system', data.message);
                break;
                
            case 'status':
                this.updateState(data.message);
                break;
                
            case 'transcription':
                this.addMessage('user', `"${data.text}" (confidence: ${(data.confidence * 100).toFixed(1)}%)`);
                break;
                
            case 'ai_response':
                this.addMessage('ai', data.text, data.emotion);
                this.updateEmotion(data.emotion);
                
                // Use appropriate TTS
                if (this.useBrowserTTS) {
                    this.speakWithBrowserTTS(data.text, data.emotion);
                } else {
                    this.speakWithOpenVoice(data.text, data.emotion);
                }
                break;
                
            case 'tts_complete':
                // Not used with streaming approach
                if (!this.useBrowserTTS && data.success && data.audio_url) {
                    this.playAudio(data.audio_url);
                }
                break;
                
            case 'tts_error':
                this.addMessage('error', data.message);
                this.isSpeaking = false;
                this.elements.interruptBtn.disabled = true;
                this.updateState('Error');
                break;
                
            case 'interruption_handled':
                this.addMessage('system', 'Interruption handled');
                this.isSpeaking = false;
                this.elements.interruptBtn.disabled = true;
                break;
                
            case 'continuation_available':
                this.addMessage('system', `Would you like me to continue explaining: "${data.text}"?`);
                break;
                
            case 'error':
                this.addMessage('error', data.message);
                this.updateState('Error');
                break;
        }
    }
    
    async sendTextMessage() {
        const text = this.elements.textInput.value.trim();
        if (!text || !this.isConnected) return;
        
        // Add user message to chat
        this.addMessage('user', text);
        this.elements.textInput.value = '';
        
        // Update state
        this.updateState('Processing...');
        
        try {
            // Send to chat endpoint with longer timeout
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 30000); // 30 second timeout
            
            const response = await fetch('http://localhost:8001/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    session_id: this.sessionId,
                    message: text
                }),
                signal: controller.signal
            });
            
            clearTimeout(timeoutId);
            
            if (!response.ok) {
                const errorText = await response.text();
                console.error('Response error:', errorText);
                throw new Error('Failed to get response');
            }
            
            const data = await response.json();
            console.log('Chat response:', data);
            
            // Add AI response to chat
            this.addMessage('ai', data.ai_response, data.emotion || 'default');
            this.updateEmotion(data.emotion || 'default');
            
            // Use appropriate TTS
            if (this.useBrowserTTS) {
                this.speakWithBrowserTTS(data.ai_response, data.emotion || 'default');
            } else {
                await this.speakWithOpenVoice(data.ai_response, data.emotion || 'default');
            }
            
        } catch (error) {
            console.error('Error sending message:', error);
            if (error.name === 'AbortError') {
                this.addMessage('error', 'Request timed out. Please try again.');
            } else {
                this.addMessage('error', 'Failed to get response from AI');
            }
            this.updateState('Error');
        }
    }
    
    playAudio(audioUrl) {
        // Ensure URL is complete
        if (audioUrl.startsWith('/')) {
            audioUrl = 'http://localhost:8002' + audioUrl;
        }
        
        console.log('Playing audio:', audioUrl);
        
        this.elements.ttsAudio.src = audioUrl;
        this.elements.ttsAudio.hidden = false;
        
        // Play audio
        const playPromise = this.elements.ttsAudio.play();
        
        if (playPromise !== undefined) {
            playPromise
                .then(() => {
                    console.log('Audio playback started');
                    this.isSpeaking = true;
                    this.elements.interruptBtn.disabled = false;
                })
                .catch(error => {
                    console.error('Audio playback failed:', error);
                    this.addMessage('error', 'Failed to play audio. You may need to interact with the page first.');
                    this.isSpeaking = false;
                    this.elements.interruptBtn.disabled = true;
                    
                    // Show audio controls as fallback
                    this.elements.ttsAudio.controls = true;
                    this.elements.ttsAudio.hidden = false;
                });
        }
    }
    
    toggleVoice() {
        if (!this.isConnected) return;
        
        if (!this.isListening) {
            this.startVoiceInput();
        } else {
            this.stopVoiceInput();
        }
    }
    
    // --- Microphone streaming using Web Audio API for raw PCM ---
    mediaStream = null;
    voiceAudioContext = null;
    scriptNode = null;

    startVoiceInput() {
        this.isListening = true;
        this.elements.voiceBtn.textContent = '🎤 Listening...';
        this.elements.voiceBtn.style.backgroundColor = '#e74c3c';
        
        navigator.mediaDevices.getUserMedia({ audio: true })
            .then(stream => {
                this.mediaStream = stream;
                this.voiceAudioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
                const source = this.voiceAudioContext.createMediaStreamSource(stream);

                // ScriptProcessorNode is deprecated but still widely supported
                this.scriptNode = this.voiceAudioContext.createScriptProcessor(4096, 1, 1);

                this.scriptNode.onaudioprocess = (audioProcessingEvent) => {
                    if (!this.isConnected || !this.isListening) return;
                    const inputBuffer = audioProcessingEvent.inputBuffer;
                    const inputData = inputBuffer.getChannelData(0); // mono

                    // Convert Float32Array [-1,1] to 16-bit PCM Little Endian
                    const pcmBuffer = new ArrayBuffer(inputData.length * 2);
                    const pcmView = new DataView(pcmBuffer);
                    for (let i = 0; i < inputData.length; i++) {
                        let s = Math.max(-1, Math.min(1, inputData[i]));
                        pcmView.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
                    }
                    // Send PCM buffer as binary
                    this.ws.send(pcmBuffer);
                };

                source.connect(this.scriptNode);
                this.scriptNode.connect(this.voiceAudioContext.destination);
                
                this.updateState('Listening...');
            })
            .catch(err => {
                console.error('Microphone error:', err);
                this.addMessage('error', 'Microphone access denied or not available.');
                this.stopVoiceInput();
            });

        this.ws.send(JSON.stringify({
            type: 'start_listening'
        }));
    }

    stopVoiceInput() {
        this.isListening = false;
        this.elements.voiceBtn.textContent = '🎤 Start Voice';
        this.elements.voiceBtn.style.backgroundColor = '#27ae60';

        if (this.scriptNode) {
            this.scriptNode.disconnect();
            this.scriptNode = null;
        }
        if (this.voiceAudioContext) {
            this.voiceAudioContext.close();
            this.voiceAudioContext = null;
        }
        if (this.mediaStream) {
            this.mediaStream.getTracks().forEach(track => track.stop());
            this.mediaStream = null;
        }
        
        this.updateState('Idle');
    }
    
    interrupt() {
        if (!this.isSpeaking || !this.isConnected) return;
        
        // Stop browser TTS if active
        if (this.useBrowserTTS && 'speechSynthesis' in window) {
            window.speechSynthesis.cancel();
        }
        
        // Stop OpenVoice audio if playing
        if (this.currentAudio) {
            this.currentAudio.pause();
            this.currentAudio.currentTime = 0;
            this.currentAudio = null;
        }
        
        // Stop current audio element
        this.elements.ttsAudio.pause();
        this.elements.ttsAudio.currentTime = 0;
        
        const interruptText = prompt('What would you like to ask?');
        if (interruptText) {
            this.ws.send(JSON.stringify({
                type: 'interrupt',
                text: interruptText
            }));
            
            // Send the interrupt as a new message
            this.sendTextMessageWithContent(interruptText);
        }
    }
    
    async sendTextMessageWithContent(text) {
        // Add user message to chat
        this.addMessage('user', text);
        
        // Update state
        this.updateState('Processing...');
        
        try {
            // Send to chat endpoint
            const response = await fetch('http://localhost:8001/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    session_id: this.sessionId,
                    message: text
                })
            });
            
            if (!response.ok) {
                const errorText = await response.text();
                console.error('Response error:', errorText);
                throw new Error('Failed to get response');
            }
            
            const data = await response.json();
            console.log('Chat response:', data);
            
            // Add AI response to chat
            this.addMessage('ai', data.ai_response, data.emotion || 'default');
            this.updateEmotion(data.emotion || 'default');
            
            // Use appropriate TTS
            if (this.useBrowserTTS) {
                this.speakWithBrowserTTS(data.ai_response, data.emotion || 'default');
            } else {
                await this.speakWithOpenVoice(data.ai_response, data.emotion || 'default');
            }
            
        } catch (error) {
            console.error('Error sending message:', error);
            this.addMessage('error', 'Failed to get response from AI');
            this.updateState('Error');
        }
    }
    
    stop() {
        if (this.isConnected) {
            // Stop browser TTS
            if ('speechSynthesis' in window) {
                window.speechSynthesis.cancel();
            }
            
            // Stop OpenVoice audio if playing
            if (this.currentAudio) {
                this.currentAudio.pause();
                this.currentAudio.currentTime = 0;
                this.currentAudio = null;
            }
            
            // Stop audio playback
            this.elements.ttsAudio.pause();
            this.elements.ttsAudio.currentTime = 0;
            
            // Stop any voice input
            if (this.isListening) {
                this.stopVoiceInput();
            }
            
            fetch(`http://localhost:8002/stop/${this.sessionId}`, { method: 'POST' })
                .then(() => {
                    this.isSpeaking = false;
                    this.elements.interruptBtn.disabled = true;
                    this.updateState('Stopped');
                })
                .catch(error => console.error('Stop failed:', error));
        }
    }
    
    clearSession() {
        if (confirm('Are you sure you want to clear the conversation?')) {
            this.elements.chatMessages.innerHTML = '';
            this.addMessage('system', 'Conversation cleared');
            
            // Clear session on the backend
            fetch(`http://localhost:8001/sessions/${this.sessionId}`, { method: 'DELETE' })
                .then(response => {
                    if (response.ok) {
                        this.addMessage('system', 'Session cleared on server');
                    }
                })
                .catch(error => console.log('Failed to clear backend session:', error));
        }
    }
    
    downloadHistory() {
        // Create a JSON of the current conversation
        const messages = [];
        const messageElements = this.elements.chatMessages.querySelectorAll('.message');
        
        messageElements.forEach(elem => {
            const type = elem.classList[1]; // Get message type
            const content = elem.querySelector('.message-content').textContent;
            const time = elem.querySelector('.message-header').textContent;
            messages.push({ type, content, time });
        });
        
        const data = {
            session_id: this.sessionId,
            messages: messages,
            exported_at: new Date().toISOString()
        };
        
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `conversation_${this.sessionId}_${new Date().getTime()}.json`;
        a.click();
        URL.revokeObjectURL(url);
    }
    
    addMessage(type, text, emotion = null) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${type}`;
        
        let content = `<div class="message-header">${new Date().toLocaleTimeString()}</div>`;
        content += `<div class="message-content">${this.escapeHtml(text)}`;
        
        if (emotion && type === 'ai') {
            content += `<span class="emotion-indicator emotion-${emotion}">${emotion}</span>`;
        }
        
        content += '</div>';
        messageDiv.innerHTML = content;
        
        this.elements.chatMessages.appendChild(messageDiv);
        this.elements.chatMessages.scrollTop = this.elements.chatMessages.scrollHeight;
    }
    
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    updateConnectionStatus(status, className) {
        this.elements.connectionStatus.textContent = status;
        this.elements.connectionStatus.className = className;
    }
    
    updateState(state) {
        this.elements.currentState.textContent = state;
    }
    
    updateEmotion(emotion) {
        this.elements.currentEmotion.textContent = emotion;
    }
    
    startHealthCheck() {
        // Initial health check
        this.checkHealth();
        
        // Regular health checks
        setInterval(() => {
            this.checkHealth();
        }, 10000); // Check every 10 seconds
    }
    
    checkHealth() {
        Promise.all([
            fetch('http://localhost:8000/health').then(r => r.ok ? 'healthy' : 'unhealthy').catch(() => 'unreachable'),
            fetch('http://localhost:8001/health').then(r => r.ok ? 'healthy' : 'unhealthy').catch(() => 'unreachable'),
            fetch('http://localhost:8002/health').then(r => r.ok ? 'healthy' : 'unhealthy').catch(() => 'unreachable')
        ]).then(results => {
            const services = {
                'ASR Service': results[0],
                'Orchestrator': results[1],
                'TTS Service': results[2]
            };
            
            let statusHtml = '';
            for (const [service, status] of Object.entries(services)) {
                const className = status === 'healthy' ? 'service-healthy' : 
                                status === 'unhealthy' ? 'service-unhealthy' : 'service-unreachable';
                statusHtml += `<div class="${className}">${service}: ${status}</div>`;
            }
            this.elements.serviceStatus.innerHTML = statusHtml;
        });
    }
}

// Initialize the application when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new AITeacher();
});