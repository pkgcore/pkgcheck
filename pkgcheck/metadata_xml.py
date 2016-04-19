# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: BSD/GPL2

import os

from snakeoil import compatibility
from snakeoil.demandload import demandload

from pkgcheck import base

if compatibility.is_py3k:
    urllib_path = 'urllib.request:urlopen'
    demandload(
        'urllib.request:urlopen',
        'urllib:error@urllib_error')
else:
    # yes, this is a bit special.  We do this
    # since the two parts we want, exist
    # in different modules dependant on py2k/py3k.
    demandload(
        'urllib2@urllib_error',
        'urllib2:urlopen')
demandload(
    'argparse',
    'tempfile:NamedTemporaryFile',
    'pkgcore.log:logger',
    'pkgcore.spawn:spawn,find_binary',
    'snakeoil.osutils:pjoin',
    'snakeoil:fileutils',
)


class base_MissingXml(base.Error):
    """required xml file is missing"""

    __slots__ = ('category', 'package', 'filename')
    __attrs__ = __slots__

    def __init__(self, filename, category, package=None):
        super(base_MissingXml, self).__init__()
        self.category = category
        self.package = package
        self.filename = filename

    @property
    def _label(self):
        if self.package is not None:
            return "%s/%s" % (self.category, self.package)
        return self.category

    @property
    def short_desc(self):
        return "%s is missing %s" % (self._label, os.path.basename(self.filename))


class base_BadlyFormedXml(base.Warning):
    """xml isn't well formed"""

    __slots__ = ("category", "package", "filename")
    __attrs__ = __slots__

    def __init__(self, filename, category, package=None):
        super(base_BadlyFormedXml, self).__init__()
        self.category = category
        self.package = package
        self.filename = filename

    @property
    def _label(self):
        if self.package is not None:
            return "%s/%s" % (self.category, self.package)
        return self.category

    @property
    def short_desc(self):
        return "%s %s is not well formed xml" % (self._label, os.path.basename(self.filename))


class base_InvalidXml(base.Error):
    """xml fails dtd validation"""

    __slots__ = ("category", "package", "filename")
    __attrs__ = __slots__

    def __init__(self, filename, category, package=None):
        super(base_InvalidXml, self).__init__()
        self.category = category
        self.package = package
        self.filename = filename

    @property
    def _label(self):
        if self.package is not None:
            return "%s/%s" % (self.category, self.package)
        return self.category

    @property
    def short_desc(self):
        return "%s %s violates metadata.dtd" % (self._label, os.path.basename(self.filename))


class PkgMissingMetadataXml(base_MissingXml):
    __slots__ = ()
    threshold = base.package_feed


class CatMissingMetadataXml(base_MissingXml):
    __slots__ = ()
    threshold = base.category_feed


class PkgInvalidXml(base_InvalidXml):
    __slots__ = ()
    threshold = base.package_feed


class CatInvalidXml(base_InvalidXml):
    __slots__ = ()
    threshold = base.category_feed


class PkgBadlyFormedXml(base_BadlyFormedXml):
    __slots__ = ()
    threshold = base.package_feed


class CatBadlyFormedXml(base_BadlyFormedXml):
    __slots__ = ()
    threshold = base.category_feed


