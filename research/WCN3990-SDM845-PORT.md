# WCN3990 / SDM845 Wi-Fi port notes (OnePlus 6T)

Status: hardware discovery and firmware inventory completed. The read-only WCN3990/GLINK/ADSP probe and the later modem-Q6 metadata probe both passed XNU CI. The read-only modem_a UFS reader and firmware-header checks are in the next CI build. No modem or Wi-Fi hardware has been started.

This document is specific to `fajita` (OnePlus 6T, SDM845). Do not apply the `ios-topaz` Wi-Fi patches unchanged: that port targets SM6225 and its hard-coded modem/WLAN memory layout does not match this device.

## Hardware verified on the phone

The connected handset was in OrangeFox recovery. Its live device tree exposes `qcom,icnss@18800000`:

- WCN3990/SNoC register window: `0x18800000`, size `0x00800000`.
- Twelve CE interrupts: GIC SPIs 414 through 425.
- IOMMU stream ID: `0x40`.
- WLAN firmware reserved region: `0x8df00000`, size `0x00100000`.
- Separate live `qcom,wlan-msa-memory` property: `0x1000` (4096); this is not the reserved-region address/size.
- The WLAN node is `qcom,icnss` in the downstream live DT.
- The live ICNSS node includes `qcom,smmu-s1-bypass`; the generated Apple DT carries that flag, the two available regulator voltage configurations and the OnePlus calibration/host-quirk metadata.
- The live ICNSS node has no separate `wcn3990-pmu` child. It references regulator supplies for 0.8 V CX/MX, 1.8 V XO, 1.3 V RFA and 3.3 V channel 0; its live `qcom,vdd-0.8-cx-mx-config` is 800000/800000 µV and `qcom,vdd-3.3-ch0-config` is 3104000/3312000 µV. Do not invent a PMU switch GPIO.
- Shared SMEM region: `0x86000000`, size `0x00200000`.
- Modem reserved region: `0x8e000000`, size `0x07800000`.
- MBA reserved region: `0x96600000`, size `0x00200000` (downstream live DT).
- ADSP reserved region: `0x8c500000`, size `0x01a00000`.
- Modem GLINK transport uses the same SMEM region plus IRQ register `0x1799000c` (4 bytes), doorbell mask `0x00100000`, GIC SPI 449.
- SMP2P uses register `0x1799000c` (4 bytes), GIC SPI 451, remote PID 1 and IRQ bitmask `0x4`.
- The live modem node has `qcom,pil-self-auth`, `qcom,qdsp6v65-1-0`, `qcom,mem-protect-id = 15`, `qcom,signal-aop`, `qcom,mss_pdc_offset = 9`, and `qcom,ssctl-instance-id = 18`. It has no `qcom,pas-id` property. This is the MBA self-auth path, not the direct PAS-ID-4 path used by Topaz; do not copy Topaz's modem boot sequence.
- Live modem clocks: `clock-names = xo, iface_clk, bus_clk, mem_clk, gpll0_mss_clk, snoc_axi_clk, mnoc_axi_clk, prng_clk`; active clocks are `iface_clk, bus_clk, mem_clk, gpll0_mss_clk, snoc_axi_clk, mnoc_axi_clk`; proxy clocks are `xo, prng_clk`.
- Live `vdd_cx-voltage`, `vdd_mx-uV` and `vdd_mss-uV` properties each contain the raw value `385`. The Linux driver passes these to regulator APIs as voltage values, but that raw value is unusual; do not translate or vote these rails until the units/provider behavior are verified.
- QDSP6 v65 boot-FSM registers from the Android 11 downstream driver: Q6 sleep `q6_base + 0x3c`, boot-core-start `q6_base + 0x400`, boot command `q6_base + 0x404`, and MBA status `rmb_base + 0x40`.
- The ADSP PAS ID is 1 in the SDM845 PAS driver; the live modem node does not expose a modem PAS ID.

The upstream SDM845 DTS agrees on the `0x8e000000` modem and `0x96600000` MBA carveouts. The live downstream DTS is authoritative where it differs.

The existing `tools/build-fajita.sh` always invokes `mkadt.py --highmem`. That sets XNU's managed DRAM base to `0x100000000`; the modem/ADSP/SMEM/WLAN carveouts below `0xac800000` stay outside the XNU allocator. Do not remove `--highmem` unless the memory map is redesigned, or the kernel could allocate over coprocessor memory. The driver will still need explicit mappings for those reserved low-memory ranges.

