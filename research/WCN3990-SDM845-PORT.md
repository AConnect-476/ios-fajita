# WCN3990 / SDM845 Wi-Fi port notes (OnePlus 6T)

Status: hardware discovery and firmware inventory completed; XNU driver not yet implemented.

This document is specific to `fajita` (OnePlus 6T, SDM845). Do not apply the `ios-topaz` Wi-Fi patches unchanged: that port targets SM6225 and its hard-coded modem/WLAN memory layout does not match this device.

## Hardware verified on the phone

The connected handset was in OrangeFox recovery. Its live device tree exposes `qcom,icnss@18800000`:

- WCN3990/SNoC register window: `0x18800000`, size `0x00800000`.
- Twelve CE interrupts: GIC SPIs 414 through 425.
- IOMMU stream ID: `0x40`.
- WLAN firmware/MSA reserved memory: `0x8df00000`, size `0x00100000`.
- The WLAN node is `qcom,icnss` in the downstream live DT (not the upstream `qcom,wcn3990-wifi` compatible).
- PMU node: `wcn3990-pmu`; its switch-control line is PM8998 GPIO3. The OnePlus common DTS supplies 0.8 V CX/MX, 1.8 V XO, 1.3 V RF, and two 3.3 V channel rails.
- Shared SMEM region: `0x86000000`, size `0x00200000`.
- Modem reserved region: `0x8e000000`, size `0x07800000`.
- MBA reserved region: `0x96600000`, size `0x00200000` (downstream live DT).

The upstream SDM845 DTS instead describes the modem/MBA reserved regions as `0x8e000000` / `0x96500000`; use the live fajita DT for final addresses. The live downstream DTS must win over generic upstream defaults.

## Device-extracted firmware inventory

Read-only mounted `vendor_a` and the `/firmware` partition in recovery. Copied the following into the local, untracked directory `fajita-wifi-modem-fw/` (not committed to Git):

- `wlanmdsp.mbn` — SHA-256 `0f81800262f534dc9ef7e9d28232ce3e9619d8424f8e4747d818cabbe03dc63a`
- `bdwlan.bin` — SHA-256 `a46790bc201026e8f38a19f3acd749640b54b73d14e09287659a647b9cc3ee8e`
- `modem.mdt`, `modem.b00`–`modem.b28` (present segments), `mba.mbn`
- `adsp.mdt`, `adsp.b00`–`adsp.b13`
- PD descriptor JSON files: `adspr.jsn`, `modemr.jsn`, `modemuw.jsn`, `cdspr.jsn`, `slpir.jsn`, `slpius.jsn`

The `bdwlan.bin` SHA-256 exactly matches the OnePlus 6/6T WCN3990 board entry published upstream. The extracted `wlanmdsp.mbn` reports firmware build `WLAN.HL.2.0.c8-00050-QCAHLSWMTPLZ-1.435283.1.441421.1`. Do not assume a generic WCN3990 `firmware-5.bin` is compatible until its WLAN.HL version/features are checked against this image.

The firmware archive copied from recovery is `fajita-wifi-modem.tar` (SHA-256 `f2f7f00cc32acbf3cbe805cb6a2ffa5634384a4b1142300c2ca4667cabe7775c`). Firmware binaries are intentionally excluded from this repository.

## Why Topaz patches are not directly portable

The SM6225 Topaz implementation hard-codes a different memory map, including modem pool `0xE0000000`, SMEM `0x46000000`, WLAN `0x0C800000`, SMMU `0x0C600000`, and WLAN MSA `0x51900000`. Those conflict with the live SDM845/fajita map above. Its PAS image extents, modem memory carveout, SMP2P and GLINK assumptions also cannot be copied without validation.

The Topaz patch series is still useful as a protocol reference for PAS, SMEM/SMP2P, GLINK/QRTR, PD services, WLFW, CE, HTC/WMI/HTT, scanning and WPA2. Each hardware-specific assumption must be replaced with fajita values and checked against the live DT and this phone's firmware.

## Implementation order

1. Add a read-only XNU discovery/probe for the live ADT nodes, reserved-memory regions, ICNSS register window and interrupts. No register writes during this stage.
2. Implement SDM845 modem PAS startup using the actual live memory carveouts, firmware format and TrustZone SCM ABI. Keep modem EFS/rmtfs access read-only; never write modemst/fsg/fsc/persist.
3. Implement SMEM, SMP2P, GLINK and QRTR with SDM845 addresses and handshakes.
4. Bring up PD mapping/TFTP/rmtfs host services and verify the WLAN PD is available.
5. Implement WCN3990 WLFW QMI, MSA permission handoff and OnePlus board data upload.
6. Implement SNoC copy engines and HTC/WMI/HTT using the WCN3990 CE layout.
7. Reach passive scan first, then station association and WPA2.
8. Add the iOS network interface and `wifid` integration only after the data path is stable.

## Safety boundary

No phone partitions were written during this discovery. `vendor_a` was mounted read-only with `noload`; the `/firmware` partition was already read-only in recovery. No slot change, flash, format or wipe was performed. Keep the working Android slot and all calibration/EFS partitions untouched.
