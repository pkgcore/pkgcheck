# Copyright 2023 Gentoo Authors
# Distributed under the terms of the GNU General Public License v2

EAPI=8

DESCRIPTION="Ebuild with two PyPI URLs"
HOMEPAGE="https://example.com"
SRC_URI="
	mirror://pypi/${PN::1}/${PN/-/.}/${PN//-/_}-${PV}.tar.gz
	mirror://pypi/${PN::1}/${PN/-/.}_vectors/${PN/-/.}_vectors-151.tar.gz
"
S=${WORKDIR}/${PN//-/_}-${PV}

LICENSE="BSD"
SLOT="0"
