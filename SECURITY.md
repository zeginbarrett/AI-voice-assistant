# Security and responsible use

SAM was designed for an isolated **trusted home LAN**, not public Internet deployment.

* The ESP32 exchanges unencrypted PCM, MP3 bytes, and control messages with the Windows host. A shared random token authenticates the audio sessions but does **not** make them private against LAN eavesdropping.
* Do **not** forward TCP ports **8765, 8766, 8770, 8771** on your router. Use a private Wi-Fi network and Windows Private-network firewall rules only.
* Keep `SAM_PC_Wake/sam_config.h`, `windows/settings.json`, voice recordings, log files, and model downloads **out of Git**. `.gitignore` covers their ordinary paths, but inspect every commit before pushing.
* Avoid publishing third-party voice clips without the speaker's permission. The optional voice-cloning add-on intentionally ships with **no voice samples**; provide an authorized recording locally.
* Downloaded FFmpeg, PyTorch, Piper, Whisper and Chatterbox models are not part of this repository. Check their licenses and the terms of any model you use.
* The project is provided as hobby software and has no verified security audit. Please report vulnerabilities privately to the repository owner before publicly disclosing reproducible exploitation steps.
