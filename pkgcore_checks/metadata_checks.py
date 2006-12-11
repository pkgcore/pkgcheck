# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

import os
from operator import attrgetter
from pkgcore_checks import base, util, addons
from itertools import ifilterfalse
from pkgcore.util.caching import WeakInstMeta

from pkgcore.util.compatibility import any
from pkgcore.util.file import read_dict
from pkgcore.package.errors import MetadataException
from pkgcore.ebuild.atom import MalformedAtom, atom
from pkgcore.util.lists import iflatten_instance
from pkgcore.util.iterables import expandable_chain
from pkgcore.fetch import fetchable
from pkgcore.restrictions import packages
from pkgcore.util.osutils import listdir_files, join as pjoin

from pkgcore.util.demandload import demandload
demandload(globals(), "pkgcore.util.xml:escape "
    "logging errno ")


class iuse_checking(object):

    __metaclass__ = WeakInstMeta
    __inst_caching__ = True

    def __init__(self, profile_bases):
        known_iuse = set()
        unstated_iuse = set()
        for profile_base in profile_bases:
            try:
                known_iuse.update(util.get_use_desc(profile_base))
            except IOError, ie:
                if ie.errno != errno.ENOENT:
                    raise

            try:
                for restricts_dict in \
                    util.get_use_local_desc(profile_base).itervalues():
                    for flags in restricts_dict.itervalues():
                        known_iuse.update(x.strip() for x in flags)
            except IOError, ie:
                if ie.errno != errno.ENOENT:
                    raise		

            use_expand_base = pjoin(profile_base, "desc")
            try:
                for entry in listdir_files(use_expand_base):
                    try:
                        estr = entry.rsplit(".", 1)[0].lower()+ "_"
                        unstated_iuse.update(estr + usef.strip() for usef in 
                            read_dict(pjoin(use_expand_base, entry),
                                None).iterkeys())
                    except (IOError, OSError), ie:
                        if ie.errno != errno.EISDIR:
                            raise
                        del ie
            except (OSError, IOError), ie:
                if ie.errno != errno.ENOENT:
                    raise

        known_iuse.update(unstated_iuse)
        self.known_iuse = frozenset(known_iuse)
        unstated_iuse.update(util.get_repo_known_arches(profile_base))
        self.unstated_iuse = frozenset(unstated_iuse)
        self.profile_bases = profile_base
        self.ignore = not (unstated_iuse or known_iuse)

    def get_filter(self):
        if self.ignore:
            return self.fake_iuse_validate
        return self.iuse_validate
        
    @staticmethod
    def fake_iuse_validate(klasses, pkg, seq, reporter):
        return iflatten_instance(seq, klasses)

    def iuse_validate(self, klasses, pkg, seq, reporter):
        skip_filter = (packages.Conditional,) + klasses
        unstated = set()
    
        stated = pkg.iuse
        i = expandable_chain(iflatten_instance(seq, skip_filter))
        for node in i:
            if isinstance(node, packages.Conditional):
                # invert it; get only whats not in pkg.iuse
                unstated.update(ifilterfalse(stated.__contains__,
                    node.restriction.values))
                i.append(iflatten_instance(node.payload, skip_filter))
                continue
            yield node

        # the valid_unstated_iuse filters out USE_EXPAND as long as
        # it's listed in a desc file
        unstated.difference_update(self.valid_unstated_iuse)
        # hack, see bugs.gentoo.org 134994.
        unstated.difference_update(["bootstrap"])
        if unstated:
            reporter.add_report(UnstatedIUSE(pkg, attr_name,
                unstated))


class use_consumer(base.Template):

    enabled = False
    feed_type = base.versioned_feed
    required_addons = (addons.ProfileAddon,)

    def start(self):
        self.iuse_handler = iuse_checking(self.options.repo_bases)
        self.iuse_filter = self.iuse_handler.get_filter()
        base.Template.start(self)

    def finish(self, reporter):
        self.iuse_handler = self.iuse_filter = None
        base.Template.finish(self, reporter)


