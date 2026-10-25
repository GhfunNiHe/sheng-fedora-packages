%undefine        _debugsource_packages
# No debuginfo subpackage, matching the --nodebuginfo that the CI builds pass:
# Copr has no way to pass extra rpmbuild options, so the spec has to say it.
%global debug_package %{nil}
%global KERNEL_VER 7.3.0
%global KERNEL_TAG 7.3.0
%global KERNEL_RPMVER 7.3.0
%global DEVICE_NAME sheng
%global PLATFORM_NAME sm8550

Version:         %{KERNEL_RPMVER}
Release:         1.%{DEVICE_NAME}%{?dist}
ExclusiveArch:  aarch64
Name:            kernel-%{PLATFORM_NAME}
Summary:         Mainline Linux kernel for %{PLATFORM_NAME} devices (U-Boot boot)
License:         GPL-2.0-only
URL:             https://github.com/ianchb/sm8550-mainline

Source0:         %{url}/archive/%{KERNEL_TAG}.tar.gz
Source1:         https://github.com/ianchb/sm8550-mainline/releases/download/%{KERNEL_VER}/sm8550.config
Source2:         extra-sm8550.config

BuildRequires:   bc bison dwarves diffutils elfutils-devel findutils git-core hmaccalc hostname make openssl-devel perl-interpreter rsync tar which flex bzip2 xz zstd python3 python3-devel python3-pyyaml rust rust-src bindgen rustfmt clippy opencsd-devel net-tools
BuildRequires:   clang lld llvm ccache

Provides:        kernel               = %{version}-%{release}
Provides:        kernel-core          = %{version}-%{release}
Provides:        kernel-modules       = %{version}-%{release}
Provides:        kernel-modules-core  = %{version}-%{release}

%description
Mainline kernel for %{PLATFORM_NAME}, packaged for the sheng device booted via
U-Boot. U-Boot's sysboot reads /extlinux/extlinux.conf off the ESP and loads
the uncompressed arm64 Image (shipped as /boot/vmlinuz-<ver>) with booti, so a
kernel update is delivered by dnf without re-flashing a boot image. Built from
source archive with commit hash resolved from the upstream tag
(e.g. %{KERNEL_VER}-%{PLATFORM_NAME}-gXXXXXXXXX).

%prep
%setup -q -n sm8550-mainline-%{KERNEL_TAG}

# Resolve tag to commit hash without full clone
COMMIT_HASH=$(git ls-remote %{url}.git refs/tags/%{KERNEL_TAG} | awk '{print $1}' | cut -c1-7)
echo "Tag %{KERNEL_TAG} commit: ${COMMIT_HASH}"
LOCALVERSION_FULL="-%{PLATFORM_NAME}-g${COMMIT_HASH}"
echo "${LOCALVERSION_FULL}" > .lkv_suffix

cp %{SOURCE1} .config
sed -i '/^CONFIG_LOCALVERSION=/d' .config
sed -i 's/^CONFIG_LOCALVERSION_AUTO=y/CONFIG_LOCALVERSION_AUTO=n/' .config

# Append extra config (zswap support); make olddefconfig normalizes it
cat %{SOURCE2} >> .config

%build
LOCALVERSION_FULL=$(cat .lkv_suffix)

export CCACHE_DIR="${CCACHE_DIR:-$HOME/.ccache}"
export CCACHE_MAXSIZE="${CCACHE_MAXSIZE:-10G}"
export CCACHE_SLOPPINESS="file_macro,locale,time_macros"
export CCACHE_NOHASHDIR="true"
mkdir -p "$CCACHE_DIR"

make ARCH=arm64 CC="ccache clang" LLVM=1 LOCALVERSION="${LOCALVERSION_FULL}" olddefconfig
make ARCH=arm64 CC="ccache clang" LLVM=1 LOCALVERSION="${LOCALVERSION_FULL}" \
    -j%{?_smp_build_ncpus} Image modules dtbs

# Save the full kernel version for %%install
echo "%{KERNEL_VER}${LOCALVERSION_FULL}" > %{_topdir}/BUILD/kernel-version

%install
KERNEL_RELEASE=$(cat %{_topdir}/BUILD/kernel-version)
LOCALVERSION_FULL=$(cat .lkv_suffix)

