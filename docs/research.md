# TM1701 / BIOS 0906 charging-control research

Investigation date: 2026-10-13. Results apply to one Timi TM1701 with BIOS
XMAKB5R0P0906, SUNWODA R15B01W battery, and BQ24780S charger.

## Live evidence

The charger returned manufacturer ID `0x0040` at register `0xFE` and device ID
`0x0030` at `0xFF`. These match the BQ24780S. Its
[datasheet](https://www.ti.com/lit/ds/symlink/bq24780s.pdf), sections 7.6.1 and
7.6.2.1, documents these identifiers and bit 0 of `ChargeOption0` (`0x12`),
`CHRG_INHIBIT`: setting it inhibits charging.

The baseline `ChargeOption0` was `0x8108`. Changing only bit 0 to produce
`0x8109` paused charging while AC remained connected. Clearing it restored
`0x8108` and charging resumed:

| Phase | ChargeOption0 | Direct battery current | AC online |
| --- | --- | --- | --- |
| Before pause | `0x8108` | +806 mA | 1 |
| Ten one-second pause samples | `0x8109` | -64 to 0 mA | 1 |
| After restoration | `0x8108` | +2,004 mA | 1 |

All pause currents, in observation order: `0, -19, 0, 0, -13, -64, -27, 0, 0, 0`
mA. The signed current comes directly from Smart Battery command `0x0A`.
An earlier three-second experiment had inconclusive Linux telemetry; the
ten-second experiment used direct battery readings to establish the effect.

Linux `BAT0/status` continued to report `Charging`; its power reading also
lagged. Direct charger readback and battery current are needed for verification.
The controller was subsequently installed with 65%/80% limits. Its stop/start
cleanup restored/reapplied the inhibit and the live charging pause was observed.
The full physical threshold cycle and reboot/suspend behavior remain untested.

## Existing EC SMBus transport

The working transport uses standard EC data port `0x62`, command/status port
`0x66`, EC read opcode `0x80`, and EC write opcode `0x81`. Initially the status
port returned `0x08`, with both I/O buffers empty. EC register `0xA4` reported
99%, consistent with the battery's state of charge at the time.

The mailbox layout matches the protocol implemented by the Linux
[ACPI SMBus host driver](https://github.com/torvalds/linux/blob/master/drivers/acpi/sbshc.c):

| EC offset | Purpose |
| --- | --- |
| `0x60` | Protocol / transaction trigger |
| `0x61` | Status: bit 7 complete, low 5 bits error code |
| `0x62` | SMBus address byte |
| `0x63` | Device command |
| `0x64`–`0x83` | Data, little-endian for word operations |
| `0x84` | Block count |

Protocol `0x09` requests `SMBUS_READ_WORD`; `0x08` requests `SMBUS_WRITE_WORD`.
Address byte `0x12` addresses the charger at 7-bit address `0x09`; address byte
`0x16` addresses the battery at `0x0B`. Firmware analysis showed both routed to
SMBus channel 0. The charger address byte and ChargeOption0 command happen to
both be `0x12`; they occupy different mailbox fields.

Even SMBus reads require EC writes to the mailbox parameters. The controller
limits charger writes to ChargeOption0, checks completion/error status, and
checks readback. Other charging settings are not written. Initial reads found
ChargeCurrent `0x0900` and ChargeVoltage `0x21F0`.

## Offline firmware analysis

The BIOS 0906 update package was obtained from
[Mi-Notebook-Pro-Mods](https://github.com/Cr0wTom/Mi-Notebook-Pro-Mods). It matched
the installed BIOS version; it was **not** a live SPI flash dump. Firmware and
disassembly are omitted from this repository. Obtain your own authorized copy
for independent offline inspection; installing this controller needs no image.

| Property | Value |
| --- | --- |
| Input file | `XMAKB5R0P0906.fd` |
| EC image offset in that package | `0x2991D0` |
| EC image offset from flash descriptor base | `0x200000` |
| EC image size | 131,072 bytes |
| Payload size | 97,686 bytes |
| Payload load address | `0x20100` |
| Payload byte-sum checksum | `0x646040` |

Input file SHA-256:

```text
19a01ab545c56f0a5464ed7f79a3c94cdc4b8b048d312510b6c4580f31d00855
```

Extracted EC image SHA-256:

```text
0715ce933509ecbde3b8339f3bd920bfabaa6dc1bf77603e36389cd728347f38
```

GNU binutils 2.45 built for `cr16-elf` disassembled the CompactRISC payload with
VMA `0x20100`. Relevant code locations were:

| EC code address | Observation |
| --- | --- |
| `0x293AC`–`0x29964` | Native charger updates including commands `0x12`, `0x14`, `0x15` |
| `0x2976A` onward | Internal RAM `0x1070B`, bit 0, influences native inhibition |
| `0x345C4` | EC register read handler |
| `0x34608` | EC register write handler |
| `0x3467A`–`0x34696` | Charger/battery address routing to channel 0 |
| `0x34804` onward | Mailbox protocol translated into an internal SMBus request |
| `0x34A64` onward | Returned SMBus data copied into the mailbox |

Internal EC RAM `0x1070B` is not a host physical address and was not written
directly. Live ACPI exposed ordinary battery telemetry, with no Linux charge
threshold files or newer Xiaomi MIFS interface. Their absence led to inspection
of the existing EC mailbox; no firmware flash or patch was performed.

## What the result establishes

There is a working charging inhibit/resume path on the tested machine without
firmware modification. Persistent percentage thresholds are implemented by a
Linux service that checks state and reapplies the inhibit when necessary.
This does not establish firmware-level thresholds or universal Xiaomi support.
The chip inhibit and EC SMBus protocol are documented prior art; these results
are an independent, model-specific confirmation, without a priority claim.
