# Choose SAM's voice

**SAM's voice is selected by the user.** There is no required voice, gender or voice-cloning setup. Start with a Windows voice, or install an optional synthesis engine and model. Voices that appear in the selector depend on what is installed on your PC.

## Quick start: Windows SAPI

Run `CHOOSE_SAM_VOICE.bat` to list and choose from installed Windows speech voices. This option does not require a GPU or a separate neural voice model download, although expressiveness depends on the installed voice.

## Optional: offline Piper voices

The same selector can help install supported Piper voices, including `en_US-amy-medium` and `en_US-hfc_female-medium`. These are example model identifiers, **not** requirements or restrictions on SAM's voice. After downloading a supported model, synthesis runs locally. The Windows bridge converts synthesized speech into the 16 kHz audio format used for device playback.

## Optional: custom voice using Chatterbox (advanced / experimental)

`optional/voice_clone/` contains an **experimental Windows-only Chatterbox installer** that modifies SAM's Windows voice module, sets up an isolated Python environment and may use NVIDIA CUDA acceleration when supported. Model and PyTorch downloads can require several gigabytes. The feature is not guaranteed to work on every PC or GPU.

1. Use a voice you own or have the speaker's explicit permission to synthesize. Never use somebody else's voice without permission.
2. Prepare approximately 10–20 seconds of clean reference audio as a WAV file and store it locally at `optional/voice_clone/engine/sam_reference.wav` (ignored by Git).
3. Get the baseline v5 system working first. Close the voice server before running `optional/voice_clone/INSTALL_SAM_CLONED_VOICE.bat`.
4. The installer should preview the model, request confirmation and preserve old voice settings for rollback. Output quality and latency depend on your hardware and reference recording.
5. If the custom voice does not sound right or is too slow, run `RESTORE_OLD_SAM_VOICE.bat` to restore the previous voice configuration.

**Keep voice recordings and generated clones private.** Do not upload recordings or voice models to GitHub without the speaker's authorization. Chatterbox, Piper and their pretrained models have their own licenses and usage terms.

See [installation](INSTALL.md), [architecture](ARCHITECTURE.md) and [security](../SECURITY.md).
