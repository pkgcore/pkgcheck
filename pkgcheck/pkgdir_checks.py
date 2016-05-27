# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: BSD/GPL2

import codecs
from collections import deque
import os
import stat

from pkgcore.ebuild.atom import MalformedAtom, atom
from snakeoil.demandload import demandload
from snakeoil.osutils import listdir, pjoin, sizeof_fmt

from pkgcheck.base import Result, Template, package_feed

demandload('errno')

allowed_filename_chars = "a-zA-Z0-9._-+:"
allowed_filename_chars_set = set()
allowed_filename_chars_set.update(chr(x) for x in xrange(ord('a'), ord('z')+1))
allowed_filename_chars_set.update(chr(x) for x in xrange(ord('A'), ord('Z')+1))
allowed_filename_chars_set.update(chr(x) for x in xrange(ord('0'), ord('9')+1))
allowed_filename_chars_set.update([".", "-", "_", "+", ":"])


class MissingFile(Result):
    """Package is missing an expected file entry."""

    __slots__ = ("category", "package", "filename")

    threshold = package_feed

    def __init__(self, pkg, filename):
        Result.__init__(self)
        self._store_cp(pkg)
        self.filename = filename

    @property
    def short_desc(self):
        return "required file doesn't exist: %r" % (self.filename,)


class MismatchedPN(Result):
    """Ebuilds that have different names than their parent directory."""

    __slots__ = ("category", "package", "ebuilds")

    threshold = package_feed

    def __init__(self, pkg, ebuilds):
        Result.__init__(self)
        self._store_cp(pkg)
        self.ebuilds = ebuilds

    @property
    def short_desc(self):
        return "mismatched package name%s: [ %s ]" % (
            's'[len(self.ebuilds) == 1:], ', '.join(self.ebuilds))


class InvalidPN(Result):
    """Ebuilds that have invalid package names."""

    __slots__ = ("category", "package", "ebuilds")

    threshold = package_feed

    def __init__(self, pkg, ebuilds):
        Result.__init__(self)
        self._store_cp(pkg)
        self.ebuilds = ebuilds

    @property
    def short_desc(self):
        return "invalid package name%s: [ %s ]" % (
            's'[len(self.ebuilds) == 1:], ', '.join(self.ebuilds))


class ExecutableFile(Result):
    """File has executable bit, but doesn't need it."""

    __slots__ = ("category", "package", "filename")

    threshold = package_feed

    def __init__(self, pkg, filename):
        Result.__init__(self)
        self._store_cp(pkg)
        self.filename = filename

    @property
    def short_desc(self):
        return 'unnecessary executable bit: %r' % (self.filename,)


class SizeViolation(Result):
    """File in $FILESDIR is too large (current limit is 20k)."""

    __slots__ = ("category", "package", "filename", "size")

    threshold = package_feed

    def __init__(self, pkg, filename, size):
        Result.__init__(self)
        self._store_cp(pkg)
        self.filename = filename
        self.size = size

    @property
    def short_desc(self):
        return '"files/%s" exceeds 20k in size; %s total' % (
            self.filename, sizeof_fmt(self.size))


class Glep31Violation(Result):
    """File doesn't abide by glep31 requirements."""

    __slots__ = ("category", "package", "filename")

    threshold = package_feed

    def __init__(self, pkg, filename):
        Result.__init__(self)
        self._store_cp(pkg)
        self.filename = filename

    @property
    def short_desc(self):
        return "filename contains char outside the allowed ranges defined " \
               "by glep31: %r" % (self.filename,)


class InvalidUtf8(Result):
    """File isn't utf8 compliant."""

    __slots__ = ("category", "package", "filename", "err")

    threshold = package_feed

    def __init__(self, pkg, filename, err):
        Result.__init__(self)
        self._store_cp(pkg)
        self.filename = filename
        self.err = err

    @property
    def short_desc(self):
        return "invalid utf8: %s: %r" % (self.err, self.filename)


def utf8_check(pkg, base, filename, reporter):
    try:
        codecs.open(pjoin(base, filename), mode="rb",
                    encoding="utf8", buffering=8192).read()
    except UnicodeDecodeError as e:
        reporter.add_report(InvalidUtf8(pkg, filename, str(e)))
        del e


class PkgDirReport(Template):
    """Actual ebuild directory scans; file size, glep31 rule enforcement."""

    feed_type = package_feed

    ignore_dirs = set(["cvs", ".svn", ".bzr"])
    known_results = (MissingFile, ExecutableFile, SizeViolation,
                     Glep31Violation, InvalidUtf8, MismatchedPN, InvalidPN)

    def feed(self, pkgset, reporter):
        base = os.path.dirname(pkgset[0].ebuild.path)
        category = os.path.basename(
            os.path.dirname(os.path.dirname(pkgset[0].ebuild.path)))
        ebuild_ext = '.ebuild'
        mismatched = []
        invalid = []
        # note we don't use os.walk, we need size info also
        for filename in listdir(base):
            # while this may seem odd, written this way such that the
            # filtering happens all in the genexp.  if the result was being
            # handed to any, it's a frame switch each
            # char, which adds up.

            if any(True for x in filename if x not in allowed_filename_chars_set):
                reporter.add_report(Glep31Violation(pkgset[0], filename))

            if filename.endswith(ebuild_ext) or filename in \
                    ("Manifest", "metadata.xml"):
                if os.stat(pjoin(base, filename)).st_mode & 0111:
                    reporter.add_report(ExecutableFile(pkgset[0], filename))

            if filename.endswith(ebuild_ext):
                utf8_check(pkgset[0], base, filename, reporter)

                pkg_name = os.path.basename(filename[:-len(ebuild_ext)])
                try:
                    pkg_atom = atom('=%s/%s' % (category, pkg_name))
                    if pkg_atom.package != os.path.basename(base):
                        mismatched.append(pkg_name)
                except MalformedAtom:
                    invalid.append(pkg_name)

        if mismatched:
            reporter.add_report(MismatchedPN(pkgset[0], mismatched))
        if invalid:
            reporter.add_report(InvalidPN(pkgset[0], invalid))

        if not os.path.exists(pjoin(base, 'files')):
            return
        unprocessed_dirs = deque(["files"])
        while unprocessed_dirs:
            cwd = unprocessed_dirs.pop()
            for fn in listdir(pjoin(base, cwd)):
                afn = pjoin(base, cwd, fn)
                st = os.lstat(afn)

                if stat.S_ISDIR(st.st_mode):
                    if fn not in self.ignore_dirs:
                        unprocessed_dirs.append(pjoin(cwd, fn))

                elif stat.S_ISREG(st.st_mode):
                    if st.st_mode & 0111:
                        reporter.add_report(ExecutableFile(pkgset[0],
                                                           pjoin(cwd, fn)))
                    if not fn.startswith("digest-"):
                        if st.st_size > 20480:
                            reporter.add_report(SizeViolation(pkgset[0], fn, st.st_size))
                        if any(True for x in fn if x not in allowed_filename_chars_set):
                            reporter.add_report(Glep31Violation(pkgset[0], pjoin(cwd, fn)))
