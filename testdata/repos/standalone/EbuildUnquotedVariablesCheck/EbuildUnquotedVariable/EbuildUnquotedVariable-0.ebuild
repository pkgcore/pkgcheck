EAPI=8

DESCRIPTION="Ebuild with variables that must be quoted"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"

S=${WORKDIR}/${PV} # ok

LICENSE="BSD"
SLOT="0"

PATCHES=(
	${FILESDIR}/foo.patch # FAIL
	"${FILESDIR}"/foo.patch # ok
	"${FILESDIR}/foo.patch" # ok
)

src_prepare() {
	if [[ -z ${S} ]]; then  # ok
		:
	fi

	if has "foo" ${FILESDIR} ; then # FAIL
		:
	fi

	local t=${T} # ok
	local t=${T}/t # ok
	emake CC=${T}; someotherfunc ${T} # FAIL

	local var=( TMP=${T} ) # FAIL

	cat > "${T}"/somefile <<- EOF || die
		PATH="${EPREFIX}${INSTALLDIR}/bin"
	EOF
	doenvd "${T}"/10stuffit # ok

	echo "InitiatorName=$(${WORKDIR}/usr/sbin/iscsi-iname)" # FAIL
	einfo ${WORKDIR} # ok

	if grep -qs '^ *sshd *:' "${WORKDIR}"/etc/hosts.{allow,deny} ; then # ok
		ewarn "something something ${WORKDIR} here"
	fi

	cat < ${T} # FAIL
	cat >> ${T} # FAIL

	local TMPDIR # ok
	TMPDIR="$(mktemp --directory --tmpdir=/tmp ${PN}-XXXX)" # ok
	export TMPDIR # ok

	unset TMPDIR # ok
}
