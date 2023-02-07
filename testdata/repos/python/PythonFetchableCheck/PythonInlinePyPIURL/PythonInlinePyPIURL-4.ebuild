# Copyright 2023 Gentoo Authors
# Distributed under the terms of the GNU General Public License v2

EAPI=8

MY_P=pypi_url-${PV}
DESCRIPTION="Ebuild with PyPI URL"
HOMEPAGE="https://example.com"
SRC_URI="
	mirror://pypi/p/pypi-url/${MY_P}.tar.gz
	https://files.pythonhosted.org/packages/cp310/${PN::1}/${PN}/${P,,}-cp310-cp310-linux_x86_64.whl
"
S=${WORKDIR}/${MY_P}

LICENSE="BSD"
SLOT="0"
