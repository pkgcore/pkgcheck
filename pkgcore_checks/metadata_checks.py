# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

import logging, os, stat, errno
from operator import attrgetter
from pkgcore_checks import base

from pkgcore.util.demandload import demandload
from pkgcore.util.compatibility import any
from pkgcore.util.file import read_dict
from pkgcore.package.errors import MetadataException
from pkgcore.package.atom import MalformedAtom, atom
from pkgcore.util.lists import iflatten_instance
from pkgcore.util.iterables import expandable_chain
from pkgcore.fetch import fetchable
from pkgcore.restrictions import packages
from pkgcore.util.osutils import listdir_files
demandload(globals(), "pkgcore.util.xml:escape")

default_attrs = ("depends", "rdepends", "post_rdepends", "provides",
    "license", "fetchables", "iuse")

class MetadataReport(base.template):

    """ebuild metadata reports.
    
    DEPENDS, PDEPENDS, RDEPENDS, PROVIDES, SRC_URI, DESCRIPTION, LICENSE, etc.
    """

    feed_type = base.versioned_feed
    requires = base.arches_options + base.profile_options + \
        base.license_options
    
    def __init__(self, options):
        force_expansion = ("depends", "rdepends", "post_rdepends", "provides")
        self.attrs = [(a, attrgetter(a), a in force_expansion)
            for a in default_attrs]
        self.iuse_users = dict((x, attrgetter(x)) for x in 
            ("fetchables", "depends", "rdepends", "post_rdepends", "provides"))
        self.valid_iuse = None
        self.valid_unstated_iuse = None
        self.arches = options.arches
        self.profile_base = options.profile_base_dir
        self.licenses_dir = options.license_dir
    
    def feed(self, pkg, reporter):
        for attr_name, getter, force_expansion in self.attrs:
            try:
                o = getter(pkg)
                if force_expansion:
                    for d_atom in iflatten_instance(o, atom):
                        d_atom.key
                        d_atom.category
                        d_atom.package
                        if isinstance(d_atom, atom):
                            d_atom.restrictions
                if attr_name == "license":
                    if self.licenses is not None:
                        licenses = set(iflatten_instance(o, basestring)
                            ).difference(self.licenses)
                        if licenses:
                            reporter.add_report(MetadataError(pkg, "license",
                                "licenses don't exist- [ %s ]" %
                                    ", ".join(licenses)))
                    elif not o:
                        reporter.add_report(MetadataError(pkg, "license",
                            "no license defined"))
                elif attr_name == "iuse":
                    if self.valid_iuse is not None:
                        iuse = set(o).difference(self.valid_iuse)
                        if iuse:
                            reporter.add_report(MetadataError(pkg, "iuse", 
                                "iuse unknown flags- [ %s ]" % ", ".join(iuse)))
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

        if not pkg.keywords:
            reporter.add_report(EmptyKeywardsMinor(pkg))

        if "-*" in pkg.keywords:
            reporter.add_report(StupidKeywardsMinor(pkg))

        if self.valid_iuse is not None:
            used_iuse = set()
            skip_filter = (packages.Conditional, atom, basestring, fetchable)
            for attr_name, f in self.iuse_users.iteritems():
                i = expandable_chain(iflatten_instance(f(pkg), skip_filter))

                for node in i:
                    if not isinstance(node, packages.Conditional):
                        continue
                    # it's always a values.ContainmentMatch
                    used_iuse.update(node.restriction.vals)
                    i.append(iflatten_instance(node.payload, skip_filter))

                # the valid_unstated_iuse filters out USE_EXPAND as long as
                # it's listed in a desc file
                unstated = used_iuse.difference(pkg.iuse).difference(
                    self.arches).difference(self.valid_unstated_iuse)
                if unstated:
                    # hack, see bug 134994.
                    if unstated.difference(["bootstrap"]):
                        reporter.add_report(UnstatedIUSE(pkg, attr_name,
                            unstated))

    @staticmethod
    def load_valid_iuse(profile_base):
        known_iuse = set()
        unstated_iuse = set()
        pjoin = os.path.join
        fp = pjoin(profile_base, "use.desc")
        try:
            known_iuse.update(usef.strip() for usef in 
                read_dict(fp, None).iterkeys())
        except IOError, ie:
            if ie.errno != errno.ENOENT:
                raise

        fp = pjoin(profile_base, "use.local.desc")
        try:
            known_iuse.update(usef.rsplit(":", 1)[1].strip() for usef in 
                read_dict(fp, None).iterkeys())
        except IOError, ie:
            if ie.errno != errno.ENOENT:
                raise		

        use_expand_base = pjoin(profile_base, "desc")
        try:
            for entry in os.listdir(use_expand_base):
                try:
                    estr = entry.rsplit(".", 1)[0].lower()+ "_"
                    unstated_iuse.update(estr + usef.strip() for usef in 
                        read_dict(pjoin(use_expand_base, entry),
                            None).iterkeys())
                except (IOError, OSError), ie:
                    if ie.errno != errno.EISDIR:
                        raise
                    del ie
        except IOError, ie:
            if ie.errno != errno.ENOENT:
                raise
        known_iuse.update(unstated_iuse)
        return frozenset(known_iuse), frozenset(unstated_iuse)
            
    def start(self, repo, *a):
        # we are given extra args since we use profiles; don't care about it
        # however
        if any(x[0] == "license" for x in self.attrs):
            lfp = self.licenses_dir
            if not os.path.exists(lfp):
                logging.warn("disabling license checks- %s doesn't exist" % lfp)
                self.licenses = None
            else:
                self.licenses = frozenset(listdir_files(lfp))
        else:
            self.licenses = None
        if any(x[0] == "iuse" for x in self.attrs):
            self.valid_iuse, self.valid_unstated_iuse = \
                self.load_valid_iuse(self.profile_base)
        else:
            self.valid_iuse = self.valid_unstated_iuse = None


