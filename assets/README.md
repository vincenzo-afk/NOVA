# assets/

This directory stores static assets required by NOVA at runtime.

## Wake-Word Model (Porcupine `.ppn` file)

NOVA uses [Picovoice Porcupine](https://picovoice.ai/platform/porcupine/) for wake-word detection.

The `.ppn` keyword file is **platform-specific** and **not included** in the repository.

### How to get it

1. Sign up for a free account at https://console.picovoice.ai/
2. Go to **Porcupine** → **Train a Custom Keyword** (or use a pre-built keyword)
3. Download the Windows `.ppn` file
4. Place it in this directory: `assets/Hey-Nova_en_windows_v3_0_0.ppn`
5. Set `PORCUPINE_KEYWORD_PATH=./assets/Hey-Nova_en_windows_v3_0_0.ppn` in your `.env`
6. Set `PORCUPINE_ACCESS_KEY=<your_key>` in your `.env`

> **Note:** If `PORCUPINE_ACCESS_KEY` is set but the `.ppn` file is missing, NOVA will print a clear error at startup and continue without wake-word detection.
