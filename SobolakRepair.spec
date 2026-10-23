# PyInstaller build for Sobolak Repair:  pyinstaller SobolakRepair.spec
import os

datas = [("assets", "assets")]
if os.path.isdir(os.path.join("sobolak_repair", "firmware")):
    datas.append((os.path.join("sobolak_repair", "firmware"), os.path.join("sobolak_repair", "firmware")))

a = Analysis(["run_sobolak.py"], datas=datas, hiddenimports=["serial.tools.list_ports_windows"],
             excludes=["numpy", "matplotlib", "pytest"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="SobolakRepair", console=False,
          icon=os.path.join("assets", "sobolak.ico"), version="version_info.txt", upx=False)
