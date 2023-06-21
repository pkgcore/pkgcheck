CRATES="
	snakeoil@0.10.0
	pkgcore@0.10.0
	pkgcheck@0.10.0
"

inherit cargo

DESCRIPTION="Ebuild with suboptimal cargo_crate_uris"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
SLOT="0"
LICENSE="BSD"
SRC_URI="$(cargo_crate_uris ${CRATES})"
