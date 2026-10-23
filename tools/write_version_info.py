"""Write version_info.txt (Windows file properties for the .exe) from the package version."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sobolak_repair import APP_NAME, __version__  # noqa: E402

nums = tuple(int(x) for x in __version__.split(".")) + (0,) * (4 - len(__version__.split(".")))
template = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Sobolak Technologies'),
      StringStruct('FileDescription', '{APP_NAME}'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('InternalName', 'SobolakRepair'),
      StringStruct('LegalCopyright', 'Sobolak Technologies'),
      StringStruct('OriginalFilename', 'SobolakRepair.exe'),
      StringStruct('ProductName', '{APP_NAME}'),
      StringStruct('ProductVersion', '{__version__}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
with open(os.path.join(os.path.dirname(__file__), "..", "version_info.txt"), "w") as f:
    f.write(template)
print("version_info.txt written for", __version__)
