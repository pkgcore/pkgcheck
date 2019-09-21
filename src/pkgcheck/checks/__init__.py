from .. import base, sources


class LatestPkgsCheck(base.Check):
    """Check that only runs against the latest non-VCS and VCS pkgs per slot by default.

    But runs against all matching packages in verbose mode.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.options.verbosity < 1:
            self.source = (
                sources.FilteredRepoSource, (base.LatestPkgsFilter,),
                (('source', self.source),))
