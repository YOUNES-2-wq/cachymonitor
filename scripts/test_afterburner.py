#!/usr/bin/env python3
"""Diagnostic : liste tous les capteurs exposes par MSI Afterburner (MAHMSharedMemory)."""
import ctypes
import struct

FILE_MAP_READ = 0x0004
k32 = ctypes.windll.kernel32
k32.OpenFileMappingW.restype = ctypes.c_void_p
k32.OpenFileMappingW.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_wchar_p]
k32.MapViewOfFile.restype = ctypes.c_void_p
k32.MapViewOfFile.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                              ctypes.c_uint32, ctypes.c_size_t]
k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
k32.CloseHandle.argtypes = [ctypes.c_void_p]

h = None
for name in ("MAHMSharedMemory", "Global\\MAHMSharedMemory"):
    h = k32.OpenFileMappingW(FILE_MAP_READ, False, name)
    if h:
        print("Memoire trouvee :", name)
        break
if not h:
    print("ECHEC : memoire partagee Afterburner introuvable.")
    print("-> Dans Afterburner : Settings > Monitoring, coche 'Enable hardware polling'")
    raise SystemExit(1)

ptr = k32.MapViewOfFile(h, FILE_MAP_READ, 0, 0, 32)
hdr = bytes(ctypes.string_at(ptr, 32))
k32.UnmapViewOfFile(ptr)

sig, ver, hdr_sz, n_entries, entry_sz = struct.unpack_from("<IIIII", hdr, 0)
print(f"sig=0x{sig:08X} ('{struct.pack('<I', sig).decode('ascii', 'replace')}')  "
      f"version=0x{ver:08X}")
print(f"header_size={hdr_sz}  entries={n_entries}  entry_size={entry_sz}")

total = hdr_sz + n_entries * entry_sz
ptr = k32.MapViewOfFile(h, FILE_MAP_READ, 0, 0, total)
data = bytes(ctypes.string_at(ptr, total))
k32.UnmapViewOfFile(ptr)
k32.CloseHandle(h)

print()
print(f"{'#':>3}  {'capteur':<34} {'valeur':>12}  unite")
print("-" * 70)
for i in range(n_entries):
    base = hdr_sz + i * entry_sz
    src_name = data[base:base + 260].split(b"\0")[0].decode("latin-1")
    units = data[base + 260:base + 520].split(b"\0")[0].decode("latin-1")
    val = struct.unpack_from("<f", data, base + 260 * 5)[0]
    print(f"{i:>3}  {src_name:<34} {val:>12.2f}  {units}")