## Device-extracted firmware inventory

The live phone mounts `/firmware` from `/dev/block/bootdevice/by-name/modem_a`, which resolves to UFS LUN 4, partition 4. The partition is FAT16 (4096 bytes/sector, 4 sectors/cluster), 125,829,120 bytes. The existing local `modem_a.img` backup SHA-256 is `6d24067dee5778ee9fefe7c8880f4241e9efc6432feaeafece5cb47a77d85921`. A read-only FAT scanner found 403 files; 53 modem/ADSP/WLAN/PD-descriptor entries are recorded in `research/fajita-modem-a-extents.json`. Every extracted firmware file and descriptor, including `ADSPUA.JSN`, now byte-matches its entry in the backup. All 53 selected files are contiguous, so the XNU loader can read them by a single partition-relative offset and size without mounting or writing FAT.


Read-only mounted `vendor_a` and the `/firmware` partition in recovery. Copied the following into the local, untracked directory `fajita-wifi-modem-fw/` (not committed to Git):

- `wlanmdsp.mbn` — SHA-256 `0f81800262f534dc9ef7e9d28232ce3e9619d8424f8e4747d818cabbe03dc63a`
- `bdwlan.bin` — SHA-256 `a46790bc201026e8f38a19f3acd749640b54b73d14e09287659a647b9cc3ee8e`
- `modem.mdt`, `modem.b00`–`modem.b28` (present segments), `mba.mbn`
- `adsp.mdt`, `adsp.b00`–`adsp.b13`
- PD descriptor JSON files: `adspr.jsn`, `adspua.jsn` (pulled separately), `modemr.jsn`, `modemuw.jsn`, `cdspr.jsn`, `slpir.jsn`, `slpius.jsn`

No `msadp` debug-policy image is present in this partition. The downstream MBA loader treats that image as optional, so this device must use the no-MSADP path rather than inventing a companion image.

The extracted `wlanmdsp.mbn` reports firmware build `WLAN.HL.2.0.c8-00050-QCAHLSWMTPLZ-1.435283.1.441421.1`. The `bdwlan.bin` hash is recorded above; its exact board-2 entry still needs to be matched. A generic upstream WCN3990 `firmware-5.bin` is only 60 bytes and belongs to the upstream `WLAN.HL.2.0-01387` firmware set; do not assume it is a matching companion to this OnePlus c8-00050 image without checking the protocol and feature compatibility.

The firmware archive copied from recovery is `fajita-wifi-modem.tar` (SHA-256 `f2f7f00cc32acbf3cbe805cb6a2ffa5634384a4b1142300c2ca4667cabe7775c`). Firmware binaries are intentionally excluded from this repository.

`tools/pil-squash.py --list` confirms the MDT layouts are ELF32: modem has 30 program headers and ADSP has 15. The modem's loadable segments occupy `0x8e000000` through below `0x9581d000`, inside the `0x8e000000..0x96600000` modem carveout. ADSP loadable segments occupy `0x8c500000..0x8df00000`, exactly filling its carveout; its special hash segment points at `0x8df00000`, the adjacent WLAN firmware region, so the PIL loader must treat that segment as hash metadata rather than blindly copy it as ordinary payload.

The new `tools/pil-squash.py` helper was run against the extracted device firmware and successfully assembled:

- `modem.mbn`: 27 program segments, 60,346,576 bytes; SHA-256 `a1672ad7eb74bedc5452fef25fd2c8f8809f095e138346dc762e868819ce6b90`.
- `adsp.mbn`: 14 program segments, 11,128,744 bytes; SHA-256 `8341775842bfb5593b5b75127d6a02f36afc173f50d17a1313bb86d1a0e50362`.

These merged images remain local under `fajita-wifi-modem-fw/`; no proprietary firmware binaries are committed.

## Why Topaz patches are not directly portable

The SM6225 Topaz implementation hard-codes a different memory map, including modem pool `0xE0000000`, SMEM `0x46000000`, WLAN `0x0C800000`, SMMU `0x0C600000`, and WLAN MSA `0x51900000`. Those conflict with the live SDM845/fajita map above. Its PAS ID (4), SMP2P/GLINK values and modem memory carveout cannot be copied without validation.

The Topaz patch series is still useful as a protocol reference for PAS, SMEM/SMP2P, GLINK/QRTR, PD services, WLFW, CE, HTC/WMI/HTT, scanning and WPA2. Each hardware-specific assumption must be replaced with fajita values and checked against the live DT and this phone's firmware.