class LicenseMetadataReport(use_consumer):

    """LICENSE metadata key validity checks"""
    
    enabled = True
    required_addons = (addons.ProfileAddon, addons.LicenseAddon)

    def start(self):
        use_consumer.start(self)
        self.licenses = set()
        for license_dir in self.options.license_dirs:
            self.licenses.update(listdir_files(license_dir))

    def finish(self, reporter):
        self.licenses = None
        use_consumer.finish(self, reporter)
    
    def feed(self, pkg, reporter):
        try:
            licenses = pkg.license
        except (KeyboardInterrupt, SystemExit):
            raise
        except (MetadataException, MalformedAtom, ValueError), e:
            reporter.add_report(MetadataError(pkg, attr_name, 
                "error- %s" % e))
            del e
        except Exception, e:
            logging.error("unknown exception caught for pkg(%s) attr(%s): "
                "type(%s), %s" % (pkg, attr_name, type(e), e))
            reporter.add_report(MetadataError(pkg, attr_name, 
                "exception- %s" % e))
            del e
        else:
            i = self.iuse_filter((basestring,), pkg, licenses, reporter)
            if self.licenses is None:
                # force a walk of it so it'll report if needs be.
                for x in i:
                    pass
            else:
                licenses = set(i)
                if not licenses:
                    reporter.add_report(MetadataError(pkg, "license",
                        "no license defined"))
                else:
                    licenses.difference_update(self.licenses)
                    if licenses:
                        reporter.add_report(MetadataError(pkg, "license",
                            "licenses don't exist- [ %s ]" %
                            ", ".join(licenses)))


class IUSEMetadataReport(use_consumer):
    
    """Check IUSE for valid use flags"""
    
    enabled = True
    
    def feed(self, pkg, reporter):
        if not self.iuse_handler.ignore:
            iuse = set(pkg.iuse).difference(self.iuse_handler.known_iuse)
            if iuse:
                reporter.add_report(MetadataError(pkg, "iuse", 
                    "iuse unknown flags- [ %s ]" % ", ".join(iuse)))


class DependencyReport(use_consumer):

    """check DEPEND, PDEPEND, RDEPEND, and PROVIDES"""

    enabled = True
    attrs = tuple((x, attrgetter(x)) for x in
        ("depends", "rdepends", "post_rdepends"))

    def feed(self, pkg, reporter):
        for attr_name, getter in self.attrs:
            try:
                for x in self.iuse_filter((atom,), pkg, getter(pkg), reporter):
                    pass
            except (KeyboardInterrupt, SystemExit):
                raise
            except (MetadataException, MalformedAtom, ValueError), e:
                reporter.add_report(MetadataError(pkg, attr_name, 
                    "error- %s" % e))
                del e
            except Exception, e:
                logging.error("unknown exception caught for pkg(%s) attr(%s): "
                    "type(%s), %s" % (pkg, attr_name, type(e), e))
                reporter.add_report(MetadataError(pkg, attr_name, 
                    "exception- %s" % e))
                del e


class KeywordsReport(base.Template):
    
    feed_type = base.versioned_feed
    
    def feed(self, pkg, reporter):
        if not pkg.keywords:
            reporter.add_report(EmptyKeywords(pkg))

        if "-*" in pkg.keywords:
            reporter.add_report(StupidKeywords(pkg))



class SrcUriReport(use_consumer):
    """SRC_URI related checks.
    verify that it's a valid/fetchable uri, port 80,443,23
    """
    enabled = True
    valid_protos = frozenset(["http", "https", "ftp"])

    def feed(self, pkg, reporter):
        try:
            lacks_uri = set()
            for f_inst in self.iuse_filter((fetchable,), pkg, pkg.fetchables,
                reporter):
                if f_inst.uri is None:
                    lacks_uri.add(f_inst.filename)
                elif isinstance(f_inst.uri, list):
                    bad = set()
                    for x in f_inst.uri:
                        i = x.find("://")
                        if i == -1:
                            bad.add(x)
                        else:
                            if x[:i] not in self.valid_protos:
                                bad.add(x)
                    if bad:
                        reporter.add_report(
                            BadProto(pkg, f_inst.filename, bad))
            if not "fetch" in pkg.restrict:
                for x in lacks_uri:
                    reporter.add_report(MissingUri(pkg, x))

        except (KeyboardInterrupt, SystemExit):
            raise
        except (MetadataException, MalformedAtom, ValueError), e:
            reporter.add_report(MetadataError(pkg, attr_name, 
                "error- %s" % e))
            del e
        except Exception, e:
            logging.error("unknown exception caught for pkg(%s) attr(%s): "
                "type(%s), %s" % (pkg, attr_name, type(e), e))
            reporter.add_report(MetadataError(pkg, attr_name, 
                "exception- %s" % e))
            del e


