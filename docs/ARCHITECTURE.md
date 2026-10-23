# How SAM works

SAM is two cooperating programs: a continuously running ESP32 firmware and a Windows voice server.

### Microphone, wake word, and question

1. The ESP32 drives shared I²S clocks, initializes the ES7210 mic ADC and ES8311 speaker codec, captures 16 kHz stereo PCM, and sends framed packets via Wi-Fi TCP **8766**.
2. The Windows bridge (`windows/sam_pc_wake.py`) checks message authentication, audio integrity, left/right RMS and zero patterns, and stores short diagnostics locally.
3. **faster-whisper** runs offline on the Windows machine, identifying “Hey Sam” from the continuous microphone stream. K2 can manually trigger listening for diagnostics.
4. The next utterance is transcribed. A rolling buffer allows some immediate speech after the wake phrase; the bridge rejects characteristic Whisper repetitive hallucinations when possible.
5. Local commands (time, music, volume) are handled directly; free-form questions are sent to **Ollama** `http://127.0.0.1:11434/api/chat` with recent turns as context.
6. The answer is converted to a 16 kHz WAV by the user's selected voice engine and model: an available Windows SAPI voice, optional Piper, or opt-in Chatterbox custom voice.
7. A local HTTP reply on **8765** tells the ESP32 to play the WAV through ES8311. After speaking, Windows opens a follow-up window of ~12 seconds so no second wake phrase is needed.

### Music

The ESP32 mounts the microSD card read-only and exposes music filenames/files over local HTTP on **8770**. Windows indexes titles, fetches MP3s, decodes using local FFmpeg, and returns **16 kHz stereo PCM** over TCP **8771**. Music stops/pauses as speech needs the audio path. Music and TTS use the same board output and hardware volume setting.

### What runs locally / what is downloaded

Speech recognition, reasoning and synthesis are local once their models are installed. Initial installs of the Whisper and Qwen models, optional Piper/Chatterbox models, or FFmpeg require Internet downloads. The system does not need a cloud account for ordinary text dialogue after setup.

### Limitations

- LAN control and PCM are **not encrypted**. This is intended for a trusted home network only.
- A PC must remain running; the ESP32 cannot execute the chosen Ollama LLM by itself.
- No hardware acoustic echo cancellation is integrated; SAM may struggle to hear speech during loud playback.
- Conversation mode is a time-limited follow-up window, not unrestricted always-on full duplex conversation.
- Chatterbox voice cloning is computationally expensive and might delay responses.
