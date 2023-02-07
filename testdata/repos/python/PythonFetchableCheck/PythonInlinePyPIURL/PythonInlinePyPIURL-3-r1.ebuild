# Copyright 2023 Gentoo Authors
# Distributed under the terms of the GNU General Public License v2

EAPI=8

MY_P=pypi-url-${PV}
DESCRIPTION="Ebuild with PyPI URL"
HOMEPAGE="https://example.com"
SRC_URI="
	mirror://pypi/p/pypi-url/${MY_P}.tar.gz
	https://files.pythonhosted.org/packages/py3/p/pypi-url/pypi_url-3-py3-none-any.whl
"
S=${WORKDIR}/${MY_P}

LICENSE="BSD"
SLOT="0"
