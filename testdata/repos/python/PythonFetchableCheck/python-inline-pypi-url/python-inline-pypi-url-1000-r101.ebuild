# Copyright 2023 Gentoo Authors
# Distributed under the terms of the GNU General Public License v2

EAPI=8

DESCRIPTION="Ebuild with PyPI URL"
HOMEPAGE="https://example.com"
SRC_URI="mirror://pypi/${PN::1}/${PN//-/_}/${PN//-/_}-${PV}.tar.gz"
S=${WORKDIR}/${PN//-/_}-${PV}

LICENSE="BSD"
SLOT="0"
