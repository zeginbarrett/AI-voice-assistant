# Troubleshooting

| Symptom | What to check |
| --- | --- |
| `Cannot find an overload for Add` during old GPU clone install | Upgrade to a version that does not shadow PowerShell's reserved `$Matches` variable. The optional version here uses a corrected locator. |
| `No module named pip` while adding MP3 decoder | Use `INSTALL_MUSIC_DECODER.bat`: the repaired v5 installer downloads stand-alone FFmpeg and **does not use pip** for MP3 playback. |
| 87.6% of mic samples are exact zeros | Usually the **wrong ES7210/I²S framing**; confirm the standard-I²S 16-bit v4/v5 firmware, not the experimental TDM build. |
| Transcripts repeat “Okay”, “You” or nonsense | Whisper may hallucinate on silence/noisy audio; check mic WAV diagnostics, speak within range and avoid loud speaker feedback. Silence filters are heuristic, not perfect. |
| `Hey Sam` works but the question is missed | Wait for the purple ring or use a shorter wake/question phrase. Check `HEARD:` log lines. The conversation window expires after ~12 s of inactivity. |
| SAM answers with the wrong clock time | The Windows system clock/time zone must be correct; simple time questions are supposed to be handled locally, not invented by Ollama. |
| Speaker talks but songs do not play | Verify FAT32 SD, MP3 files, mounted card and installed FFmpeg, then confirm private LAN TCP 8770/8771 availability. |
| Python venv or config missing | The included one-click `setup.ps1` needs an earlier SAM standalone installation. New users must follow the [manual bootstrap](INSTALL.md). |
| CUDA not detected for voice cloning | `nvidia-smi` alone isn't enough. PyTorch must be a **CUDA build** and report `torch.cuda.is_available() == True`. |
| Arduino compilation fails | Verify esp32 Arduino core 3.3.x, 16M flash, octal PSRAM, Adafruit NeoPixel; inspect `logs/compile.log`. |
| Device disconnects / can't connect PC | Same LAN, correct PC IPv4 in `sam_config.h`, Windows Private firewall, and TCP 8765/8766. |

To protect privacy, redact Wi-Fi passwords, token values, and personal voice data before posting logs publicly.
