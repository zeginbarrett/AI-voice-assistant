# Contributing

1. Search existing issues before opening a new one. Describe the board revision, Arduino core version, Windows and GPU type when relevant.
2. Create focused commits with runnable test steps and a clear description of changed behavior.
3. Run `python -m unittest discover -s tests -v` with the required packages before submitting; hardware behavior requires a real board check.
4. Use sanitized examples: never include Wi-Fi passwords, LAN authentication tokens, personal voice references, copyrighted music tracks or model weights in a PR.
5. Code is published under GPL-3.0; by contributing you agree that your contribution can be distributed under the repository's license.
