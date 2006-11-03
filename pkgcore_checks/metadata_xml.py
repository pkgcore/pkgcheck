# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

import os
from pkgcore_checks import base
from pkgcore.util.demandload import demandload
demandload(globals(), "urllib:urlopen "
    "tempfile:NamedTemporaryFile "
    "libxml2 "
    "pkgcore.spawn:spawn,find_binary ")


class base_check(base.Template):
    """base class for metadata.xml scans"""

    dtd_url = "http://www.gentoo.org/dtd/metadata.dtd"

    def __init__(self, options):
        base.Template.__init__(self, options)
        self.base = getattr(options.src_repo, "base", None)
        self.dtd_file = None

    def feed(self, data, reporter):
        loc = self.base
        if self.base is not None:
            loc = os.path.join(self.base, "metadata", "dtd", "metadata.dtd")
            if not os.path.exists(loc):
                loc = None

        if loc is not None:
            self.dtd_loc = loc
        else:
            dtd = urlopen(self.dtd_url).read()
            self.dtd_file = NamedTemporaryFile()
            self.dtd_loc = self.dtd_file.name
            os.chmod(self.dtd_loc, 0644)
            self.dtd_file.write(dtd)
            self.dtd_file.flush()
        try:
            self.validator = libxml_parser(self.dtd_loc).validate
        except ImportError:
            self.validator = xmllint_parser(self.dtd_loc).validate
        self.last_seen = None

        for thing in data:
            yield thing
            self._feed(thing, reporter)
        self.last_seen = None

    def _feed(self, thing, reporter):
        raise NotImplementedError(self._feed)

    def check_file(self, loc):
        if not os.path.exists(loc):
            return False
        return self.validator(loc)


class PackageMetadataXmlCheck(base_check):
    """package level metadata.xml scans"""

    feed_type = base.versioned_feed
    enabling_threshold = base.package_feed

    def _feed(self, pkg, reporter):
        if self.last_seen == pkg.key:
            return
        self.last_seen = pkg.key
        loc = os.path.join(os.path.dirname(pkg.ebuild.get_path()),
                           "metadata.xml")
        ret = self.check_file(loc)
        if ret:
            reporter.add_report(ret(loc, pkg.category, pkg.package))


class CategoryMetadataXmlCheck(base_check):
    """metadata.xml scans"""
    feed_type = base.versioned_feed
    enabling_threshold = base.category_feed

    dtd_url = "http://www.gentoo.org/dtd/metadata.dtd"

    def _feed(self, pkg, reporter):
        if self.last_seen == pkg.category:
            return
        self.last_seen = pkg.category
        loc = os.path.join(self.base, pkg.category, "metadata.xml")
        ret = self.check_file(loc)
        if ret:
            reporter.add_report(ret(loc, pkg.category))


class libxml_parser(object):

    def __init__(self, loc):
        self.parsed_dtd = libxml2.parseDTD(None, loc)
        self.validator = libxml2.newValidCtxt()
    
    def validate(self, loc):
        xml = libxml2.createFileParserCtxt(loc)
        xml.parseDocument()
        if not xml.isValid():
            return BadlyFormedXml
        elif not xml.doc().validateDtd(self.validator, self.parsed_dtd):
            return InvalidXml
        return False


class xmllint_parser(object):

    def __init__(self, loc):
        self.dtd_loc = loc
        self.bin_loc = find_binary("xmllint")
    
    def validate(self, loc):
        if not os.path.exists(loc):
            return False
        ret = spawn([self.bin_loc, "--nonet", "--noout", "--dtdvalid",
            self.dtd_loc, loc], fd_pipes={})

        if ret == 1:
            return BadlyFormedXml

        elif ret == 3:
            return InvalidXml

        return False


class BadlyFormedXml(base.Result):
    """xml isn't well formed"""
    __slots__ = ("category", "package", "filename")
    
    def __init__(self, filename, category, package=None):
        base.Result.__init__(self)
        self.category = category
        self.package = package
        self.filename = filename
    
    def to_str(self):
        s = ''
        if self.package is not None:
            s = '/' + self.package
        return "%s%s: %s is not well formed" % (self.category, s,
            self.filename)
    
    def to_xml(self):
        s = ''
        if self.package is not None:
            s = "\n    <package>%s</package>" % self.package

        return \
"""<check name="%s">
    <category>%s</category>%s
    <msg>%s is not well formed</msg>
</check>""" % (self.__class__.__name__, self.category, s, self.filename)


class InvalidXml(base.Result):
    """xml fails dtd validation"""
    __slots__ = ("category", "package", "file")
    
    def __init__(self, filename, category, package=None):
        base.Result.__init__(self, filename, category, package=None)
        self.category = category
        self.package = package
        self.filename = filename

    def to_str(self):
        s = ''
        if self.package is not None:
            s = '/' + self.package

        return "%s%s: %s violates it's dtd" % (self.category, s, 
            self.filename)

    def to_xml(self):
        s = ''
        if self.package is not None:
            s = "\n    <package>%s</package>" % self.package

        return \
"""<check name="%s">
    <category>%s</category>%s
    <msg>%s is not valid according to it's dtd</msg>
</check>""" % (self.__class__.__name__, self.category, s, self.filename)
