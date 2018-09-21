import codecs
from collections import defaultdict, deque
import os
import stat

from pkgcore.ebuild.atom import MalformedAtom, atom
from snakeoil.demandload import demandload
from snakeoil.osutils import listdir, pjoin, sizeof_fmt
from snakeoil.strings import pluralism

from .base import Error, Warning, Template, package_feed

demandload('errno', 'snakeoil.chksum:get_chksums')

allowed_filename_chars = "a-zA-Z0-9._-+:"
allowed_filename_chars_set = set()
allowed_filename_chars_set.update(chr(x) for x in range(ord('a'), ord('z')+1))
allowed_filename_chars_set.update(chr(x) for x in range(ord('A'), ord('Z')+1))
allowed_filename_chars_set.update(chr(x) for x in range(ord('0'), ord('9')+1))
allowed_filename_chars_set.update([".", "-", "_", "+", ":"])


class MissingFile(Error):
    """Package is missing an expected file entry."""

    __slots__ = ("category", "package", "filename")

    threshold = package_feed

    def __init__(self, pkg, filename):
        super().__init__()
        self._store_cp(pkg)
        self.filename = filename

    @property
    def short_desc(self):
        return f"required file doesn't exist: {self.filename!r}"


class MismatchedPN(Error):
    """Ebuilds that have different names than their parent directory."""

    __slots__ = ("category", "package", "ebuilds")

    threshold = package_feed

    def __init__(self, pkg, ebuilds):
        super().__init__()
        self._store_cp(pkg)
        self.ebuilds = tuple(sorted(ebuilds))

    @property
    def short_desc(self):
        return "mismatched package name%s: [ %s ]" % (
            pluralism(self.ebuilds), ', '.join(self.ebuilds))


class InvalidPN(Error):
    """Ebuilds that have invalid package names."""

    __slots__ = ("category", "package", "ebuilds")

    threshold = package_feed

    def __init__(self, pkg, ebuilds):
        super().__init__()
        self._store_cp(pkg)
        self.ebuilds = tuple(sorted(ebuilds))

    @property
    def short_desc(self):
        return "invalid package name%s: [ %s ]" % (
            pluralism(self.ebuilds), ', '.join(self.ebuilds))


class DuplicateFiles(Warning):
    """Two or more identical files in FILESDIR."""

    __slots__ = ("category", "package", "files")

    threshold = package_feed

    def __init__(self, pkg, files):
        super().__init__()
        self._store_cp(pkg)
        self.files = tuple(sorted(files))

    @property
    def short_desc(self):
        return 'duplicate identical files in FILESDIR: %s' % (
            ', '.join(map(repr, self.files)))


class EmptyFile(Warning):
    """File in FILESDIR is empty."""

    __slots__ = ("category", "package", "filename")

    threshold = package_feed

    def __init__(self, pkg, filename):
        super().__init__()
        self._store_cp(pkg)
        self.filename = filename

    @property
    def short_desc(self):
        return f'empty file in FILESDIR: {self.filename!r}'


class ExecutableFile(Warning):
    """File has executable bit, but doesn't need it."""

    __slots__ = ("category", "package", "filename")

    threshold = package_feed

    def __init__(self, pkg, filename):
        super().__init__()
        self._store_cp(pkg)
        self.filename = filename

    @property
    def short_desc(self):
        return f'unnecessary executable bit: {self.filename!r}'


class SizeViolation(Warning):
    """File in $FILESDIR is too large (current limit is 20k)."""

    __slots__ = ("category", "package", "filename", "size")

    threshold = package_feed

    def __init__(self, pkg, filename, size):
        super().__init__()
        self._store_cp(pkg)
        self.filename = filename
        self.size = size

    @property
    def short_desc(self):
        return f'{self.filename!r} exceeds 20k in size; {sizeof_fmt(self.size)} total'


class Glep31Violation(Error):
    """File doesn't abide by glep31 requirements."""

    __slots__ = ("category", "package", "filename")

    threshold = package_feed

    def __init__(self, pkg, filename):
        super().__init__()
        self._store_cp(pkg)
        self.filename = filename

    @property
    def short_desc(self):
        return "filename contains char outside the allowed ranges defined " \
               f"by glep31: {self.filename!r}"


