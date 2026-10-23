# Install SAM (Windows + Waveshare)

## 1. Hardware and prerequisites

- Waveshare ESP32-S3-AUDIO-Board, a speaker on the board's speaker connector, USB data cable, private 2.4 GHz Wi-Fi.
- Windows 10/11 PC on the same LAN, preferably always on. For large custom TTS models, an NVIDIA GPU with CUDA helps, but baseline SAPI/faster-whisper/Ollama may work without it.
- Arduino IDE 2 or Arduino CLI with the **ESP32 by Espressif** board core (3.3.x tested), and the **Adafruit NeoPixel** library. `ESP_I2S`, `WiFi`, `Wire`, `SD_MMC`, and `HTTPClient` are from the ESP32 Arduino core.
- Python **3.12** with `numpy`, `faster-whisper`, and `ctranslate2` for the bridge. The bundled v5 upgrade installer locates an earlier configured Python venv rather than installing a fresh one.
- [Ollama](https://ollama.com/download) installed locally. From PowerShell or a command prompt: `ollama pull qwen3.5:4b`.

## 2. Decide: upgrading an earlier SAM or setting up fresh?

### Upgrade from an earlier SAM standalone version (supported one-click path)

1. Keep the older `SAM_Standalone_Voice*` folder under **Downloads**, including its existing `SAM_Voice/sam_config.h` and functioning Whisper Python virtual environment.
2. Close the old SAM window with **Ctrl+C**.
3. Extract this source tree into a new folder. Plug the board in over USB.
4. Run **`RUN_SAM_TEST.bat`**. The script searches the existing configuration, copies the local token/network settings to ignored files, detects the serial port, compiles, flashes and runs the PC bridge.
5. Later, use **`START_SAM.bat`** to start the bridge without flashing again.

### New installation (manual bootstrap)

The supplied `setup.ps1` is **an upgrade installer**, not a fully automatic first-run wizard. Do the following first:

1. Install the Arduino IDE or `arduino-cli` and set up `esp32:esp32` / Adafruit NeoPixel.
2. Install Python 3.12. In a Windows PowerShell terminal at the repository root:

   ```powershell
   py -3.12 -m venv windows\.venv
   windows\.venv\Scripts\python.exe -m pip install numpy faster-whisper ctranslate2
   ```

3. Copy `SAM_PC_Wake/sam_config.example.h` to `SAM_PC_Wake/sam_config.h` and edit the copy: insert your private Wi-Fi SSID/password, your **Windows PC LAN IPv4** (not your ESP IP), and a unique long random shared `SAM_TOKEN`.
4. Create `windows/settings.json` with exactly the same token as the firmware, plus model and port:

   ```json
   {"token":"YOUR_LONG_RANDOM_TOKEN","ollama_model":"qwen3.5:4b","whisper_model":"base.en","port":8765,"stream_port":8766,"voice_engine":"sapi","speaker_volume":75}
   ```

5. Set `windows/python_path.txt` to the **absolute path** of `windows\.venv\Scripts\python.exe` on your machine. These three local files are in `.gitignore`.
6. Install FFmpeg for music using `windows\.venv\Scripts\python.exe windows\install_ffmpeg.py`.
7. Compile and flash `SAM_PC_Wake/SAM_PC_Wake.ino` in the Arduino IDE after choosing the ESP32-S3 board with 16 MB flash and octal PSRAM. The tested Arduino-CLI board options are in `setup.ps1`.
8. Start Ollama. Run **`START_SAM.bat`**. Let Python through the Windows firewall **only for Private networks**. The PC bridge listens on TCP 8765 and 8766; music uses 8770 and 8771 on the ESP.

## 3. First hands-free test

Say **“Hey Sam”**, wait for the purple ring, then ask a question. Say a follow-up within roughly 12 seconds of the reply ending. If you say **“Hey Sam, what time is it?”** in one breath and the request is not carried through, check your `WAKE HEARD` and `HEARD` logs; behavior is version-dependent.

If the microphone shows large exact-zero percentages or the wake model hallucinates repetitive text, see [Troubleshooting](TROUBLESHOOTING.md). No-button operation is normal; K2 is a fallback.

## 4. Change SAM's voice

Run `CHOOSE_SAM_VOICE.bat` to switch Windows SAPI / optional Piper female voices. For opt-in reference-audio cloning, see [Voice options](VOICES.md). A cloned voice is **never** included in this public repository.

## 5. Protect credentials

Before committing any modifications, run `git status` and verify `sam_config.h`, `settings.json`, `python_path.txt`, `.wav`, `.mp3`, model files and logs are **not staged**. Keep the PC and ESP on your private LAN; never port-forward the SAM ports.
