# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: BSD/GPL2

import codecs, errno
from collections import deque
from snakeoil.compatibility import any
from snakeoil.demandload import demandload
demandload(globals(), "snakeoil.xml:escape")

from pkgcore_checks.base import Result, Template, package_feed

import os, stat
pjoin = os.path.join


allowed_filename_chars = "a-zA-Z0-9._-+:"
allowed_filename_chars_set = set()
allowed_filename_chars_set.update(chr(x) for x in xrange(ord('a'), ord('z')+1))
allowed_filename_chars_set.update(chr(x) for x in xrange(ord('A'), ord('Z')+1))
allowed_filename_chars_set.update(chr(x) for x in xrange(ord('0'), ord('9')+1))
allowed_filename_chars_set.update([".", "-", "_", "+", ":"])


class MissingFile(Result):
    """pkg is missing an expected file entry"""

    __slots__ = ("category", "package", "filename")

    threshold = package_feed

    def __init__(self, pkg, filename):
        Result.__init__(self)
        self._store_cp(pkg)
        self.filename = filename

    @property
    def short_desc(self):
        return "required file %s doesn't exist" % self.filename


class ExecutableFile(Result):
    """file has executable bit, but doesn't need it"""

    __slots__ = ("category", "package", "filename")

    threshold = package_feed

    def __init__(self, pkg, filename):
        Result.__init__(self)
        self._store_cp(pkg)
        self.filename = filename

    @property
    def short_desc(self):
        return "file %s has unecessary executable bit" % self.filename


class SizeViolation(Result):
    """filesdir, excluding digest/cvs, is too large"""

    __slots__ = ("category", "package", "size")

    threshold = package_feed

    def __init__(self, pkg, size):
        Result.__init__(self)
        self._store_cp(pkg)
        self.size = size

    @property
    def short_desc(self):
        return "files directory exceeds 20k; %i bytes total" % self.size


class Glep31Violation(Result):

    """file doesn't abide by glep31 requirements"""

    __slots__ = ("category", "package", "filename")

    threshold = package_feed

    def __init__(self, pkg, filename):
        Result.__init__(self)
        self._store_cp(pkg)
        self.filename = filename

    @property
    def short_desc(self):
        return "file %s has char outside the allowed char ranges defined by " \
            "glep31" % self.filename


class InvalidUtf8(Result):

    """file isn't utf8 compliant"""

    __slots__ = ("category", "package", "filename", "err")

    threshold = package_feed

    def __init__(self, pkg, filename, err):
        Result.__init__(self)
        self._store_cp(pkg)
        self.filename = filename
        self.err = err

    @property
    def short_desc(self):
        return "file %s is not valid utf8- %s" % (self.filename, self.err)


def utf8_check(pkg, base, filename, reporter):
    try:
        codecs.open(pjoin(base, filename), mode="rb",
            encoding="utf8", buffering=8192).read()
    except UnicodeDecodeError, e:
        reporter.add_report(InvalidUtf8(pkg, filename, str(e)))
        del e


class PkgDirReport(Template):
    """actual ebuild directory scans; file size, glep31 rule enforcement."""

    feed_type = package_feed

    ignore_dirs = set(["cvs", ".svn", ".bzr"])
    known_results = (MissingFile, ExecutableFile, SizeViolation,
        Glep31Violation, InvalidUtf8)

    def feed(self, pkgset, reporter):
        base = os.path.dirname(pkgset[0].ebuild.get_path())
        # note we don't use os.walk, we need size info also
        for filename in os.listdir(base):
            # while this may seem odd, written this way such that the
            # filtering happens all in the genexp.  if the result was being
            # handed to any, it's a frame switch each
            # char, which adds up.

            if any(True for x in filename if
                x not in allowed_filename_chars_set):
                reporter.add_report(Glep31Violation(pkgset[0], filename))

            if filename.endswith(".ebuild") or filename in \
                ("Manifest", "ChangeLog", "metadata.xml"):
                if os.stat(pjoin(base, filename)).st_mode & 0111:
                    reporter.add_report(ExecutableFile(pkgset[0], filename))

            if filename.endswith(".ebuild"):
                utf8_check(pkgset[0], base, filename, reporter)

        try:
            utf8_check(pkgset[0], base, "ChangeLog", reporter)
        except IOError, e:
            if e.errno != errno.ENOENT:
                raise
            del e
            reporter.add_report(MissingFile(pkgset[0], "ChangeLog"))

        if not os.path.exists(pjoin(base, "files")):
            if pkgset[0].manifest.version == 1:
                reporter.add_report(MissingFile(pkgset[0], "files"))
            return

        size = 0
        unprocessed_dirs = deque(["files"])
        while unprocessed_dirs:
            cwd = unprocessed_dirs.pop()
            for fn in os.listdir(pjoin(base, cwd)):
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
                        size += st.st_size
                        if any(True for x in fn if
                            x not in allowed_filename_chars_set):
                            reporter.add_report(Glep31Violation(pkgset[0],
                                pjoin(cwd, fn)))

                # yes, we silently ignore others.
        if size > 20480:
            reporter.add_report(SizeViolation(pkgset[0], size))
