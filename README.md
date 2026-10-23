# SAM — Hands-Free Local AI Voice Assistant

**A DIY female-voiced smart speaker using the Waveshare ESP32-S3-AUDIO-Board and a Windows PC.** No Home Assistant account or cloud LLM subscription is required for the baseline setup.

> **Project status:** Early community release / hardware-tested prototype. The original v4 standard-I²S microphone path and the v5 Windows speech pipeline have worked on one physical Waveshare board. Hardware, installer, SD music and voice-cloning features may need adjustment on other PCs. This is **not** a turnkey commercial product.

## What SAM can do

- **Hands-free:** say *“Hey Sam”* without touching buttons; an optional K2 diagnostic button remains.
- **Converse:** remember recent dialogue and listen automatically for follow-up questions after each reply.
- **Understand locally:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper) transcribes 16 kHz microphone audio.
- **Think locally:** [Ollama](https://ollama.com/) runs a Qwen-based conversational model on the Windows machine.
- **Speak:** built-in Windows female SAPI voices, optional [Piper](https://github.com/rhasspy/piper) neural voices, or an optional Chatterbox cloned voice if you have permission.
- **Play music:** read MP3s from a FAT32 microSD card in the Waveshare, decode on Windows with FFmpeg, and stream PCM back to the speaker.
- **Control volume by voice:** *“volume up”*, *“volume down”*, *“set volume to 40 percent”*, *“mute”*, *“unmute”*.
- **Control music by voice:** play, shuffle, skip, pause, resume, stop.

## Start here

**Hardware:** Waveshare ESP32-S3-AUDIO-Board, compatible speaker and a Windows 10/11 PC on the same private 2.4 GHz Wi-Fi network. A FAT32 microSD card is optional for music.

1. Read **[First-time installation](docs/INSTALL.md)** before flashing. This repository includes the *working-v5 upgrade installer*, which recovers configuration from an earlier SAM install; first-time users need to prepare Python, Arduino CLI and local configuration as described there.
2. Install [Ollama](https://ollama.com/), pull the model (`ollama pull qwen3.5:4b`) and keep Ollama running.
3. Use the Windows installer scripts to configure and flash your ESP32. After the first flash, double-click **`START_SAM.bat`** to start the bridge without reflashing.
4. Say **“Hey Sam”**, then ask something. After the answer, respond normally without another wake phrase while the follow-up window is open.

### Quick voice commands

| Say | Expected action |
| --- | --- |
| “Hey Sam, what time is it?” | Read the Windows PC clock |
| “Hey Sam, tell me a joke.” | Ask the local Ollama model |
| “And another one.” | Follow-up conversation (within ~12 seconds) |
| “Hey Sam, play some music.” | Shuffle the SD library |
| “Hey Sam, play Queen.” | Match artist/title against MP3 filename |
| “Next song.” / “Pause music.” | Music control |
| “Set volume to 40 percent.” | Hardware speaker volume |

## Architecture

```text
         WAVESHARE ESP32-S3 AUDIO BOARD             WINDOWS PC
  +--------------------------------------+  +------------------------------+
  | Dual microphones -> ES7210 16-bit    |  | Whisper / wake phrase        |
  | ESP32 I2S clock master @ 16 kHz      |==| Streaming speech recognition |
  | Mic audio -> TCP 8766               |  | Ollama (Qwen)                |
  | Speaker <- ES8311 <- 16 kHz PCM     |<=| Female TTS engine            |
  | MicroSD MP3 library on TCP 8770     |=>| FFmpeg MP3 decoder            |
  | Music PCM sink on TCP 8771          |<=| Music queue / voice commands |
  | RGB ring, K2 optional diagnostics   |  | Local session / follow-ups   |
  +--------------------------------------+  +------------------------------+
           PRIVATE WI-FI LAN ONLY — no TLS
```

The PC does speech, reasoning and voice generation; the ESP32 handles the microphone, speaker, ring and microSD interface. See **[How SAM works](docs/ARCHITECTURE.md)**.

## Documentation

- [Installation and setup](docs/INSTALL.md)
- [Board pins and microSD](docs/HARDWARE.md)
- [How the audio and AI pipeline works](docs/ARCHITECTURE.md)
- [Music playback](docs/MUSIC.md)
- [Female and cloned voices](docs/VOICES.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Roadmap](docs/ROADMAP.md)
- [Security and voice consent](SECURITY.md)

## Privacy / important warnings

Never commit **`sam_config.h`**, **`windows/settings.json`**, Wi-Fi credentials, shared tokens, voice recordings, `.venv`, or neural model weights. They are excluded from this public release. Audio/control streams on the LAN are **not encrypted**; use only on your trusted network and do not expose ports to the Internet.

## License and credits

This repository uses the existing [GNU GPL v3 license](LICENSE). Uses the work of the ESPHome, Espressif, Arduino, Whisper, Ollama, Piper, FFmpeg and Chatterbox projects; their own code, model files and licenses remain with their respective authors. SAM is an independent community project, not an official Waveshare, OpenAI, Ollama or ESPHome product.