class DescriptionReport(base.Template):
    """
    DESCRIPTION checks.
    check on length (<=250), too short (<5), or generic (lifted from eclass or
    just using the pkgs name
    """
    
    feed_type = base.versioned_feed

    def feed(self, pkg, reporter):
        s = pkg.description.lower()

        if s.startswith("based on") and "eclass" in s:
            reporter.add_report(CrappyDescription(pkg,
                "generic eclass defined description"))

        elif pkg.package == s or pkg.key == s:
            reporter.add_report(CrappyDescription(pkg,
                "using the pkg name as the description isn't very helpful"))

        else:
            l = len(pkg.description)
            if not l:
                reporter.add_report(CrappyDescription(pkg,
                    "empty/unset"))
            elif l > 250:
                reporter.add_report(CrappyDescription(pkg,
                    "over 250 chars in length, bit long"))
            elif l < 5:
                reporter.add_report(CrappyDescription(pkg,
                    "under 10 chars in length- too short"))


class RestrictsReport(base.Template):
    feed_type = base.versioned_feed
    known_restricts = frozenset(("confcache", "stricter", "mirror", "fetch", 
        "test", "sandbox", "userpriv", "primaryuri", "binchecks", "strip",
        "multilib-strict"))

    __doc__ = "check over RESTRICT, looking for unknown restricts\nvalid " \
        "restricts:%s" % ", ".join(sorted(known_restricts))
    
    def feed(self, pkgs, reporter):
        for pkg in pkgs:
            yield pkg
            bad = set(pkg.restrict).difference(self.known_restricts)
            if bad:
                deprecated = set(x for x in bad if x.startswith("no")
                    and x[2:] in self.known_restricts)
                reporter.add_report(BadRestricts(
                        pkg, bad.difference(deprecated), deprecated))


class BadRestricts(base.Result):
    """pkg's restrict metadata has unknown/deprecated entries"""
    
    __slots__ = ("category", "package", "version", "restricts", "deprecated")
    
    def __init__(self, pkg, restricts, deprecated=None):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.restricts = restricts
        self.deprecated = deprecated
        if not restricts and not deprecated:
            raise TypeError("deprecated or restricts must not be empty")
    
    def to_str(self):
        s = ''
        if self.restricts:
            s = "unknown restricts [ %s ]" % ", ".join(self.restricts)
        if self.deprecated:
            if s:
                s += ", "
            s += "deprecated (drop the 'no') [ %s ]" % ", ".join(
                self.deprecated)
        return "%s/%s-%s: %s" % (self.category, self.package, self.version, s)
        
    def to_xml(self):
        s = ''
        if self.restricts:
            s = "unknown restricts: %s" % ", ".join(self.restricts)
        if self.deprecated:
            if s:
                s += ".  "
            s += "deprecated (drop the 'no')- %s" % ", ".join(self.deprecated)

        return \
"""<check name="%s">
    <category>%s</category>
    <package>%s</package>
    <version>%s</version>
    <msg>%s</msg>
</check>""" % (self.__class__.__name__, self.category, self.package,
    self.version, "unknown restricts- %s" % s)


class CrappyDescription(base.Result):
    
    """pkg's description sucks in some fashion"""

    __slots__ = ("category", "package", "version", "msg")

    def __init__(self, pkg, msg):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.msg = msg
    
    def to_str(self):
        return "%s/%s-%s: description: %s" % (self.category, self.package,
            self.version, self.msg)
    
    def to_xml(self):
        return \
"""<check name="%s">
    <category>%s</category>
    <package>%s</package>
    <version>%s</version>
    <msg>%s</msg>
</check>""" % (self.__class__.__name__, self.category, self.package, 
    self.version, self.msg)