# 1. Install modules
make ARCH=arm64 CC="ccache clang" LLVM=1 LOCALVERSION="${LOCALVERSION_FULL}" \
    INSTALL_MOD_PATH=%{buildroot} modules_install
rm -rf %{buildroot}/lib/modules/*/build
rm -rf %{buildroot}/lib/modules/*/source
# UsrMerge
mkdir -p %{buildroot}/usr
mv %{buildroot}/lib %{buildroot}/usr/

# 2. Install the kernel image to /boot. vmlinuz-<ver> is the uncompressed
#    arm64 Image that U-Boot's booti loads off the ESP (the ESP copy is made
#    in %posttrans). Nothing else in /boot is needed, so Image-*, Image.gz-*,
#    System.map-* and config-* are not shipped.
install -Dm644 arch/arm64/boot/Image %{buildroot}/boot/vmlinuz-${KERNEL_RELEASE}

# 3. Install device tree
install -Dm644 arch/arm64/boot/dts/qcom/sm8550-xiaomi-%{DEVICE_NAME}.dtb \
    %{buildroot}/boot/sm8550-xiaomi-%{DEVICE_NAME}-${KERNEL_RELEASE}.dtb
install -Dm644 arch/arm64/boot/dts/qcom/sm8550-xiaomi-%{DEVICE_NAME}.dtb \
    %{buildroot}/usr/lib/modules/${KERNEL_RELEASE}/dtb/qcom/sm8550-xiaomi-%{DEVICE_NAME}.dtb

%files
%license COPYING
/boot/sm8550-xiaomi-%{DEVICE_NAME}-*.dtb
/boot/vmlinuz-*
/usr/lib/modules/*

%posttrans
set -e

# Resolve the newly installed kernel release: the modules directory this
# package just wrote under /usr/lib/modules is the newest one.
KERNEL_RELEASE=$(ls -dt /usr/lib/modules/*/ 2>/dev/null | head -1 | sed 's#/$##; s#.*/##')
if [ -z "$KERNEL_RELEASE" ]; then
    echo "CRITICAL: no kernel modules directory found" >&2
    exit 1
fi
echo "kernel-%{PLATFORM_NAME}: configuring U-Boot boot for ${KERNEL_RELEASE}"

# 1. The boot chain cannot be updated without the expected ESP. It must be
#    mounted at /boot/efi, be a vfat filesystem, and identify as the sheng ESP
#    by either PARTLABEL=esp or filesystem LABEL=ESP (either one is enough; the
#    LABEL form also covers a partitionless rootfs image, which cannot carry a
#    PARTLABEL). A missing, unmounted or unexpected ESP is a configuration
#    error: fail with a recovery hint instead of writing boot files to the
#    wrong filesystem.
if [ ! -d /boot/efi ]; then
    echo "ERROR: ESP mount point /boot/efi was not found." >&2
    echo "  Add the ESP to /etc/fstab, mount it at /boot/efi, then run:" >&2
    echo "  dnf reinstall kernel-%{PLATFORM_NAME}" >&2
    exit 1
fi
if ! mountpoint -q /boot/efi; then
    echo "ERROR: ESP is not mounted at /boot/efi." >&2
    echo "  Mount it, then run: dnf reinstall kernel-%{PLATFORM_NAME}" >&2
    exit 1
fi
ESP_FSTYPE=$(findmnt -n -o FSTYPE --target /boot/efi 2>/dev/null || true)
if [ "$ESP_FSTYPE" != vfat ]; then
    echo "ERROR: /boot/efi is not a vfat ESP (found: ${ESP_FSTYPE:-unknown})." >&2
    echo "  Refusing to write boot files to the wrong filesystem." >&2
    exit 1
fi
ESP_PARTLABEL=$(findmnt -n -o PARTLABEL --target /boot/efi 2>/dev/null || true)
ESP_LABEL=$(findmnt -n -o LABEL --target /boot/efi 2>/dev/null || true)
if [ "$ESP_PARTLABEL" != esp ] && [ "$ESP_LABEL" != ESP ]; then
    echo "ERROR: /boot/efi is vfat but has PARTLABEL='${ESP_PARTLABEL:-<empty>}' and LABEL='${ESP_LABEL:-<empty>}'." >&2
    echo "  Expected PARTLABEL=esp or LABEL=ESP." >&2
    echo "  Unmount it and mount the sheng ESP at /boot/efi, then run:" >&2
    echo "  dnf reinstall kernel-%{PLATFORM_NAME}" >&2
    exit 1
