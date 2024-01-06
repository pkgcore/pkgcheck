# Copyright 2022 Gentoo Authors
# Distributed under the terms of the GNU General Public License v2

EAPI=8

DESCRIPTION="Ebuild with valid USE flags"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"

LICENSE="BSD"
SLOT="0"
IUSE="bash-completion ipv6"

BDEPEND="
	UseFlagsWithoutEffectsCheck/UseFlagWithoutDeps[bash-completion(+)]
"

src_compile() {
	emake IPV6=$(use ipv6) BASH="$(use bash-completion)"
}
