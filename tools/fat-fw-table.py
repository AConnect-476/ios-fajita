#!/usr/bin/env python3
"""List read-only byte extents for firmware files in a FAT modem_a image.

The output offsets are relative to the start of the modem_a partition and can
be passed to the read-only sweet_ufs_read_part() interface. No image is changed.
"""
from __future__ import annotations

import argparse
import json
import math
import struct
import zlib
from pathlib import Path


class FatVolume:
    def __init__(self, path: Path):
        self.path = path
        self.fp = path.open("rb")
        b = self.fp.read(512)
        if len(b) < 512 or b[510:512] != b"\x55\xaa":
            raise ValueError("not a FAT volume boot sector")
        self.bytes_per_sector = struct.unpack_from("<H", b, 11)[0]
        self.sectors_per_cluster = b[13]
        self.reserved_sectors = struct.unpack_from("<H", b, 14)[0]
        self.fat_count = b[16]
        self.root_entries = struct.unpack_from("<H", b, 17)[0]
        total16 = struct.unpack_from("<H", b, 19)[0]
        fat16 = struct.unpack_from("<H", b, 22)[0]
        total32 = struct.unpack_from("<I", b, 32)[0]
        fat32 = struct.unpack_from("<I", b, 36)[0]
        self.total_sectors = total16 or total32
        self.fat_sectors = fat16 or fat32
        self.fat_type = 16 if fat16 else 32
        self.root_cluster = struct.unpack_from("<I", b, 44)[0] & 0x0fffffff if self.fat_type == 32 else 0
        if self.bytes_per_sector not in (512, 1024, 2048, 4096):
            raise ValueError(f"unsupported bytes/sector {self.bytes_per_sector}")
        if not self.sectors_per_cluster or self.sectors_per_cluster & (self.sectors_per_cluster - 1):
            raise ValueError("invalid sectors/cluster")
        self.root_dir_sectors = math.ceil(self.root_entries * 32 / self.bytes_per_sector)
        self.first_data_sector = self.reserved_sectors + self.fat_count * self.fat_sectors + self.root_dir_sectors
        self.cluster_bytes = self.bytes_per_sector * self.sectors_per_cluster

    def read_at(self, offset: int, size: int) -> bytes:
        self.fp.seek(offset)
        data = self.fp.read(size)
        if len(data) != size:
            raise ValueError(f"short FAT image read at {offset:#x}: {len(data)}/{size}")
        return data

    def read_sector(self, sector: int, count: int = 1) -> bytes:
        return self.read_at(sector * self.bytes_per_sector, count * self.bytes_per_sector)

    def next_cluster(self, cluster: int) -> int:
        fat_offset = cluster * (2 if self.fat_type == 16 else 4)
        raw = self.read_at(self.reserved_sectors * self.bytes_per_sector + fat_offset,
                           2 if self.fat_type == 16 else 4)
        return struct.unpack("<H" if self.fat_type == 16 else "<I", raw)[0] & (0xffff if self.fat_type == 16 else 0x0fffffff)

    def cluster_chain(self, first: int) -> list[int]:
        if first < 2:
            return []
        chain, seen = [], set()
        current = first
        eoc = 0xfff8 if self.fat_type == 16 else 0x0ffffff8
        while current >= 2 and current < eoc:
            if current in seen:
                raise ValueError(f"FAT cluster loop at {current}")
            seen.add(current)
            chain.append(current)
            nxt = self.next_cluster(current)
            if nxt >= eoc:
                break
            if nxt == 0 or nxt == (0xfff7 if self.fat_type == 16 else 0x0ffffff7):
                raise ValueError(f"invalid FAT chain at cluster {current}")
            current = nxt
            if len(chain) > self.total_sectors:
                raise ValueError("FAT chain exceeds volume size")
        return chain

    def cluster_offset(self, cluster: int) -> int:
        sector = self.first_data_sector + (cluster - 2) * self.sectors_per_cluster
        return sector * self.bytes_per_sector

    @staticmethod
    def short_name(entry: bytes) -> str:
        base = entry[0:8].decode("ascii", "replace").rstrip()
        ext = entry[8:11].decode("ascii", "replace").rstrip()
        return base + ("." + ext if ext else "")

    def directory_entries(self, first_cluster: int | None = None):
        if first_cluster is None and self.fat_type == 16:
            raw = self.read_sector(self.reserved_sectors + self.fat_count * self.fat_sectors,
                                   self.root_dir_sectors)
        else:
            cluster = self.root_cluster if first_cluster is None else first_cluster
            raw = b"".join(self.read_at(self.cluster_offset(c), self.cluster_bytes)
                           for c in self.cluster_chain(cluster))
        for off in range(0, len(raw), 32):
            e = raw[off:off + 32]
            if len(e) < 32 or e[0] == 0x00:
                break
            if e[0] == 0xe5 or e[11] == 0x0f or (e[11] & 0x08):
                continue
            name = self.short_name(e)
            if name in (".", ".."):
                continue
            hi = struct.unpack_from("<H", e, 20)[0]
            lo = struct.unpack_from("<H", e, 26)[0]
            cluster = ((hi << 16) | lo) if self.fat_type == 32 else lo
            size = struct.unpack_from("<I", e, 28)[0]
            yield {"name": name, "attr": e[11], "cluster": cluster, "size": size}

    def extents(self, first_cluster: int, size: int):
        if size == 0:
            return []
        chain = self.cluster_chain(first_cluster)
        need = math.ceil(size / self.cluster_bytes)
        if len(chain) < need:
            raise ValueError(f"file cluster chain too short: {len(chain)} < {need}")
        chain = chain[:need]
        extents = []
        remaining = size
        for cluster in chain:
            off = self.cluster_offset(cluster)
            length = min(self.cluster_bytes, remaining)
            if extents and extents[-1][0] + extents[-1][1] == off:
                extents[-1][1] += length
            else:
                extents.append([off, length])
            remaining -= length
        return extents

    def file_bytes(self, extents):
        return b"".join(self.read_at(off, length) for off, length in extents)

    def walk(self, cluster: int | None = None, prefix: str = ""):
        for entry in self.directory_entries(cluster):
            path = f"{prefix}/{entry['name']}" if prefix else entry["name"]
            if entry["attr"] & 0x10:
                yield from self.walk(entry["cluster"], path)
            else:
                yield path, entry


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("image", type=Path, help="raw modem_a partition image")
    ap.add_argument("--compare-dir", type=Path, help="compare file bytes with extracted firmware directory")
    ap.add_argument("--prefix", default="IMAGE/", help="directory prefix to include (default IMAGE/)")
    args = ap.parse_args()

    fat = FatVolume(args.image)
    output = []
    for path, entry in fat.walk():
        if args.prefix and not path.upper().startswith(args.prefix.upper()):
            continue
        extents = fat.extents(entry["cluster"], entry["size"])
        data = fat.file_bytes(extents)
        item = {
            "path": path,
            "size": entry["size"],
            "crc32": f"{zlib.crc32(data) & 0xffffffff:08x}",
            "extents": [{"offset": f"0x{off:x}", "length": f"0x{length:x}"} for off, length in extents],
            "contiguous": len(extents) <= 1,
        }
        if args.compare_dir:
            candidate = args.compare_dir / Path(path).name.lower()
            if not candidate.is_file():
                candidate = args.compare_dir / Path(path).name
            if candidate.is_file():
                local = candidate.read_bytes()
                item["matches_extracted"] = local == data
            else:
                item["matches_extracted"] = None
        output.append(item)

    print(json.dumps({
        "filesystem": f"FAT{fat.fat_type}",
        "bytes_per_sector": fat.bytes_per_sector,
        "sectors_per_cluster": fat.sectors_per_cluster,
        "partition_bytes": args.image.stat().st_size,
        "files": output,
    }, indent=2))


if __name__ == "__main__":
    main()
