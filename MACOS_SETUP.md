# macOS setup

## 1. Install Python

Install Python 3.11+ on the Mac. If Homebrew is available:

```bash
brew install python
```

## 2. Build the app

Open Terminal in the project folder and run:

```bash
chmod +x build_macos.sh
./build_macos.sh
```

The app will be created at:

```text
dist/InterviewAssistant.app
```

Run it with:

```bash
open dist/InterviewAssistant.app
```

## 3. Give microphone permission

On first launch macOS can ask for microphone access. Allow it.

If it does not ask, open:

```text
System Settings -> Privacy & Security -> Microphone
```

Then allow `InterviewAssistant` or the Terminal/Python process used to launch it.

## 4. Capture Google Meet audio

To listen to the interviewer instead of your microphone, install a virtual audio device such as BlackHole.

Typical Google Meet routing:

1. Install BlackHole 2ch.
2. Open `Audio MIDI Setup`.
3. Create a `Multi-Output Device`.
4. Enable your headphones/speakers and `BlackHole 2ch` in that Multi-Output Device.
5. In macOS sound output or Google Meet speaker settings, choose the Multi-Output Device.
6. In Interview Assistant, choose:

```text
Системный звук / Meet: BlackHole 2ch
```

If you only choose your regular microphone, the app will listen to you, not the person in Google Meet.

Do not choose `Steam Streaming Speakers` for Google Meet audio. On macOS it can appear like a system-audio source, but it usually does not provide a stable recording stream to the app. Use `BlackHole 2ch` or another virtual audio device instead.

## 5. Logs

On macOS the app writes logs to:

```text
~/InterviewAssistant/logs
```

Open the logs folder with:

```bash
open ~/InterviewAssistant/logs
```

Question history:

```text
~/InterviewAssistant/logs/asked_questions.md
```

Program analysis:

```text
~/InterviewAssistant/logs/program_analysis.md
```
