# Open-source components

SAM interfaces with a variety of independent projects. The fact that SAM links to or downloads a dependency does not change that dependency's license. Consult current upstream license terms before redistributing copies of binaries or trained model weights:

- Waveshare / Espressif / Arduino ESP32 (hardware drivers and Arduino platform)
- ESPHome (ES7210 register setup reference)
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) / CTranslate2
- [Ollama](https://ollama.com/) and the selected Qwen model
- [Piper](https://github.com/rhasspy/piper), individual Piper voices
- [FFmpeg](https://ffmpeg.org/) (binary licenses can vary by build)
- [Chatterbox](https://github.com/resemble-ai/chatterbox) (optional model and related libraries)

The public repository includes **only SAM source**, no third-party voice reference or AI model weights.
