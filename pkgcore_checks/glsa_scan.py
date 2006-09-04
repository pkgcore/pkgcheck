# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

import os, optparse

from pkgcore_checks import base
from pkgcore.pkgsets.glsa import GlsaDirSet
from pkgcore.restrictions.util import collect_package_restrictions
from pkgcore.restrictions import packages, values
from pkgcore.util.xml import escape


class GlsaLocationOption(base.FinalizingOption):

    def __init__(self):
        base.FinalizingOption.__init__(self, "--glsa-dir", action='store', type='string',
            dest='glsa_location', default=None, 
            help="source directoy for glsas; tries to autodetermine it, may be required if no glsa dirs are known")

    def finalize(self, options, runner):
        glsa_loc = options.glsa_location
        if glsa_loc is not None:
            if not os.path.isdir(glsa_loc):
                raise optparse.OptionValueError("--glsa-dir '%r' doesn't exist" % glsa_loc)
        else:
            glsa_loc = os.path.join(base.get_repo_base(options), "metadata", "glsa")
            if not os.path.isdir(glsa_loc):
                raise optparse.OptionValueError("--glsa-dir must be specified, couldn't identify glsa src from %r" % options.src_repo)

        options.glsa_location = base.abspath(glsa_loc)


GlsaLocation_option = GlsaLocationOption()


class TreeVulnerabilitiesReport(base.template):
    """Scan for vulnerabile ebuilds in the tree; requires a GLSA directory for vuln. info"""

    feed_type = base.versioned_feed
    requires = (GlsaLocation_option,)

    def __init__(self, options):
        self.glsa_dir = options.glsa_location	
    
    def start(self, repo):
        self.vulns = {}
        # this is a bit brittle
        for r in GlsaDirSet(self.glsa_dir):
            if len(r) > 2:
                self.vulns.setdefault(r[0].key, []).append(packages.AndRestriction(*r[1:]))
            else:
                self.vulns.setdefault(r[0].key, []).append(r[1])

    def finish(self, reporter):
        self.vulns.clear()
            
    def feed(self, pkg, reporter):
        for vuln in self.vulns.get(pkg.key, []):
            if vuln.match(pkg):
                reporter.add_report(VulnerablePackage(pkg, vuln))


class VulnerablePackage(base.Result):

    """Packages marked as vulnerable by GLSAs"""

    __slots__ = ("category", "package", "version", "arch", "glsa")

    def __init__(self, pkg, glsa):
        self.category = pkg.category
        self.package = pkg.package
        self.version = pkg.fullver
        arches = set()
        for v in collect_package_restrictions(glsa, ["keywords"]):
            if isinstance(v.restriction, values.ContainmentMatch):
                arches.update(x.lstrip("~") for x in v.restriction.vals)
            else:
                raise Exception("unexpected restriction sequence- %s in %s" % (v.restriction, glsa))
        keys = set(x.lstrip("~") for x in pkg.keywords if not x.startswith("-"))
        if arches:
            self.arch = tuple(sorted(arches.intersection(keys)))
            assert self.arch
        else:
            self.arch = tuple(sorted(keys))
        self.glsa = str(glsa)
    
    def to_str(self):
        return "%s/%s-%s: vulnerable via %s, affects %s" % (self.category, self.package, self.version, self.glsa, self.arch)

    def to_xml(self):
        return \
"""<check name="%s">
    <category>%s</category>
    <package>%s</package>
    <version>%s</version>
    <arch>%s</arch>
    <msg>vulnerable via %s</msg>
</check>""" % (self.__class__.__name__, self.category, self.package, self.version, 
"</arch>\n\t<arch>".join(self.arch), escape(self.glsa))
