import codecs
from collections import defaultdict, deque
import os
import stat

from pkgcore.ebuild.atom import MalformedAtom, atom as atom_cls
from snakeoil.demandload import demandload
from snakeoil.osutils import listdir, pjoin, sizeof_fmt
from snakeoil.strings import pluralism as _pl

from .. import base

demandload('snakeoil.chksum:get_chksums')

allowed_filename_chars = "a-zA-Z0-9._-+:"
allowed_filename_chars_set = set()
allowed_filename_chars_set.update(chr(x) for x in range(ord('a'), ord('z')+1))
allowed_filename_chars_set.update(chr(x) for x in range(ord('A'), ord('Z')+1))
allowed_filename_chars_set.update(chr(x) for x in range(ord('0'), ord('9')+1))
allowed_filename_chars_set.update([".", "-", "_", "+", ":"])


class MismatchedPN(base.Error):
    """Ebuilds that have different names than their parent directory."""

    __slots__ = ("category", "package", "ebuilds")

    threshold = base.package_feed

    def __init__(self, pkg, ebuilds):
        super().__init__()
        self._store_cp(pkg)
        self.ebuilds = tuple(sorted(ebuilds))

    @property
    def short_desc(self):
        return "mismatched package name%s: [ %s ]" % (
            _pl(self.ebuilds), ', '.join(self.ebuilds))


class InvalidPN(base.Error):
    """Ebuilds that have invalid package names."""

    __slots__ = ("category", "package", "ebuilds")

    threshold = base.package_feed

    def __init__(self, pkg, ebuilds):
        super().__init__()
        self._store_cp(pkg)
        self.ebuilds = tuple(sorted(ebuilds))

    @property
    def short_desc(self):
        return "invalid package name%s: [ %s ]" % (
            _pl(self.ebuilds), ', '.join(self.ebuilds))


class EqualVersions(base.Error):
    """Ebuilds that have equal versions.

    For example, cat/pn-1.0.2, cat/pn-1.0.2-r0, cat/pn-1.0.2-r00 and
    cat/pn-1.000.2 all have equal versions according to PMS and therefore
    shouldn't exist in the same repository.
    """

    __slots__ = ("category", "package", "versions")

    threshold = base.versioned_feed

    def __init__(self, pkg, versions):
        super().__init__()
        self._store_cpv(pkg)
        self.versions = tuple(sorted(versions))

    @property
    def short_desc(self):
        return f"equal package versions: [ {', '.join(map(repr, self.versions))} ]"


class DuplicateFiles(base.Warning):
    """Two or more identical files in FILESDIR."""

    __slots__ = ("category", "package", "files")

    threshold = base.package_feed

    def __init__(self, pkg, files):
        super().__init__()
        self._store_cp(pkg)
        self.files = tuple(sorted(files))

    @property
    def short_desc(self):
        return 'duplicate identical files in FILESDIR: %s' % (
            ', '.join(map(repr, self.files)))


class EmptyFile(base.Warning):
    """File in FILESDIR is empty."""

    __slots__ = ("category", "package", "filename")

    threshold = base.package_feed

    def __init__(self, pkg, filename):
        super().__init__()
        self._store_cp(pkg)
        self.filename = filename

    @property
    def short_desc(self):
        return f'empty file in FILESDIR: {self.filename!r}'


class ExecutableFile(base.Warning):
    """File has executable bit, but doesn't need it."""

    __slots__ = ("category", "package", "filename")

    threshold = base.package_feed

    def __init__(self, pkg, filename):
        super().__init__()
        self._store_cp(pkg)
        self.filename = filename

    @property
    def short_desc(self):
        return f'unnecessary executable bit: {self.filename!r}'


class SizeViolation(base.Warning):
    """File in $FILESDIR is too large (current limit is 20k)."""

    __slots__ = ("category", "package", "filename", "size")

    threshold = base.package_feed

    def __init__(self, pkg, filename, size):
        super().__init__()
        self._store_cp(pkg)
        self.filename = filename
        self.size = size

    @property
    def short_desc(self):
        return f'{self.filename!r} exceeds 20k in size; {sizeof_fmt(self.size)} total'


class Glep31Violation(base.Error):
    """File doesn't abide by glep31 requirements."""

    __slots__ = ("category", "package", "filename")

    threshold = base.package_feed

    def __init__(self, pkg, filename):
        super().__init__()
        self._store_cp(pkg)
        self.filename = filename

    @property
    def short_desc(self):
        return "filename contains char outside the allowed ranges defined " \
               f"by glep31: {self.filename!r}"