fi

# 2. Module dependency database. ext4/UFS are built in, so the kernel mounts
#    root directly and no initramfs is generated (no-initramfs direct boot).
depmod -a "${KERNEL_RELEASE}"

# 3. Sync the kernel and DTB to the ESP under stable, version-less names.
#    U-Boot's booti needs the uncompressed Image and /boot/vmlinuz-<ver> IS
#    that Image. Only the current kernel lives on the ESP: a stale vmlinuz.prev
#    is removed instead of being carried along as a fallback.
ESP_DIR=/boot/efi/sheng
mkdir -p "${ESP_DIR}"
rm -f "${ESP_DIR}/vmlinuz.prev"
cp -f "/boot/vmlinuz-${KERNEL_RELEASE}" "${ESP_DIR}/vmlinuz"
cp -f "/boot/sm8550-xiaomi-%{DEVICE_NAME}-${KERNEL_RELEASE}.dtb" \
    "${ESP_DIR}/sm8550-xiaomi-%{DEVICE_NAME}.dtb"
sync

# 4. extlinux.conf is written only when absent: an upgrade must never clobber a
#    boot entry the user may have hand-tuned. root= is taken verbatim from the
#    "/" entry of /etc/fstab, where the rootfs build (or the user) decides which
#    partition to boot from; PARTLABEL=/UUID=/LABEL=/dev/... are all valid
#    kernel root= values, with a fallback to the established default.
if [ ! -f /boot/efi/extlinux/extlinux.conf ]; then
    mkdir -p /boot/efi/extlinux
    ROOT_SPEC=$(awk '!/^[[:space:]]*#/ && $2 == "/" { print $1; exit }' /etc/fstab 2>/dev/null || true)
    if [ -z "$ROOT_SPEC" ]; then
        ROOT_SPEC="PARTLABEL=linux"
        echo "kernel-%{PLATFORM_NAME}: no root entry in /etc/fstab, falling back to root=$ROOT_SPEC" >&2
    fi

    cat > /boot/efi/extlinux/extlinux.conf <<EOF
timeout 3
default sheng

label sheng
	menu label Fedora (sheng)
	kernel /sheng/vmlinuz
	fdt /sheng/sm8550-xiaomi-%{DEVICE_NAME}.dtb
	append root=$ROOT_SPEC rootwait rw console=tty0 quiet systemd.gpt_auto=no cryptomgr.notests systemd.show_status=auto loglevel=3
EOF
    echo "kernel-%{PLATFORM_NAME}: created /boot/efi/extlinux/extlinux.conf (root=$ROOT_SPEC)"
else
    echo "kernel-%{PLATFORM_NAME}: extlinux.conf already present, left unchanged"
fi

echo "SUCCESS: U-Boot boot files synced for ${KERNEL_RELEASE}"

%changelog
* Sun Oct 25 2026 Sheng Packaging <packaging@sheng.local> - 7.3.0-1.sheng
- Rebase to 7.3.0
- Switch to the U-Boot boot flow: drop the Android boot.img and UEFI UKI
  generation (mkbootimg, ukify.conf, 99-sheng-generic.conf, dracut/ukify
  dependencies and the whole %pre cleanup) and sync vmlinuz + DTB to the ESP
  with an extlinux.conf that U-Boot's sysboot reads (no-initramfs direct boot)
- Ship only vmlinuz + DTB in /boot (drop the duplicate Image-*, the unused
  Image.gz-* and the debugging System.map-*/config-*)
- Keep only the current kernel on the ESP: no vmlinuz.prev fallback and no
  extra extlinux menu entry

* Sun Oct 18 2026 Sheng Packaging <packaging@sheng.local> - 7.2.6-5.sheng
- Drop the optional sheng DTS patch logic and its patch file

* Sat Oct 17 2026 Sheng Packaging <packaging@sheng.local> - 7.2.6-4.sheng
- License: GPLv2 -> GPL-2.0-only (SPDX; upstream sm8550-mainline carries the
  kernel's GPL-2.0 COPYING)
- Ship the upstream license text (%license COPYING)