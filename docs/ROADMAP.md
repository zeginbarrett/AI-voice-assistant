# Roadmap and project status

**Currently implemented in the v5 source:** local offline Whisper wake/transcription, Ollama chat, ~12-second conversational follow-ups, Windows/Piper voice selection, physical speaker volume voice commands, microSD music catalog/read service, FFmpeg decode + PCM streaming, RGB status ring and optional K2 diagnostics.

**Needs further physical validation:** install flow on a clean Windows PC; board-to-PC networking across different routers; SD mount/song indexing on multiple cards; long-duration simultaneous audio/music operation; Piper/Chatterbox performance on many GPUs.

**Potential improvements:**

- True first-run one-click installer without a previous SAM installation.
- Low-latency end-of-speech detection and more robust “Hey Sam, question” handling.
- Dedicated wake word model to reduce Whisper hallucinations.
- Hardware-level echo cancellation / music ducking that permits reliable interruptions while music plays.
- User-friendly GUI for voice choice, music library, and network configuration.
- Encryption for local audio streams and stronger pairing/rotation of tokens.
- Platform-neutral support beyond Windows.
- Automated builds and reproducible hardware verification.

Issues and pull requests are welcome; do not submit credentials or third-party voice recordings.