class InvalidUtf8(Error):
    """File isn't utf8 compliant."""

    __slots__ = ("category", "package", "filename", "err")

    threshold = package_feed

    def __init__(self, pkg, filename, err):
        super().__init__()
        self._store_cp(pkg)
        self.filename = filename
        self.err = err

    @property
    def short_desc(self):
        return "invalid utf8: {self.err}: {self.filename!r}"


def utf8_check(pkg, base, filename, reporter):
    try:
        codecs.open(
            pjoin(base, filename), mode="rb",
            encoding="utf8", buffering=8192).read()
    except UnicodeDecodeError as e:
        reporter.add_report(InvalidUtf8(pkg, filename, str(e)))
        del e


class PkgDirReport(Template):
    """Actual ebuild directory scans; file size, glep31 rule enforcement."""

    feed_type = package_feed

    ignore_dirs = set(["cvs", ".svn", ".bzr"])
    known_results = (
        DuplicateFiles, EmptyFile, ExecutableFile, SizeViolation,
        Glep31Violation, InvalidUtf8, MismatchedPN, InvalidPN,
    )

    # TODO: put some 'preferred algorithms by purpose' into snakeoil?
    digest_algo = 'sha256'

    def feed(self, pkgset, reporter):
        pkg = pkgset[0]
        base = os.path.dirname(pkg.path)
        category = os.path.basename(
            os.path.dirname(os.path.dirname(pkg.path)))
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
                reporter.add_report(Glep31Violation(pkg, filename))

            if (filename.endswith(ebuild_ext) or filename in
                    ("Manifest", "metadata.xml")):
                if os.stat(pjoin(base, filename)).st_mode & 0o111:
                    reporter.add_report(ExecutableFile(pkg, filename))

            if filename.endswith(ebuild_ext):
                utf8_check(pkg, base, filename, reporter)

                pkg_name = os.path.basename(filename[:-len(ebuild_ext)])
                try:
                    pkg_atom = atom(f'={category}/{pkg_name}')
                    if pkg_atom.package != os.path.basename(base):
                        mismatched.append(pkg_name)
                except MalformedAtom:
                    invalid.append(pkg_name)

        if mismatched:
            reporter.add_report(MismatchedPN(pkg, mismatched))
        if invalid:
            reporter.add_report(InvalidPN(pkg, invalid))

        if not os.path.exists(pjoin(base, 'files')):
            return
        unprocessed_dirs = deque(["files"])
        files_by_size = defaultdict(list)
        while unprocessed_dirs:
            cwd = unprocessed_dirs.pop()
            for fn in listdir(pjoin(base, cwd)):
                afn = pjoin(base, cwd, fn)
                st = os.lstat(afn)

                if stat.S_ISDIR(st.st_mode):
                    if fn not in self.ignore_dirs:
                        unprocessed_dirs.append(pjoin(cwd, fn))
                elif stat.S_ISREG(st.st_mode):
                    if st.st_mode & 0o111:
                        reporter.add_report(
                            ExecutableFile(pkg, pjoin(cwd, fn)))
                    if not fn.startswith("digest-"):
                        if st.st_size == 0:
                            reporter.add_report(EmptyFile(pkg, pjoin(cwd, fn)))
                        else:
                            files_by_size[st.st_size].append(pjoin(cwd, fn))
                            if st.st_size > 20480:
                                reporter.add_report(SizeViolation(pkg, pjoin(cwd, fn), st.st_size))
                        if any(True for x in fn if x not in allowed_filename_chars_set):
                            reporter.add_report(Glep31Violation(pkg, pjoin(cwd, fn)))

        files_by_digest = defaultdict(list)
        for size, files in files_by_size.items():
            if len(files) > 1:
                for f in files:
                    digest = get_chksums(pjoin(base, f), self.digest_algo)[0]
                    files_by_digest[digest].append(f)

        for digest, files in files_by_digest.items():
            if len(files) > 1:
                reporter.add_report(DuplicateFiles(pkg, files))
