#!/usr/bin/env bash
# Cross-compile btop4win (Release-LHM x64) on Linux with clang-cl + lld-link against an xwin-splatted MSVC CRT/SDK.
# Mirrors btop4win.vcxproj: /std:c++latest, /MT, LHM_Enabled, UNICODE, console subsystem, requireAdministrator manifest.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")" && pwd)
XWIN=${XWIN:-$HOME/src/xwin-sdk}
OUT=$ROOT/build
mkdir -p "$OUT/caseshim" "$OUT/libshim"

#? The SDK is case-sensitive on Linux: link the spellings btop4win's #include/#pragma comment lines use
ln -sf "$XWIN/sdk/include/um/WbemIdl.h" "$OUT/caseshim/Wbemidl.h"
for pair in Advapi32:advapi32 Pdh:pdh Ws2_32:ws2_32 PowrProf:powrprof; do
  ln -sf "$XWIN/sdk/lib/um/x86_64/${pair#*:}.lib" "$OUT/libshim/${pair%%:*}.lib"
done

#? Import library for LibreHardwareMonitor's CPPdll.dll (not shipped in the btop4win repo), from its two exports
[ -f "$ROOT/external/CPPdll.lib" ] || llvm-lib-21 /def:"$ROOT/external/CPPdll.def" /machine:x64 /out:"$ROOT/external/CPPdll.lib"
ln -sf "$ROOT/external/CPPdll.lib" "$OUT/libshim/external\\CPPdll.lib"   # btop_collect.cpp: #pragma comment(lib, "external\\CPPdll.lib")

INC=(/imsvc "$XWIN/crt/include" /imsvc "$XWIN/sdk/include/ucrt" /imsvc "$XWIN/sdk/include/um" /imsvc "$XWIN/sdk/include/shared")
LIBP=(/libpath:"$XWIN/crt/lib/x86_64" /libpath:"$XWIN/sdk/lib/um/x86_64" /libpath:"$XWIN/sdk/lib/ucrt/x86_64" /libpath:"$ROOT" /libpath:"$OUT/libshim")
CFLAGS=(--target=x86_64-pc-windows-msvc /nologo /std:c++latest /EHsc /MT /O2 /DNDEBUG /DLHM_Enabled /D_UNICODE /DUNICODE
        /utf-8 -fms-compatibility-version=19.40 -Wno-everything "${INC[@]}" /I"$ROOT/src" /I"$ROOT/include" /I"$OUT/caseshim")

pids=()
for f in btop btop_collect btop_config btop_draw btop_input btop_menu btop_theme btop_tools; do
  clang-cl "${CFLAGS[@]}" /c "$ROOT/src/$f.cpp" /Fo"$OUT/$f.obj" &
  pids+=($!)
done
for p in "${pids[@]}"; do wait "$p"; done

sed 's|\\\\|/|g' "$ROOT/btop4win.rc" > "$OUT/btop4win.rc"   # Windows paths in the .rc -> forward slashes
llvm-rc-21 /nologo /I "$ROOT" "${INC[@]/\/imsvc/\/I}" /fo "$OUT/btop4win.res" "$OUT/btop4win.rc" 2>&1 | grep -v nonportable-include-path || true

lld-link /nologo /machine:x64 /subsystem:console /out:"$OUT/btop.exe" "${LIBP[@]}" \
  "$OUT"/*.obj "$OUT/btop4win.res" psapi.lib \
  /manifest:embed /manifestuac:"level='requireAdministrator' uiAccess='false'"
ls -la "$OUT/btop.exe"
