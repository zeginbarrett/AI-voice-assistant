# Female voices and optional cloning

## Fastest: Windows SAPI

`CHOOSE_SAM_VOICE.bat` lists installed Windows voices. No GPU or additional model download is required, but expressiveness is limited.

## Offline Piper

The same selector can install Piper's `en_US-amy-medium` or `en_US-hfc_female-medium` voice. After the initial model download, synthesis runs locally. The bridge converts the result into the 16 kHz WAV format required by SAM's speaker.

## Optional Chatterbox voice cloning (advanced)

`optional/voice_clone/` contains an **experimental Windows-only Chatterbox installer** that patches SAM's PC voice module, creates an isolated Python environment and can attempt NVIDIA CUDA acceleration. Model/PyTorch downloads can take multiple gigabytes. This path was developed for a GPU equipped Windows PC but is **not guaranteed to run on every card**.

1. You must have the speaker's consent or own the relevant voice rights. Use **your own approved** clear reference sample. We do **not** redistribute anybody's personal voice recordings.
2. Convert approximately 10–20 seconds of clean speech into WAV and save locally as `optional/voice_clone/engine/sam_reference.wav` (this file is ignored by Git).
3. After the baseline SAM v5 works, close it and run `optional/voice_clone/INSTALL_SAM_CLONED_VOICE.bat`.
4. The installer should preview the new voice, request confirmation, and save old voice settings for rollback. Actual runtime latency depends on VRAM and CPU/GPU performance.
5. Use `RESTORE_OLD_SAM_VOICE.bat` if cloning sounds wrong or synthesis stalls.

**Do not upload a reference clip or cloned outputs to GitHub without the speaker's explicit permission.** Chatterbox, Piper and their pretrained models are distributed under their own separate terms.
