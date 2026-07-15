# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


hiddenimports = []
hiddenimports += collect_submodules("faster_whisper")
hiddenimports += collect_submodules("ctranslate2")
hiddenimports += collect_submodules("huggingface_hub")
hiddenimports += collect_submodules("requests")
hiddenimports += collect_submodules("soundcard")

datas = [
    ("questions", "questions"),
]
datas += collect_data_files("faster_whisper")


a = Analysis(
    ["app/main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="InterviewAssistant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="InterviewAssistant",
)
app = BUNDLE(
    coll,
    name="InterviewAssistant.app",
    icon=None,
    bundle_identifier="local.interviewassistant",
    info_plist={
        "NSMicrophoneUsageDescription": (
            "Interview Assistant needs audio input access to transcribe "
            "interview questions from the selected device."
        ),
    },
)
