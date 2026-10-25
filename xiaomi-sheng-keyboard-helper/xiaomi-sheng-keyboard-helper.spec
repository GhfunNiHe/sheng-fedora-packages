%global debug_package %{nil}

Name:           xiaomi-sheng-keyboard-helper
Version:        0.2.0
Release:        3%{?dist}
Summary:        Keyboard cover helper for Xiaomi Pad 6S Pro
License:        Apache-2.0
URL:            https://github.com/ianchb/xiaomi-sheng-keyboard-helper
Source0:        %{url}/archive/refs/tags/v%{version}.tar.gz#/%{name}-v%{version}.tar.gz
ExclusiveArch:  aarch64
BuildRequires:  gcc glib2-devel libssc
BuildRequires:  systemd-rpm-macros
Requires:       libssc glib2

%description
Restores fold-angle input control for the original keyboard cover on the
Xiaomi Pad 6S Pro 12.4 (sheng). Disables keyboard/touchpad input when the
cover is nearly closed or folded behind, and synchronizes a microphone mute
indicator with PipeWire.

%prep
%autosetup -n %{name}-%{version}

%build
# Do not hardcode CC=gcc here: the build environment sets CC="ccache gcc", and
# a command-line assignment on %make_build wins over the environment, which is
# exactly how this package used to bypass ccache. Keep the gcc fallback for a
# plain local rpmbuild that runs without the CI environment.
%make_build CC="${CC:-gcc}"

%install
# Manually install since the Makefile uses /usr prefix
install -Dm755 build/xiaomi-sheng-keyboard-helper \
    %{buildroot}%{_libexecdir}/xiaomi-sheng-keyboard-helper
install -Dm644 systemd/xiaomi-sheng-keyboard-helper-angle.service \
    %{buildroot}%{_unitdir}/xiaomi-sheng-keyboard-helper-angle.service
install -Dm644 systemd-user/xiaomi-sheng-keyboard-helper-micmute.service \
    %{buildroot}%{_userunitdir}/xiaomi-sheng-keyboard-helper-micmute.service
# Force English locale for pactl subprocesses: get-source-mute and subscribe
# output are localized (e.g. "Mute: 否"), which the helper cannot parse and
# leaves the mic-mute LED unsynchronized.
sed -i '/^\[Service\]/a Environment=LC_ALL=C LANG=C' \
    %{buildroot}%{_userunitdir}/xiaomi-sheng-keyboard-helper-micmute.service
install -Dm644 udev/90-xiaomi-sheng-keyboard-helper.rules \
    %{buildroot}%{_udevrulesdir}/90-xiaomi-sheng-keyboard-helper.rules

%files
%{_libexecdir}/xiaomi-sheng-keyboard-helper
%{_unitdir}/xiaomi-sheng-keyboard-helper-angle.service
%{_userunitdir}/xiaomi-sheng-keyboard-helper-micmute.service
%{_udevrulesdir}/90-xiaomi-sheng-keyboard-helper.rules
%license LICENSE
%doc README.md

%post
%systemd_post xiaomi-sheng-keyboard-helper-angle.service
systemctl enable xiaomi-sheng-keyboard-helper-angle.service
if command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload || :
fi

%preun
%systemd_preun xiaomi-sheng-keyboard-helper-angle.service

%postun
%systemd_postun_with_restart xiaomi-sheng-keyboard-helper-angle.service

%changelog
* Sat Oct 17 2026 Sheng Packaging <packaging@sheng.local> - 0.2.0-3
- Ship the upstream license text (%license LICENSE, Apache-2.0)
- Fix the weekday of the 0.2.0-2 entry: 2026-08-24 is a Monday, not a Tuesday
  (rpmspec warned about the bogus date on every run)

* Mon Aug 24 2026 xiaomi <GhfunNiHe@bbcctv520@petalmail.com> - 0.2.0-2
- Fix mic-mute LED not updating under non-English locales by forcing
  LC_ALL=C on the micmute user service (pactl output localization).
