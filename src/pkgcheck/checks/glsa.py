import os

from pkgcore.pkgsets.glsa import GlsaDirSet
from pkgcore.restrictions import packages, values
from pkgcore.restrictions.util import collect_package_restrictions
from snakeoil.cli.arghparse import existent_dir
from snakeoil.osutils import abspath, pjoin
from snakeoil.strings import pluralism as _pl

from .. import results
from ..log import logger
from . import GentooRepoCheck


class VulnerablePackage(results.VersionedResult, results.Error):
    """Packages marked as vulnerable by GLSAs."""

    def __init__(self, arches, glsa, **kwargs):
        super().__init__(**kwargs)
        self.arches = tuple(arches)
        self.glsa = glsa

    @property
    def desc(self):
        arches = ', '.join(self.arches)
        return f'vulnerable via {self.glsa}, keyword{_pl(self.arches)}: {arches}'


class GlsaCheck(GentooRepoCheck):
    """Scan for vulnerable ebuilds in the tree.

    Requires a GLSA directory for vulnerability info.
    """

    known_results = frozenset([VulnerablePackage])

    @staticmethod
    def mangle_argparser(parser):
        parser.plugin.add_argument(
            "--glsa-dir", dest='glsa_location', type=existent_dir,
            help="source directory for glsas; tries to autodetermine it, may "
                 "be required if no glsa dirs are known")

    @classmethod
    def check_args(cls, parser, namespace):
        namespace.glsa_enabled = True
        glsa_loc = namespace.glsa_location
        if glsa_loc is None:
            glsa_dirs = []
            for repo in namespace.target_repo.trees:
                path = pjoin(repo.location, 'metadata', 'glsa')
                if os.path.isdir(path):
                    glsa_dirs.append(path)
            if len(glsa_dirs) > 1:
                glsa_dirs = ', '.join(map(repr, glsa_dirs))
                parser.error(
                    '--glsa-dir needs to be specified to select one of '
                    f'multiple glsa sources: {glsa_dirs}')

            try:
                glsa_loc = glsa_dirs[0]
            except IndexError:
                # force the error if explicitly selected using -c/--checks
                selected_checks = namespace.selected_checks
                if selected_checks is not None and cls.__name__ in selected_checks[1]:
                    parser.error('no available glsa source, --glsa-dir must be specified')
                namespace.glsa_enabled = False
                if namespace.verbosity > 1:
                    logger.warning(
                        "disabling GLSA checks due to no glsa source "
                        "being found, and the check not being explicitly enabled")
                return

        namespace.glsa_location = abspath(glsa_loc)

    def __init__(self, *args):
        super().__init__(*args)

        # this is a bit brittle
        self.vulns = {}
        if self.options.glsa_enabled:
            for r in GlsaDirSet(self.options.glsa_location):
                if len(r) > 2:
                    self.vulns.setdefault(
                        r[0].key, []).append(packages.AndRestriction(*r[1:]))
                else:
                    self.vulns.setdefault(r[0].key, []).append(r[1])

    def feed(self, pkg):
        for vuln in self.vulns.get(pkg.key, []):
            if vuln.match(pkg):
                arches = set()
                for v in collect_package_restrictions(vuln, ['keywords']):
                    if isinstance(v.restriction, values.ContainmentMatch2):
                        arches.update(x.lstrip('~') for x in v.restriction.vals)
                    else:
                        raise Exception(
                            f'unexpected restriction sequence- {v.restriction} in {vuln}')
                keys = {x.lstrip('~') for x in pkg.keywords if not x.startswith('-')}
                if arches:
                    arches = sorted(arches.intersection(keys))
                    assert arches
                else:
                    arches = sorted(keys)
                yield VulnerablePackage(arches, str(vuln), pkg=pkg)
