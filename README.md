# Sobolak Repair

**by Sobolak Technologies**

Sobolak Repair finds and fixes **TMC CONNECTION ERROR** on Creality Ender 5 Pro printers.
Plug a printer in over USB, and it diagnoses the fault, writes the correct firmware to an SD card,
and checks that the repair worked.

## Download

Grab `SobolakRepair.exe` from the latest **Release**, or from the newest successful run under
**Actions → Build Sobolak Repair → Artifacts → SobolakRepair-windows**. It's one file with
nothing to install, and it runs on Windows 10 and 11.

> The .exe isn't code-signed yet, so Windows SmartScreen may say "Windows protected your PC".
> Click **More info → Run anyway**.

## Using it

1. Switch the printer on and connect it to the PC with USB. Close Cura and OctoPrint.
2. Open Sobolak Repair and click **Start repair**.
3. Give the printer a name and pick its port. The scan takes about 20 seconds.
4. If the firmware is the problem, choose the board (the best match is pre-selected), insert a
   microSD card (8–16 GB, FAT32) and click **Write firmware**.
5. Move the card to the printer, power-cycle it, and let Sobolak Repair confirm the fix.
6. Optional: reset settings to defaults and run the 1 cm motor test.

Reports are saved to `Documents\Sobolak Repair\reports\`, and the list of printers is kept in
`Documents\Sobolak Repair\printers.json`.

## What it can diagnose

| Result | Meaning | Fix |
|---|---|---|
| Wrong firmware for this board | Stock Creality board, but the firmware tries to talk to the drivers over UART, which these boards don't have. Every driver reports *All LOW*. | Flash standalone-driver firmware |
| No driver is answering | Upgrade board (e.g. BTT SKR). Either the 24 V power is off or the firmware is for another board revision. | Check power, then flash the correct revision |
| Some drivers are not answering | Only some axes fail, which points at hardware. | Board replacement |
| Drivers answer right now | Power-up timing or USB-only power. | Power on before plugging in USB |
| No driver problem found | Standalone firmware, which can't raise this error. | Nothing to do |
| Printer is running Klipper | Binary protocol, needs a host computer. | Flash Marlin to run standalone |

## Supported boards and firmware

Firmware is built from official **Marlin 2.1.2.9** and the Ender-5 Pro example configs in
[MarlinFirmware/Configurations](https://github.com/MarlinFirmware/Configurations). The exact
edits are listed in [`firmware/build_firmware.py`](firmware/build_firmware.py).

| Image | Board | How it's flashed |
|---|---|---|
| `creality_v422` | Creality 4.2.2, stock | SD card, new file name each time |
| `creality_v422_bltouch` | Creality 4.2.2 + BLTouch / CR Touch | SD card |
| `creality_v427` | Creality 4.2.7 | SD card |
| `skr_mini_e3_v1_2` / `_v2` / `_v3` | BigTreeTech SKR Mini E3 | SD card, `firmware.bin` |
| `creality_v1` | Creality 1.1.x (8-bit) | USB / avrdude (not automated yet) |

The 4.2.2 and 4.2.7 boards have their STEP and DIR pins swapped. If the motor test buzzes
instead of moving, the app offers the other version.

## Building from source

```
pip install -r requirements.txt
python run_sobolak.py          # run the app
python -m pytest tests         # tests
```

GitHub Actions (`.github/workflows/build.yml`) builds the firmware images with PlatformIO and
then the single-file `SobolakRepair.exe` with PyInstaller. Pushing a `v*` tag publishes a
Release.

To build firmware locally, clone Marlin and Configurations at the versions named in
`firmware/build_firmware.py`, then run:

```
python firmware/build_firmware.py --marlin path/to/Marlin --configs path/to/Configurations
```

## Licenses

* Sobolak Repair © Sobolak Technologies.
* Bundled firmware is built from [Marlin](https://github.com/MarlinFirmware/Marlin) (GPL-3.0).
  Its source and the exact build configuration are linked above.
* The bundled Inter typeface is used under the SIL Open Font License 1.1
  (`assets/fonts/LICENSE-Inter.txt`).
