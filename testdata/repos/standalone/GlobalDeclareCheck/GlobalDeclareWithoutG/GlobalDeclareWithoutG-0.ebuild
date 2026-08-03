# Copyright 2026 Gentoo Authors
# Distributed under the terms of the GNU General Public License v2

EAPI=8

DESCRIPTION="Ebuild with declare without -g in global scope"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

declare -A ASSOC_ARRAY=(
	[a]=b
	[c]=d
)

declare -rA READONLY_ASSOC=(
	[e]=f
)

declare -gA GOOD_ASSOC=(
	[g]=h
)

declare -g -A ALSO_GOOD=(
	[i]=j
)

declare -Ag YET_ANOTHER_GOOD=(
	[k]=l
)

declare -rAg GOOD_READONLY=(
	[m]=n
)

declare -r READONLY_VAR="foo"

src_prepare() {
	declare -A LOCAL_VAR=(
		[o]=p
	)
}
