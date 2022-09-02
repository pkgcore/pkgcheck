# Copyright 2022 Gentoo Authors
# Distributed under the terms of the GNU General Public License v2

# @ECLASS: unquotedvariable.eclass
# @MAINTAINER:
# Larry the Cow <larry@gentoo.org>
# @AUTHOR:
# Larry the Cow <larry@gentoo.org>
# @SUPPORTED_EAPIS: 8
# @BLURB: Eclass that forgets to quote a variable properly
# @DESCRIPTION:
# A small eclass that defines a single variable, but references a variable that
# needs to be quoted in specific contexts.

# @ECLASS_VARIABLE: EBZR_STORE_DIR
# @USER_VARIABLE
# @DESCRIPTION:
# Some text
: ${EBZR_STORE_DIR:=${PORTAGE_ACTUAL_DISTDIR:-${DISTDIR}}/bzr-src}

# @FUNCTION: webapp_configfile
# @USAGE: <file> [more files ...]
# @DESCRIPTION:
# Some text
webapp_configfile() {
	echo "${my_file}" >> ${D}/${WA_CONFIGLIST}
}
