# Playing MP3 music from microSD

1. Back up your card first, then use **FAT32** if formatting is needed. Use normal, non-DRM `.mp3` files. Format outside the ESP; SAM reads the card and does not erase songs.
2. Create `/Music` and copy files with useful titles (e.g., `Music/Artist - Song.mp3`). The firmware scans on boot, so insert the card before powering the board.
3. On Windows, run `INSTALL_MUSIC_DECODER.bat` once, or let `RUN_SAM_TEST.bat` set up the decoder during the initial upgrade installation. This installs a standalone FFmpeg executable, not Python's pip.
4. Start SAM and try **“Hey Sam, play some music”**, **“play Queen”**, **“next song”**, **“pause music”**, **“resume music”**, **“stop music”**, and **“volume down”**.

**Data path:** Waveshare SD card → Wi-Fi HTTP 8770 → Windows FFmpeg → 16 kHz PCM over Wi-Fi TCP 8771 → ES8311 output.

If SAM speaks but music is silent, check for `SD READY`/card-mount diagnostics, file indexing results, the Windows FFmpeg binary in `windows/tools/`, and whether a Windows firewall blocks the private LAN. Hardware-dependent SD-card issues remain a possible limitation.
