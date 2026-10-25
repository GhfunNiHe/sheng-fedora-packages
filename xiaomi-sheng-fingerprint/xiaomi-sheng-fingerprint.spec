%global debug_package %{nil}

%global version_local 0.1.4
%global fingerprint_build_dir %{_topdir}/BUILD/fingerprint-build

Name:           xiaomi-sheng-fingerprint
Version:        %{version_local}
Release:        2%{?dist}
Summary:        FPC1553 fingerprint sensor support for Xiaomi Pad 6S Pro
License:        Apache-2.0 AND LGPL-2.1-or-later AND GPL-2.0-or-later
URL:            https://github.com/ianchb/xiaomi-sheng-fingerprint
Source0:        %{url}/archive/refs/tags/v%{version}.tar.gz#/%{name}-v%{version}.tar.gz
Source1:        libfprint-src.tar.xz
ExclusiveArch:  aarch64
BuildRequires:  gcc meson ninja-build patchelf curl
BuildRequires:  glib2-devel libusb1-devel nss-devel libgusb-devel
BuildRequires:  libgudev-devel libfprint-devel systemd-rpm-macros

%description
User-space support for the FPC1553 fingerprint sensor in the Xiaomi Pad 6S Pro
12.4 (sheng). Installs privately under /usr/lib/xiaomi-sheng-fingerprint/
without overwriting the distribution's libfprint. Includes the FPC1553 QTEE
backend library, a patched libfprint with the FPC1553 driver, QTEE
supplicant, and systemd integration.

%prep
%autosetup -n %{name}-%{version}

# Verify prebuilt binaries
sha256sum -c prebuilt/aarch64/SHA256SUMS

%build
# -------------------------------------------------------------------
# 1. Build backend library (libfpc1553-qtee.so)
# -------------------------------------------------------------------
rm -rf "%{fingerprint_build_dir}"
mkdir -p "%{fingerprint_build_dir}"

AR_WORK="%{fingerprint_build_dir}/minkadaptor"
mkdir -p "$AR_WORK"
cd "$AR_WORK"
ar x "%{_builddir}/%{name}-%{version}/prebuilt/aarch64/build-libs/libminkadaptor.a"
objcopy --redefine-sym recv_ioctl=mink_recv_ioctl \
    --redefine-sym recv=mink_recv_svc \
    --redefine-sym recv_skip=mink_recv_skip supplicant.c.o
objcopy --redefine-sym recv_ioctl=mink_recv_ioctl \
    --redefine-sym recv=mink_recv_svc \
    --redefine-sym recv_skip=mink_recv_skip syscall.S.o
ar rcs libminkadaptor-fixed.a mink_adaptor.c.o supplicant.c.o syscall.S.o

cd "%{_builddir}/%{name}-%{version}"
# ${CC:-gcc} unquoted on purpose: the build environment sets CC="ccache gcc",
# which has to expand to two words. This compile used to call gcc directly and
# was the one object in the tree that never reached the cache.
${CC:-gcc} -O2 -DNDEBUG -Wall -Wextra -fPIC -shared -pthread \
    -Wl,-soname,libfpc1553-qtee.so -Wl,-z,relro -Wl,-z,now \
    -Ibackend/include -Ithird_party/mink/include -Ithird_party/QCBOR/inc \
    -o "%{fingerprint_build_dir}/libfpc1553-qtee.so" \
    backend/src/fpc_qtee_client.c backend/src/fpc_protocol.c \
    backend/src/fpc_db_store.c backend/src/fpc_index.c \
    backend/src/gatekeeper_client.c backend/src/gatekeeper_identity.c \
    backend/src/gatekeeper_protocol.c \
    -Wl,--whole-archive \
    prebuilt/aarch64/build-libs/librpmbservice.a \
    prebuilt/aarch64/build-libs/libqcomtee.a \
    prebuilt/aarch64/build-libs/libqcbor.a \
    "$AR_WORK/libminkadaptor-fixed.a" \
    -Wl,--no-whole-archive -lm
strip --strip-unneeded "%{fingerprint_build_dir}/libfpc1553-qtee.so"

