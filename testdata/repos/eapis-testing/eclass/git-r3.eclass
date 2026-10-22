# Copyright 1999-2024 Gentoo Authors
# Distributed under the terms of the GNU General Public License v2

# @ECLASS: git-r3.eclass
# @MAINTAINER:
# Michał Górny <mgorny@gentoo.org>
# @SUPPORTED_EAPIS: 7 8
# @BLURB: Eclass for fetching and unpacking git repositories.
# @DESCRIPTION:
# Third generation eclass for easing maintenance of live ebuilds using
# git as remote repository.

case ${EAPI} in
	7|8) ;;
	*) die "${ECLASS}: EAPI ${EAPI:-0} not supported" ;;
esac

if [[ ! ${_GIT_R3_ECLASS} ]]; then
_GIT_R3_ECLASS=1

# @ECLASS_VARIABLE: EGIT_REPO_URI
# @REQUIRED
# @DESCRIPTION:
# URIs to the repository, e.g. https://foo. If multiple URIs are
# provided, the eclass will consider the remaining URIs as fallbacks
# to try if the first URI does not work. For supported URI syntaxes,
# read the manpage for git-clone(1).
#
# URIs should be using https:// whenever possible. http:// and git://
# URIs are completely insecure and their use (even if only as
# a fallback) renders the ebuild completely vulnerable to MITM attacks.
#
# Can be a whitespace-separated list or an array.
#
# Example:
# @CODE
# EGIT_REPO_URI="https://a/b.git https://c/d.git"
# @CODE

fi