class UnstatedIUSE(base.Result):
    """pkg is reliant on conditionals that aren't in IUSE"""
    __slots__ = ("category", "package", "version", "attr", "flags")
    
    def __init__(self, pkg, attr, flags):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.attr, self.flags = attr, tuple(flags)
    
    def to_str(self):
        return "%s/%s-%s: attr(%s) uses unstated flags [ %s ]" % \
        (self.category, self.package, self.version, self.attr,
            ", ".join(self.flags))

    def to_xml(self):
        return \
"""<check name="%s">
    <category>%s</category>
    <package>%s</package>
    <version>%s</version>
    <msg>attr %s uses unstead flags: %s"</msg>
</check>""" % (self.__class__.__name__, self.category, self.package,
    self.version, self.attr, ", ".join(self.flags))


class MissingUri(base.Result):
    """restrict=fetch isn't set, yet no full uri exists"""
    __slots__ = ("category", "package", "version", "filename")

    def __init__(self, pkg, filename):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.filename = filename
    
    def to_str(self):
        return "%s/%s-%s: no uri specified for %s and RESTRICT=fetch isn't on" \
            % (self.category, self.package, self.version, self.filename)
    
    def to_xml(self):
        return \
"""<check name="%s">
    <category>%s</category>
    <package>%s</package>
    <version>%s</version>
    <msg>no uri specified for %s</msg>
</check>""" % (self.__class__.__name__, self.category, self.package,
    self.version, escape(self.filename))


class BadProto(base.Result):
    """bad protocol"""
    __slots__ = ("category", "package", "version", "filename", "bad_uri")

    def __init__(self, pkg, filename, bad_uri):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.filename = filename
        self.bad_uri = bad_uri
    
    def to_str(self):
        return "%s/%s-%s: file %s, bad proto/uri- [ '%s' ]" % (self.category, 
            self.package, self.version, self.filename, 
                "', '".join(self.bad_uri))
    
    def to_xml(self):
        return \
"""<check name="%s">
    <category>%s</category>
    <package>%s</package>
    <version>%s</version>
    <msg>file %s has invalid uri- %s</msg>
</check>""" % (self.__class__.__name__, self.category, self.package,
    self.version, escape(self.filename), escape(", ".join(self.bad_uri)))


class MetadataError(base.Result):
    """problem detected with a packages metadata"""
    __slots__ = ("category", "package", "version", "attr", "msg")
    
    def __init__(self, pkg, attr, msg):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.attr, self.msg = attr, str(msg)
    
    def to_str(self):
        return "%s/%s-%s: attr(%s): %s" % (self.category, self.package,
            self.version, self.attr, self.msg)

    def to_xml(self):
        return \
"""<check name="%s">
    <category>%s</category>
    <package>%s</package>
    <version>%s</version>
    <msg>%s</msg>
</check>""" % (self.__class__.__name__, self.category, self.package,
    self.version,
    "attr '%s' threw an error- %s" % (self.attr, escape(self.msg)))


class EmptyKeywords(base.Result):
    """pkg has no set keywords"""

    __slots__ = ('category', 'package', 'version')

    def __init__(self, pkg):
        base.Result.__init__(self)
        self._store_cpv(pkg)

    def to_str(self):
        return "%s/%s-%s: no keywords set" % (self.category, self.package,
            self.version)
    
    def to_xml(self):
        return \
"""<check name="%s">
    <category>%s</category>
    <package>%s</package>
    <version>%s</version>
    <msg>no keywords set</msg>
</check>""" % (self.__class__.__name__, self.category, self.package,
    self.version)

        
class StupidKeywords(base.Result):
    """pkg that is using -*; package.mask in profiles addresses this already"""

    __slots__ = ('category', 'package', 'version')

    def __init__(self, pkg):
        base.Result.__init__(self)
        self._store_cpv(pkg)
    
    def to_str(self):
        return "%s/%s-%s: keywords contains -*, use package.mask instead" % \
            (self.category, self.package, self.version)
        
    def to_xml(self):
        return \
"""<check name="%s">
    <category>%s</category>
    <package>%s</package>
    <version>%s</version>
    <msg>keywords contains -*, should use package.mask</msg>
</check>""" % (self.__class__.__name__, self.category, self.package,
    self.version)