class SrcUriReport(base.template):
    """SRC_URI related checks.
    verify that it's a valid/fetchable uri, port 80,443,23"""
    feed_type = base.versioned_feed
    valid_protos = frozenset(["http", "https", "ftp"])

    def feed(self, pkg, reporter):
        lacks_uri = set()
        for f_inst in iflatten_instance(pkg.fetchables, fetchable):
            if not isinstance(f_inst, fetchable):
                continue
            elif f_inst.uri is None:
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
                    reporter.add_report(BadProto(pkg, f_inst.filename, bad))
        if not "fetch" in pkg.restrict:
            for x in lacks_uri:
                reporter.add_report(MissingUri(pkg, x))


class DescriptionReport(base.template):
    """DESCRIPTION checks.
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


class RestrictsReport(base.template):
    feed_type = base.versioned_feed
    known_restricts = frozenset(("confcache", "stricter", "mirror", "fetch", 
        "test", "sandbox", "userpriv", "primaryuri", "binchecks", "strip",
        "multilib-strict"))

    __doc__ = "check over RESTRICT, looking for unknown restricts\nvalid " \
        "restricts:%s" % ", ".join(sorted(known_restricts))
    
    def feed(self, pkg, reporter):
        bad = set(pkg.restrict).difference(self.known_restricts)
        if bad:
            deprecated = set(x for x in bad if x.startswith("no")
                and x[2:] in self.known_restricts)
            reporter.add_report(BadRestricts(pkg, bad.difference(deprecated),
                deprecated))


class BadRestricts(base.Result):
    """pkg's restrict metadata has unknown/deprecated entries"""
    
    __slots__ = ("category", "package", "version", "restricts", "deprecated")
    
    def __init__(self, pkg, restricts, deprecated=None):
        self._store_cpv(pkg)
        self.restricts = restricts
        self.deprecated = deprecated
        if not restricts and not deprecated:
            raise TypeError("deprecated or restricts must not be empty")
    
    def to_str(self):
        s = ''
        if self.restricts:
            s = "unknown restricts- [ %s ]" % ", ".join(self.restricts)
        if self.deprecated:
            if s:
                s+=", "
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
</check>""" % (self.__class__.__name__, self.category, self.package, self.version, self.msg)


class UnstatedIUSE(base.Result):
    """pkg is reliant on conditionals that aren't in IUSE"""
    __slots__ = ("category", "package", "version", "attr", "flags")
    
    def __init__(self, pkg, attr, flags):
        self.category, self.package, self.version = pkg.category, pkg.package, pkg.fullver
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
        self.category, self.package, self.version = pkg.category, pkg.package, pkg.fullver
        self.filename = filename
        self.bad_uri = bad_uri
    
    def to_str(self):
        return "%s/%s-%s: file %s, bad proto/uri- [ '%s' ]" % (self.category, self.package,
            self.version, self.filename, "', '".join(self.bad_uri))
    
    def to_xml(self):
        return \
"""<check name="%s">
    <category>%s</category>
    <package>%s</package>
    <version>%s</version>
    <msg>file %s has invalid uri- %s</msg>
</check>""" % (self.__class__.__name__, self.category, self.package, self.version, 
    escape(self.filename), escape(", ".join(self.bad_uri)))


class MetadataError(base.Result):
    """problem detected with a packages metadata"""
    __slots__ = ("category", "package", "version", "attr", "msg")
    
    def __init__(self, pkg, attr, msg):
        self.category, self.package, self.version = pkg.category, pkg.package, pkg.fullver
        self.attr, self.msg = attr, str(msg)
    
    def to_str(self):
        return "%s/%s-%s: attr(%s): %s" % (self.category, self.package, self.version, 
            self.attr, self.msg)

    def to_xml(self):
        return \
"""<check name="%s">
    <category>%s</category>
    <package>%s</package>
    <version>%s</version>
    <msg>%s</msg>
</check>""" % (self.__class__.__name__, self.category, self.package, self.version,
    "attr '%s' threw an error- %s" % (self.attr, escape(self.msg)))


class EmptyKeywardsMinor(base.Result):
    """pkg has no set keywords"""

    def __init__(self, pkg):
        self.category = pkg.category
        self.package = pkg.package
        self.version = pkg.fullver
    
    def to_str(self):
        return "%s/%s-%s: no keywords set" % (self.category, self.package, self.version)
    
    def to_xml(self):
        return \
"""<check name="%s">
    <category>%s</category>
    <package>%s</package>
    <version>%s</version>
    <msg>no keywords set</msg>
</check>""" % (self.__class__.__name__, self.category, self.package, self.version)

        
class StupidKeywardsMinor(base.Result):
    """pkg that is using -*; package.mask in profiles addresses this already"""
    
    def __init__(self, pkg):
        self.category = pkg.category
        self.package = pkg.package
        self.version = pkg.fullver
    
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
</check>""" % (self.__class__.__name__, self.category, self.package, self.version)
