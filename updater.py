"""Kijkt op GitHub of er een nieuwere versie is."""
import json
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
                callback({"versie": tag.lstrip("vV"), "url": data.get("html_url"),
                          "notities": (data.get("body") or "")[:400]})
        except Exception:
            pass   # geen internet of geen release: gewoon stil blijven
    threading.Thread(target=worker, daemon=True).start()
