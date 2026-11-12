#!/bin/bash
# Compile accel-virt dans ~/.local/opt/accel-virt, selon docs/acceleration-graphique.md (environ une heure)
set -euxo pipefail
cd ~/.local/opt/accel-virt
mkdir -p hostbin && cd hostbin
if [ ! -x widl ] || [ ! -x vulkaninfo ]; then
  d=$(mktemp -d); (cd "$d" && apt-get download mingw-w64-tools vulkan-tools && for f in *.deb; do dpkg-deb -x "$f" x; done)
  cp "$d"/x/usr/bin/*widl* . ; cp "$d"/x/usr/bin/vulkaninfo . ; ln -sf x86_64-w64-mingw32-widl widl 2>/dev/null || true; rm -rf "$d"
fi
ls -l; cd ..
tools/fetch_windows_kit.sh && python3 tools/fetch_khronos_registries.py && tools/fetch_qemu.sh
git submodule update --init --recursive third_party/dxvk third_party/vkd3d-proton
cmake -S . -B build -G Ninja -DCMAKE_CXX_COMPILER=clang++ -DCMAKE_C_COMPILER=clang
cmake --build build --target drivers && cmake --install build --prefix $PWD/build/av-drivers
cmake -S . -B build-qemu -G Ninja -DCMAKE_CXX_COMPILER=clang++ -DCMAKE_C_COMPILER=clang \
      -DCMAKE_BUILD_TYPE=Release -DAV_QEMU=ON -DAV_OPENCL_LIBRARY=/usr/lib/x86_64-linux-gnu/libOpenCL.so.1
cmake --build build-qemu --target qemu av_executor av-renderer
PATH=$PWD/hostbin:$PATH tools/build_d3d_runtime.sh
echo COMPILATION-TERMINEE