## Live modem control metadata

The live `qcom,mss@4080000` node identifies `qcom,pil-q6v55-mss`, firmware stem `modem`, `qcom,mem-protect-id = 15`, `qcom,pil-self-auth`, `qcom,mss_pdc_offset = 9`, and `qcom,ssctl-instance-id = 18`. This is not Topaz's PAS ID 4. The GLINK modem transport uses SMEM `0x86000000/0x200000`, IRQ register `0x1799000c`, mask `0x1000`, SPI 449. The separate SMP2P modem node uses the same register, remote PID 1, IRQ bitmask `0x4000`, SPI 451. These were read from the phone's live device tree.

## Implementation order

1. **Implemented on this branch:** `tools/mkadt.py` adds WCN3990, modem-transport, modem-Q6 and ADSP metadata from the live fajita DT. Patch `0215-fajita-wcn3990-readonly-probe.patch` adds an XNU probe that only reads those ADT properties; it does not map MMIO or touch hardware.
2. **Implemented on this branch:** patch `0216-fajita-ufs-readonly-modem-partition.patch` adds a read-only `modem_a` reader on its verified UFS LUN 4, reusing the existing `ufs_partition_extent()` helper without changing root-LUN geometry. I checked the corrected patch with `git apply --check` against the actual `sweet_ufs.c` extracted from the preceding XNU CI build tree. Patch 0215 reads the first four bytes of `modem.mdt`, `mba.mbn`, `adsp.mdt`, `wlanmdsp.mbn` and `bdwlan.bin` from verified offsets; this validates firmware access without loading or starting a coprocessor. Both patches pass the local hunk-count check; the latest CI build is compiling the corrected UFS reader and firmware-header checks.
3. Use the verified partition-relative extents in `research/fajita-modem-a-extents.json` to read the complete `mba.mbn`, `modem.mdt`, `modem.bNN`, `adsp.mdt`, `adsp.bNN`, WLAN firmware and PD descriptors.
3. Implement the OnePlus MBA self-auth modem boot path: MBA firmware load, Q6/RMB handshake, memory assignment to VMID 15, AOP signalling and the Q6 reset sequence. Do not use Topaz's direct PAS-ID-4 flow.
4. Bring up ADSP and modem service registration, then implement SMEM, SMP2P, GLINK and QRTR using the live SDM845 IRQ register/mask and handshakes.
5. Start the required host services using this device's `.jsn` descriptors and verify the `wlan_pd` service is published.
6. Implement WCN3990 WLFW QMI, MSA permission handoff and OnePlus board data upload.
7. Implement SNoC copy engines and HTC/WMI/HTT using the WCN3990 CE layout.
8. Reach passive scan first, then station association and WPA2.
9. Add the iOS network interface and `wifid` integration only after the data path is stable.

A relevant OnePlus 6/6T Linux bring-up report documents the dependency chain: device-matched modem firmware, split MDT loading, correct PD descriptors, ADSP/servreg before pd-mapper, and modem/ADSP/pd-mapper before WLAN probe: https://bugs.kali.org/view.php?id=9780. The downstream Q6/MBA loader reference is https://github.com/crdroidandroid/android_kernel_oneplus_sdm845/tree/15.0/drivers/soc/qcom.

## Build result

- XNU run `42993235306` succeeded with the WCN3990 probe patch applied.
- Shim run `42995461853` succeeded and produced `shim-boot.img`.
- Image size: `20,545,536` bytes (about 19.6 MiB), below the 64 MiB `boot_a` backup size.
- SHA-256: `a651588025ecbd5c202c5145e5087aab63b1490e389efdf1f8ccf9960cdd831b`.
- The image has Android boot-image magic and header version 1, and includes the stock `fajita2.dtb`.
- This is a diagnostic boot image only. The payload uses a 1 MiB zeroed GPU arena and omits GMU/SQE/ZAP firmware, so GPU acceleration is not ready. It also has no iOS rootfs on the phone, and the WCN probe only logs ADT properties: Wi-Fi is **not yet functional**.

## Safety boundary

No phone partitions were written during this discovery. `vendor_a` was mounted read-only with `noload`; the `/firmware` partition was already read-only in recovery. No slot change, flash, format or wipe was performed. Keep the working Android slot and all calibration/EFS partitions untouched.
