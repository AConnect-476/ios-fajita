#!/usr/bin/env python3
"""Squash Qualcomm MDT + bNN firmware into the single MBN layout.

This is a small Python implementation of the BSD-3-Clause pil-squasher
algorithm (linux-msm/pil-squasher), with bounds and missing-segment checks.
It does not authenticate, modify, or flash firmware.
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path


def squash(mdt_path: Path, output_path: Path) -> tuple[int, int]:
    data = mdt_path.read_bytes()
    if len(data) < 64 or data[:4] != b"\x7fELF":
        raise ValueError(f"{mdt_path}: not an ELF MDT file")
    if data[5] != 1:
        raise ValueError(f"{mdt_path}: only little-endian MDT is supported")

    elf_class = data[4]
    if elf_class == 1:
        if len(data) < 52:
            raise ValueError("truncated ELF32 header")
        phoff = struct.unpack_from("<I", data, 28)[0]
        phentsize = struct.unpack_from("<H", data, 42)[0]
        phnum = struct.unpack_from("<H", data, 44)[0]
        min_phdr = 32
    elif elf_class == 2:
        if len(data) < 64:
            raise ValueError("truncated ELF64 header")
        phoff = struct.unpack_from("<Q", data, 32)[0]
        phentsize = struct.unpack_from("<H", data, 54)[0]
        phnum = struct.unpack_from("<H", data, 56)[0]
        min_phdr = 56
    else:
        raise ValueError(f"{mdt_path}: unsupported ELF class {elf_class}")

    if phentsize < min_phdr or phnum == 0:
        raise ValueError("invalid ELF program-header table")
    table_end = phoff + phentsize * phnum
    if table_end > len(data):
        raise ValueError("program-header table extends beyond MDT")

    # Qualcomm MDTs store hash segments directly after the first segment's
    # declared file data; normal loadable segments live in sibling .bNN files.
    first_phdr = data[phoff:phoff + phentsize]
    if elf_class == 1:
        hash_offset = struct.unpack_from("<I", first_phdr, 16)[0]
    else:
        hash_offset = struct.unpack_from("<Q", first_phdr, 32)[0]

    out_size = table_end
    segments: list[tuple[int, int, int, int]] = []
    for index in range(phnum):
        off = phoff + index * phentsize
        phdr = data[off:off + phentsize]
        if elf_class == 1:
            p_offset = struct.unpack_from("<I", phdr, 4)[0]
            p_filesz = struct.unpack_from("<I", phdr, 16)[0]
            p_flags = struct.unpack_from("<I", phdr, 24)[0]
        else:
            p_flags = struct.unpack_from("<I", phdr, 4)[0]
            p_offset = struct.unpack_from("<Q", phdr, 8)[0]
            p_filesz = struct.unpack_from("<Q", phdr, 32)[0]
        if not p_filesz:
            continue
        if p_offset + p_filesz > 0x1000000000:
            raise ValueError(f"segment {index}: unreasonable output offset")
        is_hash = ((p_flags >> 24) & 7) == 2
        if is_hash:
            if hash_offset + p_filesz > len(data):
                raise ValueError(f"segment {index}: hash chunk exceeds MDT")
            source = data[hash_offset:hash_offset + p_filesz]
            hash_offset += p_filesz
        else:
            segment_path = mdt_path.with_suffix(f".b{index:02d}")
            if not segment_path.is_file():
                raise FileNotFoundError(f"missing segment {segment_path}")
            segment_data = segment_path.read_bytes()
            if len(segment_data) < p_filesz:
                raise ValueError(
                    f"{segment_path}: {len(segment_data)} bytes, expected {p_filesz}"
                )
            source = segment_data[:p_filesz]
        segments.append((index, p_offset, p_filesz, source))
        out_size = max(out_size, p_offset + p_filesz)

    output = bytearray(out_size)
    output[:table_end] = data[:table_end]
    total = 0
    for index, p_offset, p_filesz, source in segments:
        output[p_offset:p_offset + p_filesz] = source
        total += p_filesz
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(output)
    return len(segments), total


def inspect_segments(mdt_path: Path) -> None:
    data = mdt_path.read_bytes()
    if len(data) < 64 or data[:4] != b"\x7fELF" or data[5] != 1:
        raise ValueError(f"{mdt_path}: unsupported MDT ELF header")
    elf_class = data[4]
    if elf_class == 1:
        phoff = struct.unpack_from("<I", data, 28)[0]
        phentsize = struct.unpack_from("<H", data, 42)[0]
        phnum = struct.unpack_from("<H", data, 44)[0]
    elif elf_class == 2:
        phoff = struct.unpack_from("<Q", data, 32)[0]
        phentsize = struct.unpack_from("<H", data, 54)[0]
        phnum = struct.unpack_from("<H", data, 56)[0]
    else:
        raise ValueError(f"unsupported ELF class {elf_class}")
    print(f"{mdt_path}: ELF{32 if elf_class == 1 else 64}, {phnum} program headers")
    print("idx type flags       paddr        filesz      memsz       source")
    for index in range(phnum):
        off = phoff + index * phentsize
        if elf_class == 1:
            p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_flags, p_align = struct.unpack_from("<8I", data, off)
        else:
            p_type, p_flags, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_align = struct.unpack_from("<IIQQQQQQ", data, off)
        if not p_filesz:
            source = "-"
        elif ((p_flags >> 24) & 7) == 2:
            source = "MDT hash data"
        else:
            source = f".b{index:02d}"
        print(f"{index:3d} {p_type:4d} {p_flags:08x} {p_paddr:08x} {p_filesz:10d} {p_memsz:10d} {source}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mdt", type=Path, help="input firmware .mdt")
    parser.add_argument("-o", "--output", type=Path, help="output .mbn (default: sibling .mbn)")
    parser.add_argument("--list", action="store_true", help="list ELF program headers and their .bNN source files")
    args = parser.parse_args()
    if args.list:
        inspect_segments(args.mdt)
        return
    output = args.output or args.mdt.with_suffix(".mbn")
    count, total = squash(args.mdt, output)
    print(f"{args.mdt}: {count} segments, {total} bytes -> {output} ({output.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
