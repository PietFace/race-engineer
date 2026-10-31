"""Zet het versienummer in het programma en in de Windows-bestandsinfo.
Gebruik:  python installer/set_version.py 2.1.0 gebruiker/repository"""
import os
import re
import sys

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
version = sys.argv[1].strip().lstrip("vV") if len(sys.argv) > 1 else "0.0.0"
repo = sys.argv[2].strip() if len(sys.argv) > 2 else ""
if not re.fullmatch(r"\d+(\.\d+){0,3}", version):
    sys.exit(f"Ongeldig versienummer: '{version}'. Gebruik bijvoorbeeld 2.1.0")

with open(os.path.join(root, "version.py"), "w", encoding="utf-8") as f:
    f.write('"""Versie en update-bron. De automatische build op GitHub vult deze waarden zelf in."""\n')
    f.write(f'VERSION = "{version}"\n')
    f.write(f'GITHUB_REPO = "{repo}"\n')

nums = [int(x) for x in version.split(".")] + [0, 0, 0]
t = tuple(nums[:4])
with open(os.path.join(root, "installer", "file_version.txt"), "w", encoding="utf-8") as f:
    f.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041304B0', [
      StringStruct('CompanyName', 'AI Race Engineer'),
      StringStruct('FileDescription', 'AI Race Engineer voor iRacing'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'RaceEngineer'),
      StringStruct('OriginalFilename', 'RaceEngineer.exe'),
      StringStruct('ProductName', 'AI Race Engineer'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1043, 1200])])
  ]
)
""")
print(f"Versie {version} ingesteld (updates via: {repo or 'uit'})")
