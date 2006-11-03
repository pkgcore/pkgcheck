# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

import os, optparse

from pkgcore_checks import base
from pkgcore.util.demandload import demandload
demandload(globals(), "pkgcore.pkgsets.glsa:GlsaDirSet "
    "pkgcore.restrictions:packages,values "
    "pkgcore.util:xml,osutils "
    "pkgcore.restrictions.util:collect_package_restrictions "
    "warnings ")


class TreeVulnerabilitiesReport(base.Template):
    """
    Scan for vulnerabile ebuilds in the tree
    
    requires a GLSA directory for vuln. info
    """

    feed_type = base.versioned_feed

    @staticmethod
    def mangle_option_parser(parser):
        parser.add_option(
            "--glsa-dir", action='store', type='string', dest='glsa_location',
            help="source directoy for glsas; tries to autodetermine it, may "
            "be required if no glsa dirs are known")

    @staticmethod
    def check_values(values):
        values.glsa_enabled = True
        glsa_loc = values.glsa_location
        if glsa_loc is not None:
            if not os.path.isdir(glsa_loc):
                raise optparse.OptionValueError("--glsa-dir '%r' doesn't "
                    "exist" % glsa_loc)
        else:
            if values.repo_base is None:
                raise optparse.OptionValueError(
                    'Need a target repo or --overlayed-repo that is a single '
                    'UnconfiguredTree for license checks')
            glsa_loc = os.path.join(values.repo_base, "metadata", "glsa")
            if not os.path.isdir(glsa_loc):
                # form of 'optional' limiting; if they are using -c, force the
                # error, else disable
                if values.checks_to_run:
                    raise optparse.OptionValueError("--glsa-dir must be "
                        "specified, couldn't identify glsa src from %r" %
                            values.src_repo)
                values.glsa_enabled = False
                warnings.warn("disabling GLSA checks due to no glsa source "
                    "being found, and the check not being explicitly enabled; "
                    "this behaviour may change")
                return

        values.glsa_location = osutils.abspath(glsa_loc)

    def __init__(self, options):
        base.Template.__init__(self, options)
        self.options = options
        self.glsa_dir = options.glsa_location
        self.enabled = False
        self.vulns = {}

    def feed(self, pkgs, reporter):
        self.enabled = self.options.glsa_enabled
        self.vulns.clear()
        if not self.enabled:
            return
        # this is a bit brittle
        for r in GlsaDirSet(self.glsa_dir):
            if len(r) > 2:
                self.vulns.setdefault(r[0].key, 
                    []).append(packages.AndRestriction(*r[1:]))
            else:
                self.vulns.setdefault(r[0].key, []).append(r[1])
        for pkg in pkgs:
            yield pkg
            if self.enabled:
                for vuln in self.vulns.get(pkg.key, []):
                    if vuln.match(pkg):
                        reporter.add_report(VulnerablePackage(pkg, vuln))
        self.vulns.clear()


class VulnerablePackage(base.Result):

    """Packages marked as vulnerable by GLSAs"""

    __slots__ = ("category", "package", "version", "arch", "glsa")

    def __init__(self, pkg, glsa):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        arches = set()
        for v in collect_package_restrictions(glsa, ["keywords"]):
            if isinstance(v.restriction, values.ContainmentMatch):
                arches.update(x.lstrip("~") for x in v.restriction.vals)
            else:
                raise Exception("unexpected restriction sequence- %s in %s" % 
                    (v.restriction, glsa))
        keys = set(x.lstrip("~") for x in pkg.keywords if not x.startswith("-"))
        if arches:
            self.arch = tuple(sorted(arches.intersection(keys)))
            assert self.arch
        else:
            self.arch = tuple(sorted(keys))
        self.glsa = str(glsa)
    
    def to_str(self):
        return "%s/%s-%s: vulnerable via %s, affects %s" % (self.category,
            self.package, self.version, self.glsa, self.arch)

    def to_xml(self):
        return \
"""<check name="%s">
    <category>%s</category>
    <package>%s</package>
    <version>%s</version>
    <arch>%s</arch>
    <msg>vulnerable via %s</msg>
</check>""" % (self.__class__.__name__, self.category, self.package,
    self.version, "</arch>\n\t<arch>".join(self.arch), xml.escape(self.glsa))
