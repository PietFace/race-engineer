"""Kijkt op GitHub of er een nieuwere versie is, en kan hem zelf downloaden en installeren."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import urllib.request

from version import GITHUB_REPO, VERSION


def _parse(v):
    v = (v or "").strip().lstrip("vV")
    out = []
    for part in v.split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    while len(out) < 3:
        out.append(0)
    return tuple(out[:3])


def is_newer(latest, current=VERSION):
    return _parse(latest) > _parse(current)


def check_async(callback):
    """callback(info) met info = {"versie", "url", "notities"} als er een update is, anders niets."""
    if not GITHUB_REPO:
        return

    def worker():
        try:
            req = urllib.request.Request(
                f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
                headers={"Accept": "application/vnd.github+json", "User-Agent": "RaceEngineer"})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read().decode("utf-8"))
            tag = data.get("tag_name", "")
            if is_newer(tag):
                setup = next((a.get("browser_download_url") for a in data.get("assets", [])
                              if str(a.get("name", "")).lower().endswith(".exe")), None)
                callback({"versie": tag.lstrip("vV"), "url": data.get("html_url"), "setup": setup,
                          "notities": (data.get("body") or "")[:400]})
        except Exception:
            pass   # geen internet of geen release: gewoon stil blijven
    threading.Thread(target=worker, daemon=True).start()


def can_self_update(info):
    """Alleen in het geïnstalleerde programma op Windows, en als de installer bij de release staat."""
    return bool(info and info.get("setup")) and sys.platform == "win32" and getattr(sys, "frozen", False)


def download_and_install(info, progress, done):
    """Download de installer op de achtergrond. progress(procent), done(fout_of_None).
    Daarna start de installer stil; die sluit het programma, werkt bij en start het opnieuw."""
    def worker():
        try:
            path = os.path.join(tempfile.gettempdir(), f"RaceEngineer-Setup-{info['versie']}.exe")
            req = urllib.request.Request(info["setup"], headers={"User-Agent": "RaceEngineer"})
            with urllib.request.urlopen(req, timeout=30) as r, open(path + ".part", "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                got = 0
                while True:
                    chunk = r.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    if total:
                        progress(int(got * 100 / total))
            if total and got < total:
                raise IOError("download onvolledig")
            if os.path.exists(path):
                os.remove(path)
            os.rename(path + ".part", path)
            flags = 0x00000008 | 0x00000200   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            subprocess.Popen([path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                             creationflags=flags, close_fds=True)
            done(None)
        except Exception as e:
            done(str(e) or "onbekende fout")
    threading.Thread(target=worker, daemon=True).start()
