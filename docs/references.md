# References and attribution

The Python implementation is independently written and uses only the Python
standard library. No third-party source code or binaries are bundled.

- [TI BQ24780S datasheet](https://www.ti.com/lit/ds/symlink/bq24780s.pdf):
  manufacturer/device IDs and ChargeOption0 `CHRG_INHIBIT` semantics.
- [Linux `sbshc.c`](https://github.com/torvalds/linux/blob/master/drivers/acpi/sbshc.c)
  and [`sbshc.h`](https://github.com/torvalds/linux/blob/master/drivers/acpi/sbshc.h):
  EC SMBus mailbox layout and protocol constants. Linux source is separately
  licensed under GPL-2.0; it is referenced for protocol behavior, not included.
- [Coreboot LPC definitions](https://github.com/coreboot/coreboot/blob/main/src/soc/intel/common/block/include/intelblocks/lpc_lib.h):
  conventional EC I/O port decoding.
- [Cr0wTom/Mi-Notebook-Pro-Mods](https://github.com/Cr0wTom/Mi-Notebook-Pro-Mods):
  collection used to locate the matching BIOS update package for offline analysis.
  Its repository license is not treated as a license to redistribute vendor firmware.
- [jwise/x2100-ec](https://github.com/jwise/x2100-ec): background research on
  CompactRISC EC firmware for different hardware; no patches were imported.
- [GNU binutils 2.45](https://ftp.gnu.org/gnu/binutils/binutils-2.45.tar.xz):
  disassembler built locally with `--target=cr16-elf`. No binary is distributed.

Xiaomi, Timi, SUNWODA, and Texas Instruments names identify tested hardware.
This project is an independent implementation and is not vendor-endorsed.
