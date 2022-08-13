"""Various file-based header checks."""

import re

from .. import results, sources
from . import GentooRepoCheck

copyright_regex = re.compile(
    r'^# Copyright (?P<begin>\d{4}-)?(?P<end>\d{4}) (?P<holder>.+)$')


class _FileHeaderResult(results.Result):
    """Generic file header result."""

    def __init__(self, line, **kwargs):
        super().__init__(**kwargs)
        self.line = line


class InvalidCopyright(_FileHeaderResult, results.AliasResult, results.Error):
    """File with invalid copyright.

    The file does not start with a valid copyright line. Each ebuild or eclass
    file must start with a copyright line of the form::

        # Copyright YEARS MAIN-CONTRIBUTOR [OTHER-CONTRIBUTOR]... [and others]

    Files in the Gentoo repository must use::

        # Copyright YEARS Gentoo Authors
    """

    _name = 'InvalidCopyright'

    @property
    def desc(self):
        return f'invalid copyright: {self.line!r}'


class OldGentooCopyright(_FileHeaderResult, results.AliasResult, results.Warning):
    """File with old Gentoo Foundation copyright.

    The file still assigns copyright to the Gentoo Foundation even though
    it has been committed after the new copyright policy was approved
    (2018-10-21).

    Ebuilds and eclasses in Gentoo repository must use 'Gentoo Authors'
    instead. Files in other repositories may specify an explicit copyright
    holder instead.
    """

    _name = 'OldGentooCopyright'

    @property
    def desc(self):
        return f'old copyright, update to "Gentoo Authors": {self.line!r}'


class NonGentooAuthorsCopyright(_FileHeaderResult, results.AliasResult, results.Error):
    """File with copyright stating owner other than "Gentoo Authors".

    The file specifies explicit copyright owner, while the Gentoo repository
    policy specifies that all ebuilds and eclasses must use "Gentoo Authors".
    If the owner is not listed in metadata/AUTHORS, addition can be requested
    via bugs.gentoo.org.
    """

    _name = 'NonGentooAuthorsCopyright'

    @property
    def desc(self):
        return f'copyright line must state "Gentoo Authors": {self.line!r}'


class InvalidLicenseHeader(_FileHeaderResult, results.AliasResult, results.Error):
    """File with invalid license header.

    The file does not have with a valid license header.

    Ebuilds and eclasses in the Gentoo repository must use::

        # Distributed under the terms of the GNU General Public License v2
    """

    _name = 'InvalidLicenseHeader'

    @property
    def desc(self):
        if self.line:
            return f'invalid license header: {self.line!r}'
        return 'missing license header'


class _HeaderCheck(GentooRepoCheck):
    """Scan files for incorrect copyright/license headers."""

    _invalid_copyright = InvalidCopyright
    _old_copyright = OldGentooCopyright
    _non_gentoo_authors = NonGentooAuthorsCopyright
    _invalid_license = InvalidLicenseHeader
    known_results = frozenset([
        _invalid_copyright, _old_copyright, _non_gentoo_authors, _invalid_license,
    ])
    _item_attr = 'pkg'

    license_header = '# Distributed under the terms of the GNU General Public License v2'

    def args(self, item):
        return {self._item_attr: item}

    def feed(self, item):
        if item.lines:
            line = item.lines[0].strip()
            if mo := copyright_regex.match(line):
                # Copyright policy is active since 2018-10-21, so it applies
                # to all ebuilds committed in 2019 and later
                if int(mo.group('end')) >= 2019:
                    if mo.group('holder') == 'Gentoo Foundation':
                        yield self._old_copyright(line, **self.args(item))
                    # Gentoo policy requires 'Gentoo Authors'
                    elif mo.group('holder') != 'Gentoo Authors':
                        yield self._non_gentoo_authors(line, **self.args(item))
            else:
                yield self._invalid_copyright(line, **self.args(item))

            try:
                line = item.lines[1].strip('\n')
            except IndexError:
                line = ''
            if line != self.license_header:
                yield self._invalid_license(line, **self.args(item))


class EbuildInvalidCopyright(InvalidCopyright, results.VersionResult):
    __doc__ = InvalidCopyright.__doc__


class EbuildOldGentooCopyright(OldGentooCopyright, results.VersionResult):
    __doc__ = OldGentooCopyright.__doc__


class EbuildNonGentooAuthorsCopyright(NonGentooAuthorsCopyright, results.VersionResult):
    __doc__ = NonGentooAuthorsCopyright.__doc__


class EbuildInvalidLicenseHeader(InvalidLicenseHeader, results.VersionResult):
    __doc__ = InvalidLicenseHeader.__doc__


class EbuildHeaderCheck(_HeaderCheck):
    """Scan ebuild for incorrect copyright/license headers."""

    _source = sources.EbuildFileRepoSource

    _invalid_copyright = EbuildInvalidCopyright
    _old_copyright = EbuildOldGentooCopyright
    _non_gentoo_authors = EbuildNonGentooAuthorsCopyright
    _invalid_license = EbuildInvalidLicenseHeader
    known_results = frozenset([
        _invalid_copyright, _old_copyright, _non_gentoo_authors, _invalid_license,
    ])
    _item_attr = 'pkg'


class EclassInvalidCopyright(InvalidCopyright, results.EclassResult):
    __doc__ = InvalidCopyright.__doc__

    @property
    def desc(self):
        return f'{self.eclass}: {super().desc}'


class EclassOldGentooCopyright(OldGentooCopyright, results.EclassResult):
    __doc__ = OldGentooCopyright.__doc__

    @property
    def desc(self):
        return f'{self.eclass}: {super().desc}'


class EclassNonGentooAuthorsCopyright(NonGentooAuthorsCopyright, results.EclassResult):
    __doc__ = NonGentooAuthorsCopyright.__doc__

    @property
    def desc(self):
        return f'{self.eclass}: {super().desc}'


class EclassInvalidLicenseHeader(InvalidLicenseHeader, results.EclassResult):
    __doc__ = InvalidLicenseHeader.__doc__

    @property
    def desc(self):
        return f'{self.eclass}: {super().desc}'


class EclassHeaderCheck(_HeaderCheck):
    """Scan eclasses for incorrect copyright/license headers."""

    _source = sources.EclassRepoSource

    _invalid_copyright = EclassInvalidCopyright
    _old_copyright = EclassOldGentooCopyright
    _non_gentoo_authors = EclassNonGentooAuthorsCopyright
    _invalid_license = EclassInvalidLicenseHeader
    known_results = frozenset([
        _invalid_copyright, _old_copyright, _non_gentoo_authors, _invalid_license,
    ])
    _item_attr = 'eclass'
