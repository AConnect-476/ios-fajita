# WCN3990 / SDM845 Wi-Fi port notes (OnePlus 6T)

Status: hardware discovery and firmware inventory completed. A read-only ADT probe and ADT metadata node are committed on this branch; XNU CI is validating the patch. No modem or Wi-Fi hardware has been started.

This document is specific to `fajita` (OnePlus 6T, SDM845). Do not apply the `ios-topaz` Wi-Fi patches unchanged: that port targets SM6225 and its hard-coded modem/WLAN memory layout does not match this device.

## Hardware verified on the phone

The connected handset was in OrangeFox recovery. Its live device tree exposes `qcom,icnss@18800000`:

- WCN3990/SNoC register window: `0x18800000`, size `0x00800000`.
- Twelve CE interrupts: GIC SPIs 414 through 425.
- IOMMU stream ID: `0x40`.
- WLAN firmware reserved region: `0x8df00000`, size `0x00100000`.
- Separate live `qcom,wlan-msa-memory` property: `0x1000` (4096); this is not the reserved-region address/size.
- The WLAN node is `qcom,icnss` in the downstream live DT (not the upstream `qcom,wcn3990-wifi` compatible).
- The OnePlus DTS sets `qcom,calibration-variant = "oneplus_sdm845"` and the `qcom,snoc-host-cap-8bit-quirk` flag. Both are represented in the generated Apple DT.
- PMU node: `wcn3990-pmu`; its switch-control line is PM8998 GPIO3. The OnePlus common DTS supplies 0.8 V CX/MX, 1.8 V XO, 1.3 V RF, and two 3.3 V channel rails.
- Shared SMEM region: `0x86000000`, size `0x00200000`.
- Modem reserved region: `0x8e000000`, size `0x07800000`.
- MBA reserved region: `0x96600000`, size `0x00200000` (downstream live DT).
- ADSP reserved region: `0x8c500000`, size `0x01a00000`.
- Modem GLINK transport uses the same SMEM region plus IRQ register `0x1799000c` (4 bytes), doorbell mask `0x00100000`, GIC SPI 449.
- SMP2P uses register `0x1799000c` (4 bytes), GIC SPI 451, remote PID 1 and IRQ bitmask `0x4`.
- The ADSP PAS ID is 1 in the SDM845 PAS driver. The live modem node has no `qcom,pas-id` property, so the modem PAS ID must be confirmed from the exact downstream loader rather than copied from Topaz.

The upstream SDM845 DTS instead describes the modem/MBA reserved regions as `0x8e000000` / `0x96500000`; use the live fajita DT for final addresses. The live downstream DTS must win over generic upstream defaults.

## Device-extracted firmware inventory

Read-only mounted `vendor_a` and the `/firmware` partition in recovery. Copied the following into the local, untracked directory `fajita-wifi-modem-fw/` (not committed to Git):

- `wlanmdsp.mbn` — SHA-256 `0f81800262f534dc9ef7e9d28232ce3e9619d8424f8e4747d818cabbe03dc63a`
- `bdwlan.bin` — SHA-256 `a46790bc201026e8f38a19f3acd749640b54b73d14e09287659a647b9cc3ee8e`
- `modem.mdt`, `modem.b00`–`modem.b28` (present segments), `mba.mbn`
- `adsp.mdt`, `adsp.b00`–`adsp.b13`
- PD descriptor JSON files: `adspr.jsn`, `modemr.jsn`, `modemuw.jsn`, `cdspr.jsn`, `slpir.jsn`, `slpius.jsn`

The extracted `wlanmdsp.mbn` reports firmware build `WLAN.HL.2.0.c8-00050-QCAHLSWMTPLZ-1.435283.1.441421.1`. The `bdwlan.bin` hash is recorded above; its exact board-2 entry still needs to be matched. A generic upstream WCN3990 `firmware-5.bin` is only 60 bytes and belongs to the upstream `WLAN.HL.2.0-01387` firmware set; do not assume it is a matching companion to this OnePlus c8-00050 image without checking the protocol and feature compatibility.

The firmware archive copied from recovery is `fajita-wifi-modem.tar` (SHA-256 `f2f7f00cc32acbf3cbe805cb6a2ffa5634384a4b1142300c2ca4667cabe7775c`). Firmware binaries are intentionally excluded from this repository.

The new `tools/pil-squash.py` helper was run against the extracted device firmware and successfully assembled:

- `modem.mbn`: 27 program segments, 60,346,576 bytes; SHA-256 `a1672ad7eb74bedc5452fef25fd2c8f8809f095e138346dc762e868819ce6b90`.
- `adsp.mbn`: 14 program segments, 11,128,744 bytes; SHA-256 `8341775842bfb5593b5b75127d6a02f36afc173f50d17a1313bb86d1a0e50362`.

These merged images remain local under `fajita-wifi-modem-fw/`; no proprietary firmware binaries are committed.

## Why Topaz patches are not directly portable

The SM6225 Topaz implementation hard-codes a different memory map, including modem pool `0xE0000000`, SMEM `0x46000000`, WLAN `0x0C800000`, SMMU `0x0C600000`, and WLAN MSA `0x51900000`. Those conflict with the live SDM845/fajita map above. Its PAS image extents, modem memory carveout, SMP2P and GLINK assumptions also cannot be copied without validation.

The Topaz patch series is still useful as a protocol reference for PAS, SMEM/SMP2P, GLINK/QRTR, PD services, WLFW, CE, HTC/WMI/HTT, scanning and WPA2. Each hardware-specific assumption must be replaced with fajita values and checked against the live DT and this phone's firmware.

## Implementation order

1. **Implemented on this branch:** `tools/mkadt.py` now adds WCN3990, WLAN firmware-region/MSA-size, modem-transport and ADSP metadata from the live fajita DT. Patch `0215-fajita-wcn3990-readonly-probe.patch` adds an XNU probe that only reads those ADT properties; it does not map MMIO or touch hardware. The hunk-count check passes locally; the corrected patch is awaiting XNU CI.
2. Implement SDM845 modem and ADSP PAS startup using the actual reserved-memory carveouts, device-specific `.mdt`/`.bNN` firmware and TrustZone SCM ABI. The live modem DT does not expose a PAS ID; do not assume the Topaz value.
3. Implement SMEM, SMP2P, GLINK and QRTR using the live SDM845 IRQ register/mask and handshakes.
4. Start ADSP and modem before PD mapping. Use the device's own `.jsn` descriptors and verify the `wlan_pd` service is published.
5. Implement WCN3990 WLFW QMI, MSA permission handoff and OnePlus board data upload.
6. Implement SNoC copy engines and HTC/WMI/HTT using the WCN3990 CE layout.
7. Reach passive scan first, then station association and WPA2.
8. Add the iOS network interface and `wifid` integration only after the data path is stable.

A relevant OnePlus 6/6T Linux bring-up report documents the same dependency chain: device-matched modem firmware, split MDT squashing, correct PD descriptors, ADSP/servreg before pd-mapper, and modem/ADSP/pd-mapper before the WLAN driver probes: https://bugs.kali.org/view.php?id=9780.

## Safety boundary

No phone partitions were written during this discovery. `vendor_a` was mounted read-only with `noload`; the `/firmware` partition was already read-only in recovery. No slot change, flash, format or wipe was performed. Keep the working Android slot and all calibration/EFS partitions untouched.
