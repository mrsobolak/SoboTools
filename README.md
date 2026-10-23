# SoboTools

## ender_doctor — Tim Cheese Scanner

Diagnoses Ender 5 Pro printers that show **TMC CONNECTION ERROR**, over USB.

### Use it (Windows 10)

1. Install Python from <https://www.python.org/downloads/> and tick **"Add python.exe to PATH"**
   (or run `winget install Python.Python.3.12` in a terminal).
2. Download this repo (green **Code** button → **Download ZIP**) and unzip it.
3. Turn the printer **on** (power switch + wall plug) and connect it to the PC with USB.
   Close Cura, Pronterface, or anything else that might be using the printer.
4. Double-click `ender_doctor\run_scanner.bat`.
5. Give the printer a name when asked (`ender1`, `ender2`, ...).
6. Repeat for every printer. Reports land in `ender_doctor\reports\`.

If no COM port is found: try a different USB cable (many are charge-only), or install the
CH340 USB driver (search "CH340 driver WCH").

Optional: `run_scanner.bat --reboot` also restarts the printer to capture its startup log.

### What the verdicts mean

| Verdict | Meaning |
|---|---|
| `FIRMWARE_MISMATCH_LIKELY` | Stock Creality board, but firmware tries to talk to the drivers over UART. Reflash with standalone-driver firmware. |
| `ALL_DRIVERS_FAIL` | Every driver silent — motor power off, or firmware doesn't match the board. |
| `SOME_DRIVERS_FAIL` | Only some axes fail — likely hardware (driver chip, jumper, solder). |
| `DRIVERS_OK_NOW` | Drivers answer now — error is probably a power-up timing / USB-power issue. |
| `DRIVERS_STANDALONE` | Firmware doesn't use UART at all, so it shouldn't raise this error. |
| `KLIPPER_OR_WRONG_BAUD` | Board speaks binary — probably Klipper firmware. |
| `NO_RESPONSE` | Nothing answered — wrong port, port busy, or no working firmware. |

### Tests

```
cd ender_doctor
py tests/test_diagnose.py
```
