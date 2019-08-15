import os

from snakeoil.demandload import demandload
from snakeoil.strings import pluralism as _pl

from .. import base

demandload(
    'pkgcore.log:logger',
    'pkgcore.pkgsets.glsa:GlsaDirSet',
    'pkgcore.restrictions:packages,values',
    'pkgcore.restrictions.util:collect_package_restrictions',
    'snakeoil.osutils:abspath,pjoin',
)


class VulnerablePackage(base.VersionedResult, base.Error):
    """Packages marked as vulnerable by GLSAs."""

    __slots__ = ("arches", "glsa")

    def __init__(self, pkg, glsa):
        super().__init__(pkg)
        arches = set()
        for v in collect_package_restrictions(glsa, ["keywords"]):
            if isinstance(v.restriction, values.ContainmentMatch2):
                arches.update(x.lstrip("~") for x in v.restriction.vals)
            else:
                raise Exception(f"unexpected restriction sequence- {v.restriction} in {glsa}")
        keys = set(x.lstrip("~") for x in pkg.keywords if not x.startswith("-"))
        if arches:
            self.arches = tuple(sorted(arches.intersection(keys)))
            assert self.arches
        else:
            self.arches = tuple(sorted(keys))
        self.glsa = str(glsa)

    @property
    def short_desc(self):
        arches = ', '.join(self.arches)
        return f'vulnerable via {self.glsa}, keyword{_pl(self.arches)}: {arches}'


class TreeVulnerabilitiesCheck(base.Template):
    """Scan for vulnerable ebuilds in the tree.

    Requires a GLSA directory for vulnerability info.
    """

    feed_type = base.versioned_feed
    known_results = (VulnerablePackage,)

    @staticmethod
    def mangle_argparser(parser):
        parser.plugin.add_argument(
            "--glsa-dir", dest='glsa_location',
            help="source directory for glsas; tries to autodetermine it, may "
                 "be required if no glsa dirs are known")

    @classmethod
    def check_args(cls, parser, namespace):
        namespace.glsa_enabled = True
        glsa_loc = namespace.glsa_location
        if glsa_loc is not None:
            if not os.path.isdir(glsa_loc):
                parser.error(f"--glsa-dir {glsa_loc!r} doesn't exist")
        else:
            if not namespace.repo_bases:
                parser.error('a target repo or overlayed repo must be specified')
            for repo_base in namespace.repo_bases:
                candidate = pjoin(repo_base, "metadata", "glsa")
                if os.path.isdir(candidate):
                    if glsa_loc is None:
                        glsa_loc = candidate
                    else:
                        parser.error(
                            'multiple glsa sources is unsupported (detected '
                            f'{glsa_loc!r} and {candidate!r}). Pick one with --glsa-dir.')
            if glsa_loc is None:
                # force the error if explicitly selected using -c/--checks
                selected_checks = namespace.selected_checks
                if selected_checks is not None and cls.__name__ in selected_checks[1]:
                    parser.error(
                        "--glsa-dir must be specified, couldn't find glsa source")
                namespace.glsa_enabled = False
                if namespace.verbosity > 0:
                    logger.warn(
                        "disabling GLSA checks due to no glsa source "
                        "being found, and the check not being explicitly enabled; "
                        "this behaviour may change")
                return

        namespace.glsa_location = abspath(glsa_loc)

    def __init__(self, options):
        super().__init__(options)

        # this is a bit brittle
        self.vulns = {}
        if self.options.glsa_enabled:
            for r in GlsaDirSet(options.glsa_location):
                if len(r) > 2:
                    self.vulns.setdefault(
                        r[0].key, []).append(packages.AndRestriction(*r[1:]))
                else:
                    self.vulns.setdefault(r[0].key, []).append(r[1])

    def feed(self, pkg):
        for vuln in self.vulns.get(pkg.key, []):
            if vuln.match(pkg):
                yield VulnerablePackage(pkg, vuln)
