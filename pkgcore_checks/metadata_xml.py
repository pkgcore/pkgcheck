# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

import os
from pkgcore_checks.base import template, Result, package_feed
from pkgcore.util.demandload import demandload
demandload(globals(), "urllib:urlopen "
    "tempfile:NamedTemporaryFile "
    "libxml2 "
    "pkgcore.spawn:spawn,find_binary ")


class MetadataXmlReport(template):
    """metadata.xml scans"""
    feed_type = package_feed
    
    dtd_url = "http://www.gentoo.org/dtd/metadata.dtd"

    def __init__(self, options):
        template.__init__(self, options)
        self.base = getattr(options.src_repo, "base", None)
        self.dtd_file = None

    # protocol... pylint: disable-msg=W0613
    def start(self, repo):
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
    
    def feed(self, pkgset, reporter):
        loc = os.path.join(os.path.dirname(pkgset[0].path), "metadata.xml")
        if os.path.exists(loc):
            ret = self.validator(pkgset[0], loc)
            if ret is not None:
                reporter.add_report(ret)


class libxml_parser(object):

    def __init__(self, loc):
        self.parsed_dtd = libxml2.parseDTD(None, loc)
        self.validator = libxml2.newValidCtxt()
    
    def validate(self, pkg, loc):
        xml = libxml2.createFileParserCtxt(loc)
        xml.parseDocument()
        if not xml.isValid():
            return BadlyFormedXml(pkg, os.path.basename(loc))
        elif not xml.doc().validateDtd(self.validator, self.parsed_dtd):
            return InvalidXml(pkg, os.path.basename(loc))
        return None


class xmllint_parser(object):

    def __init__(self, loc):
        self.dtd_loc = loc
        self.bin_loc = find_binary("xmllint")
    
    def validate(self, pkg, loc):
        ret = spawn([self.bin_loc, "--nonet", "--noout", "--dtdvalid",
            self.dtd_loc, loc], fd_pipes={})

        if ret == 1:
            return BadlyFormedXml(pkg, os.path.basename(loc))

        elif ret == 3:
            return InvalidXml(pkg, os.path.basename(loc))

        return None


class BadlyFormedXml(Result):
    """xml isn't well formed"""
    __slots__ = ("category", "package", "version", "filename")
    
    def __init__(self, pkg, filename):
        Result.__init__(self)
        self._store_cpv(pkg)
        self.filename = filename
    
    def to_str(self):
        return "%s/%s-%s: %s is not well formed" % (self.category,
            self.package, self.version, self.filename)
    
    def to_xml(self):
        return \
"""<check name="%s">
    <category>%s</category>
    <package>%s</package>
    <version>%s</version>
    <msg>%s is not well formed</msg>
</check>""" % (self.__class__.__name__, self.category, self.package,
    self.version, self.filename)


class InvalidXml(Result):
    """xml fails dtd validation"""
    __slots__ = ("category", "package", "version", "file")
    
    def __init__(self, pkg, filename):
        Result.__init__(self)
        self._store_cpv(pkg)
        self.filename = filename
    
    def to_str(self):
        return "%s/%s-%s: %s violates it's dtd" % (self.category, self.package, 
            self.version, self.filename)
    
    def to_xml(self):
        return \
"""<check name="%s">
    <category>%s</category>
    <package>%s</package>
    <version>%s</version>
    <msg>%s is not valid according to it's dtd</msg>
</check>""" % (self.__class__.__name__, self.category, self.package, 
    self.version, self.filename)