mkdir -p "%{fingerprint_build_dir}/backend"
install -m 0644 "%{fingerprint_build_dir}/libfpc1553-qtee.so" "%{fingerprint_build_dir}/backend/"
install -m 0644 backend/include/*.h "%{fingerprint_build_dir}/backend/"

# -------------------------------------------------------------------
# 2. Build patched libfprint (private install, fpc1553 driver only)
# -------------------------------------------------------------------
# ccache stays ON here. It used to carry an `export CCACHE_DISABLE=1`, which
# turned the largest compile in this package into a guaranteed miss on every
# run. Nothing in this build is hostile to ccache: `meson setup` takes the
# compiler from the environment, --buildtype=release --strip do not change the
# object files, and the absolute -I/%{fingerprint_build_dir} paths only make
# the hash version-specific, never wrong.

mkdir -p "%{fingerprint_build_dir}/src"
tar -xf %{SOURCE1} -C "%{fingerprint_build_dir}/src" --strip-components=1

cd "%{fingerprint_build_dir}/src"
patch -p1 < "%{_builddir}/%{name}-%{version}/patches/libfprint/0001-libfprint-add-fpc1553.patch"

VENDOR_DIR="%{fingerprint_build_dir}/vendor/QCBOR-1.6/inc"
install -d -m 0755 "$VENDOR_DIR"
cp -R "%{_builddir}/%{name}-%{version}/third_party/QCBOR/inc/." "$VENDOR_DIR/"

meson setup "%{fingerprint_build_dir}/build" "%{fingerprint_build_dir}/src" \
    --buildtype=release --strip \
    --prefix=%{_prefix} --libdir=lib/xiaomi-sheng-fingerprint \
    -Ddrivers=fpc1553 -Dfpc1553_backend_dir="%{fingerprint_build_dir}/backend" \
    -Dintrospection=false -Ddoc=false -Dinstalled-tests=false \
    -Dgtk-examples=false -Dudev_rules=disabled -Dudev_hwdb=disabled
meson compile -C "%{fingerprint_build_dir}/build"

LIBFPRINT_SO="%{fingerprint_build_dir}/build/libfprint/libfprint-2.so.2.0.0"
patchelf --set-rpath '$ORIGIN' "$LIBFPRINT_SO"

%install
cd "%{_builddir}/%{name}-%{version}"

install -d -m 0755 %{buildroot}%{_libdir}/xiaomi-sheng-fingerprint
install -d -m 0755 %{buildroot}%{_libdir}/qtee-listeners
install -d -m 0755 %{buildroot}%{_libexecdir}

# Private libfprint + backend
install -m 0644 "%{fingerprint_build_dir}/build/libfprint/libfprint-2.so.2.0.0" \
    %{buildroot}%{_libdir}/xiaomi-sheng-fingerprint/
ln -s libfprint-2.so.2.0.0 \
    %{buildroot}%{_libdir}/xiaomi-sheng-fingerprint/libfprint-2.so.2
ln -s libfprint-2.so.2 \
    %{buildroot}%{_libdir}/xiaomi-sheng-fingerprint/libfprint-2.so
install -m 0644 "%{fingerprint_build_dir}/libfpc1553-qtee.so" \
    %{buildroot}%{_libdir}/xiaomi-sheng-fingerprint/

# Prebuilt QTEE runtime
install -m 0755 prebuilt/aarch64/qteesupplicant %{buildroot}%{_libexecdir}/
install -m 0755 prebuilt/aarch64/sfs_config %{buildroot}%{_libexecdir}/fpc-sfs-config
for listener in prebuilt/aarch64/qtee-listeners/*.so.1.0.0; do
    name=$(basename "$listener")
    base=${name%.1.0.0}
    install -m 0644 "$listener" %{buildroot}%{_libdir}/qtee-listeners/"$name"
    ln -s "$name" %{buildroot}%{_libdir}/qtee-listeners/"$base"
done

# systemd
install -Dm644 systemd/qteesupplicant.service \
    %{buildroot}%{_unitdir}/qteesupplicant.service
install -Dm644 systemd/sfsconfig.service \
    %{buildroot}%{_unitdir}/sfsconfig.service
install -Dm644 systemd/fprintd.service.d/10-xiaomi-sheng-fpc1553.conf \
    %{buildroot}%{_unitdir}/fprintd.service.d/10-xiaomi-sheng-fpc1553.conf

# udev
install -Dm644 udev/99-qcomtee-fpc.rules \
    %{buildroot}%{_udevrulesdir}/99-qcomtee-fpc.rules

%files
%license LICENSE
%dir %{_libdir}/xiaomi-sheng-fingerprint
%{_libdir}/xiaomi-sheng-fingerprint/libfprint-2.so
%{_libdir}/xiaomi-sheng-fingerprint/libfprint-2.so.2
%{_libdir}/xiaomi-sheng-fingerprint/libfprint-2.so.2.0.0
%{_libdir}/xiaomi-sheng-fingerprint/libfpc1553-qtee.so
%dir %{_libdir}/qtee-listeners
%{_libdir}/qtee-listeners/libfsservice.so.1.0.0
%{_libdir}/qtee-listeners/libfsservice.so
%{_libdir}/qtee-listeners/libgpfsservice.so.1.0.0
%{_libdir}/qtee-listeners/libgpfsservice.so
%{_libdir}/qtee-listeners/librpmbservice.so.1.0.0
%{_libdir}/qtee-listeners/librpmbservice.so
%{_libdir}/qtee-listeners/libtimeservice.so.1.0.0
%{_libdir}/qtee-listeners/libtimeservice.so
%{_libexecdir}/qteesupplicant
%{_libexecdir}/fpc-sfs-config
%{_unitdir}/qteesupplicant.service
%{_unitdir}/sfsconfig.service
%{_unitdir}/fprintd.service.d/10-xiaomi-sheng-fpc1553.conf
%{_udevrulesdir}/99-qcomtee-fpc.rules
%doc README.md UPSTREAM_CHANGES.md

%post
%systemd_post sfsconfig.service
%systemd_post qteesupplicant.service
systemctl enable qteesupplicant.service
if command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload || :
    udevadm trigger --subsystem-match=tee || :
fi

%preun
%systemd_preun qteesupplicant.service
%systemd_preun sfsconfig.service

%postun
%systemd_postun_with_restart qteesupplicant.service

%changelog
* Sat Oct 17 2026 Sheng Packaging <packaging@sheng.local> - 0.1.4-2
- Ship the upstream license text (%license LICENSE, Apache-2.0); the LGPL/GPL
  terms in the License tag come from the bundled libfprint sources
