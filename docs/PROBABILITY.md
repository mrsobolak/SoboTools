# Can software fix the Ender 5 Pro "TMC CONNECTION ERROR"?

The situation is four used Ender 5 Pros from the same school. All four show the same error,
board versions are unknown, and the PC can talk to all of them over USB.

## What the source code says

* Marlin raises `TMC CONNECTION ERROR` only from `test_tmc_connection()`
  (`Marlin/src/feature/tmc_util.cpp`). That function runs at startup and at the end of `M122`.
* It is compiled only when the firmware has **UART/SPI** TMC drivers configured
  (`HAS_TRINAMIC_CONFIG`). Firmware with `*_STANDALONE` drivers doesn't even have `M122`
  (`Unknown command`), so it **cannot** show this error.
* Every stock Creality board the Ender 5 Pro shipped with is wired for standalone drivers, with
  no UART line: the 1.1.5 (ATmega1284P), the 4.2.2 and the 4.2.7. Marlin's official Ender-5 Pro
  configs for all three use `TMC2208_STANDALONE`.
* On a UART driver, "no reply" reads back as `0`, which Marlin prints as **"Error: All LOW"**.

**Conclusion:** on a stock board, this error means the firmware is wrong for the board. It is
not a dead chip. Four identical machines with the same symptom strongly suggest the school
flashed the same image onto all of them.

## Likely causes (per printer)

| Cause | Odds | Fixed by Sobolak Repair? |
|---|---|---|
| Stock Creality board running UART-driver firmware | ~60% | **Yes**, by flashing standalone firmware |
| SKR Mini E3 upgrade with wrong-revision firmware, or 24 V off | ~25% | **Yes** (correct revision), or a power fix the app points out |
| Other (custom board, wiring, damage) | ~10% | Diagnosed only |
| Real driver failure | <5% | Diagnosed only; needs a new board (~$30–40) |

## Odds of success

| Goal | Odds |
|---|---|
| Correctly diagnose each printer over USB | **~95%** |
| Fix each printer with Sobolak Repair + one SD card swap | **~85–90%** |
| All four printers fixed | **~70%** (lower if one of them really has a hardware fault) |
| Fully hands-free (no SD card) | Not possible with the stock bootloader |

## Remaining risks

* **4.2.2 vs 4.2.7:** software can't tell them apart, and their STEP/DIR pins are swapped. The
  app picks the most likely one (or the one named in the current firmware). The motor test after
  flashing catches a wrong pick and offers the other image.
* **GD32 chips:** some newer 4.2.x boards use a GD32F303 instead of the STM32. STM32 builds
  usually run on it, but not always.
* **1.1.x boards:** these flash over USB with avrdude, not by SD card. That isn't automated yet.
* **SD cards:** the Creality bootloader gives no success signal and silently skips a file name
  it has already flashed. Sobolak Repair writes a fresh name each time and verifies the result
  by re-scanning.

## Sources

* Marlin `tmc_util.cpp`, `M122.cpp`, `drivers.h`, `pins_CREALITY_V4.h`, `pins_CREALITY_V427.h`
  (MarlinFirmware/Marlin, 2.1.x)
* MarlinFirmware/Configurations `release-2.1.2.9`, `config/examples/Creality/Ender-5 Pro/*`
* TMCStepper `TMCStepper.cpp` / `TMC2208Stepper.cpp` (All HIGH / All LOW semantics)
* Klipper `scripts/spi_flash/board_defs.py` (Creality bootloader needs a unique file name)
* Creality forum threads on Ender 5 Pro TMC connection errors, fixed by reflashing