class InvalidUTF8(base.Error):
    """File isn't UTF-8 compliant."""

    __slots__ = ("category", "package", "filename", "err")

    threshold = base.package_feed

    def __init__(self, pkg, filename, err):
        super().__init__()
        self._store_cp(pkg)
        self.filename = filename
        self.err = err

    @property
    def short_desc(self):
        return f"invalid UTF-8: {self.err}: {self.filename!r}"


def utf8_check(pkg, base, filename):
    try:
        codecs.open(
            pjoin(base, filename), mode="rb",
            encoding="utf8", buffering=8192).read()
    except UnicodeDecodeError as e:
        yield InvalidUTF8(pkg, filename, str(e))
        del e


class PkgDirReport(base.Template):
    """Actual ebuild directory scans; file size, glep31 rule enforcement."""

    feed_type = base.package_feed

    ignore_dirs = set(["cvs", ".svn", ".bzr"])
    known_results = (
        DuplicateFiles, EmptyFile, ExecutableFile, SizeViolation,
        Glep31Violation, InvalidUTF8, MismatchedPN, InvalidPN, EqualVersions,
    )

    # TODO: put some 'preferred algorithms by purpose' into snakeoil?
    digest_algo = 'sha256'

    def feed(self, pkgset):
        pkg = pkgset[0]
        base_path = os.path.dirname(pkg.path)
        category = os.path.basename(
            os.path.dirname(os.path.dirname(pkg.path)))
        ebuild_ext = '.ebuild'
        mismatched = []
        invalid = []
        # note we don't use os.walk, we need size info also
        for filename in listdir(base_path):
            # while this may seem odd, written this way such that the
            # filtering happens all in the genexp.  if the result was being
            # handed to any, it's a frame switch each
            # char, which adds up.

            if any(True for x in filename if x not in allowed_filename_chars_set):
                yield Glep31Violation(pkg, filename)

            if (filename.endswith(ebuild_ext) or filename in
                    ("Manifest", "metadata.xml")):
                if os.stat(pjoin(base_path, filename)).st_mode & 0o111:
                    yield ExecutableFile(pkg, filename)

            if filename.endswith(ebuild_ext):
                utf8_check(pkg, base_path, filename)

                pkg_name = os.path.basename(filename[:-len(ebuild_ext)])
                try:
                    pkg_atom = atom_cls(f'={category}/{pkg_name}')
                    if pkg_atom.package != os.path.basename(base_path):
                        mismatched.append(pkg_name)
                except MalformedAtom:
                    invalid.append(pkg_name)

        if mismatched:
            yield MismatchedPN(pkg, mismatched)
        if invalid:
            yield InvalidPN(pkg, invalid)

        # check for equal versions
        equal_versions = defaultdict(set)
        sorted_pkgset = sorted(pkgset)
        for i, pkg_a in enumerate(sorted_pkgset):
            try:
                pkg_b = sorted_pkgset[i + 1]
            except IndexError:
                break
            if pkg_a.versioned_atom == pkg_b.versioned_atom:
                equal_versions[pkg_a.versioned_atom].update([pkg_a.fullver, pkg_b.fullver])
        for atom, versions in equal_versions.items():
            yield EqualVersions(atom, versions)

        if not os.path.exists(pjoin(base_path, 'files')):
            return
        unprocessed_dirs = deque(["files"])
        files_by_size = defaultdict(list)
        while unprocessed_dirs:
            cwd = unprocessed_dirs.pop()
            for fn in listdir(pjoin(base_path, cwd)):
                afn = pjoin(base_path, cwd, fn)
                st = os.lstat(afn)

                if stat.S_ISDIR(st.st_mode):
                    if fn not in self.ignore_dirs:
                        unprocessed_dirs.append(pjoin(cwd, fn))
                elif stat.S_ISREG(st.st_mode):
                    if st.st_mode & 0o111:
                        yield ExecutableFile(pkg, pjoin(cwd, fn))
                    if not fn.startswith("digest-"):
                        if st.st_size == 0:
                            yield EmptyFile(pkg, pjoin(cwd, fn))
                        else:
                            files_by_size[st.st_size].append(pjoin(cwd, fn))
                            if st.st_size > 20480:
                                yield SizeViolation(pkg, pjoin(cwd, fn), st.st_size)
                        if any(True for x in fn if x not in allowed_filename_chars_set):
                            yield Glep31Violation(pkg, pjoin(cwd, fn))

        files_by_digest = defaultdict(list)
        for size, files in files_by_size.items():
            if len(files) > 1:
                for f in files:
                    digest = get_chksums(pjoin(base_path, f), self.digest_algo)[0]
                    files_by_digest[digest].append(f)

        for digest, files in files_by_digest.items():
            if len(files) > 1:
                yield DuplicateFiles(pkg, files)
