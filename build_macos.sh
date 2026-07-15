#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if pgrep -f "InterviewAssistant" >/dev/null 2>&1; then
  echo "InterviewAssistant is running. Close it, then run this build script again."
  exit 1
fi

rm -rf build dist

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python -m PyInstaller --noconfirm --clean InterviewAssistant_macos.spec

mkdir -p dist/InterviewAssistant/recordings
rm -rf dist/InterviewAssistant/questions
cp -R questions dist/InterviewAssistant/questions

echo ""
echo "Done."
echo "Run app bundle: open dist/InterviewAssistant.app"
echo "Or run folder executable: dist/InterviewAssistant/InterviewAssistant"