class base_check(base.Template):
    """base class for metadata.xml scans"""

    dtd_url = "http://www.gentoo.org/dtd/metadata.dtd"
    misformed_error = None
    invalid_error = None
    missing_error = None

    @classmethod
    def mangle_argparser(cls, parser):
        try:
            parser.plugin.add_argument(
                '--metadata-dtd',
                help='location to cache %s' % (cls.dtd_url,))
            parser.plugin.add_argument(
                '--metadata-dtd-required',
                help="if metadata.dtd cannot be fetched (no connection for example), "
                     "treat it as a failure rather than warning and ignoring.")
        except argparse.ArgumentError:
            # the arguments have already been added to the parser
            pass

    def __init__(self, options):
        base.Template.__init__(self, options)
        self.repo_base = getattr(options.src_repo, "location", None)
        self.dtd_file = None

    def start(self):
        self.last_seen = None
        refetch = False
        write_path = read_path = self.options.metadata_dtd
        if write_path is None:
            read_path = pjoin(self.repo_base, 'metadata', 'dtd', 'metadata.dtd')
        refetch = not os.path.isfile(read_path)

        if refetch:
            logger.warn('metadata.dtd cannot be opened from %s, will refetch', read_path)
            logger.info("fetching metdata.dtd from %s", self.dtd_url)
            try:
                dtd_data = urlopen(self.dtd_url).read()
            except urllib_error.URLError as e:
                if self.options.metadata_dtd_required:
                    raise Exception(
                        "failed fetching dtd from %s: reason %s. "
                        "Due to --metadata-dtd-required in use, bailing" %
                        (self.dtd_url, e.reason))
                logger.warn(
                    "failed fetching dtd from %s: reason %s", self.dtd_url, e.reason)
                self.validator = noop_validator
                return
            if write_path is None:
                self.dtd_file = NamedTemporaryFile()
                write_path = read_path = self.dtd_file.name
            try:
                fileutils.write_file(write_path, 'wb', dtd_data)
            except EnvironmentError as e:
                if self.options.metadata_dtd_required:
                    raise Exception(
                        "failed saving dtd to %s: reason %s. "
                        "Due to --metadata-dtd-required in use, bailing" %
                        (write_path, e))
                logger.warn("failed writing dtd to %s: reason %s.  Disabling check." %
                            (write_path, e))
                self.validator = noop_validator
                return

        self.dtd_loc = read_path
        self.validator = xmllint_parser(self.dtd_loc).validate

    def feed(self, thing, reporter):
        raise NotImplementedError(self.feed)

    def finish(self, reporter):
        self.last_seen = None

    def check_file(self, loc):
        if not os.path.exists(loc):
            return self.missing_error
        ret = self.validator(loc)
        if ret == 0:
            return None
        elif ret == 1:
            return self.misformed_error
        elif ret == 2:
            return self.invalid_error
        raise AssertionError(
            "got %r from validator, which isn't valid" % ret)


class PackageMetadataXmlCheck(base_check):
    """package level metadata.xml scans"""

    feed_type = base.versioned_feed
    scope = base.package_scope
    misformed_error = PkgBadlyFormedXml
    invalid_error = PkgInvalidXml
    missing_error = PkgMissingMetadataXml

    known_results = (PkgBadlyFormedXml, PkgInvalidXml, PkgMissingMetadataXml)

    def feed(self, pkg, reporter):
        if self.last_seen == pkg.key:
            return
        self.last_seen = pkg.key
        loc = pjoin(os.path.dirname(pkg.ebuild.path), "metadata.xml")
        ret = self.check_file(loc)
        if ret is not None:
            reporter.add_report(ret(loc, pkg.category, pkg.package))


class CategoryMetadataXmlCheck(base_check):
    """metadata.xml scans"""
    feed_type = base.versioned_feed
    scope = base.category_scope
    misformed_error = CatBadlyFormedXml
    invalid_error = CatInvalidXml
    missing_error = CatMissingMetadataXml

    known_results = (CatBadlyFormedXml, CatInvalidXml, CatMissingMetadataXml)

    dtd_url = "http://www.gentoo.org/dtd/metadata.dtd"

    def feed(self, pkg, reporter):
        if self.last_seen == pkg.category:
            return
        self.last_seen = pkg.category
        loc = os.path.join(self.repo_base, pkg.category, "metadata.xml")
        ret = self.check_file(loc)
        if ret is not None:
            reporter.add_report(ret(loc, pkg.category))


class xmllint_parser(object):

    def __init__(self, loc):
        self.dtd_loc = loc
        self.bin_loc = find_binary("xmllint")

    def validate(self, loc):
        """
        :param loc: location to verify
        :return: 0 no issue
                 1 badly formed
                 2 invalid xml
        """
        ret = spawn([self.bin_loc, "--nonet", "--noout", "--dtdvalid",
                    self.dtd_loc, loc], fd_pipes={})

        if ret == 1:
            return 1

        elif ret == 3:
            return 2

        return 0


def noop_validator(loc):
        return 0
