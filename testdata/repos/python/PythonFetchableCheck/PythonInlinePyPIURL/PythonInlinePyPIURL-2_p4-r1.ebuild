# Copyright 2023 Gentoo Authors
# Distributed under the terms of the GNU General Public License v2

EAPI=8

MY_P=${PN,,}-${PV/_p/.post}
DESCRIPTION="Ebuild with PyPI URL"
HOMEPAGE="https://example.com"
SRC_URI="
	mirror://pypi/${PN::1}/${PN}/${MY_P}.tar.gz
	https://example.com/foo.patch
"
S=${WORKDIR}/${MY_P}

LICENSE="BSD"
SLOT="0"
