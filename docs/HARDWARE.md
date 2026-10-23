# Waveshare ESP32-S3-AUDIO-Board reference

This project targets the Waveshare **ESP32-S3-AUDIO-Board** with an ES7210 dual-microphone ADC and ES8311 speaker codec. Do not assume another ESP32-S3 board has the same wiring.

| Function | GPIO / address |
| --- | --- |
| I²C SDA / SCL | GPIO11 / GPIO10 |
| ES7210 (microphone ADC) | I²C 0x40 |
| ES8311 (speaker codec) | I²C 0x18 |
| TCA9555 expander | I²C 0x20 |
| I²S MCLK / BCLK / WS | GPIO12 / GPIO13 / GPIO14 |
| ADC data input / DAC data output | GPIO15 / GPIO16 |
| 7-LED WS2812 ring | GPIO38 |
| Speaker amplifier enable | Expander EXIO8, active high |
| K2 diagnostic button | Expander EXIO10 |
| SD_MMC CLK / CMD / DATA0 | GPIO40 / GPIO42 / GPIO41 |
| SD card select | Expander EXIO3 |

The ES7210 and ES8311 **share BCLK and LRCLK**; the ESP32 provides master clocks. The working v4 microphone uses **standard 16-bit I²S at 16 kHz** and is carried into SAM v5. Earlier 16 kHz four-slot TDM experiments showed about 87.6% zero samples; changing to standard 16-bit I²S reduced that figure to roughly 2% in the original build.

The board needs **2.4 GHz Wi-Fi**. Music requires a FAT32 microSD card inserted before board boot. Do not change expander mux pins EXIO6/EXIO7—they have conflicting documentation and can interfere with USB/camera selection.

References: [Waveshare wiki](https://www.waveshare.com/wiki/ESP32-S3-AUDIO-Board), [ESPHome board implementation](https://github.com/MichalZaniewicz/esphome-waveshare-esp32-s3-audio-va), [ESPHome ES7210 driver](https://github.com/esphome/esphome/blob/dev/esphome/components/es7210/es7210.cpp).
