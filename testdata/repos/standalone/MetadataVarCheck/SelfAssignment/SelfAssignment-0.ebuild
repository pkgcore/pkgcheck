DESCRIPTION="Ebuild with various self assignments"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

RDEPEND="${RDEPEND}" # FAIL
RDEPEND="$RDEPEND" # FAIL
RDEPEND=${RDEPEND} # FAIL
RDEPEND=$RDEPEND # FAIL
RDEPEND="${RDEPEND}
" # FAIL
RDEPEND="
	${RDEPEND}" # FAIL
RDEPEND="
	${RDEPEND}
" # FAIL

RDEPEND+=" ${RDEPEND}" # OK (+=)
RDEPEND="${RDEPEND} stub/stub1" # OK (something else)
RDEPEND="stub/stub1 ${RDEPEND}" # OK (something else)
RDEPEND="${RDEPEND:=stub/stub1}" # OK (:=)
