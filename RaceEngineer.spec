# PyInstaller-recept voor AI Race Engineer.  Bouwen:  pyinstaller --noconfirm RaceEngineer.spec
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hidden = []
for pkg in ("pyttsx3", "edge_tts", "anthropic", "qrcode", "speech_recognition"):
    try:
        hidden += collect_submodules(pkg)
    except Exception:
        pass
hidden += ["irsdk", "keyboard", "pygame", "comtypes", "comtypes.client", "pythoncom", "pywintypes"]

datas = [("icon.ico", ".")]
for pkg in ("speech_recognition", "certifi", "edge_tts"):
    try:
        datas += collect_data_files(pkg)
    except Exception:
        pass

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy.tests", "PySide6.QtWebEngineCore", "PySide6.Qt3DCore",
              "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtPdf"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RaceEngineer",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon="icon.ico",
    version="installer/file_version.txt",
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="RaceEngineer")
