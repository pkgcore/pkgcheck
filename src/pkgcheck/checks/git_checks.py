from snakeoil.strings import pluralism as _pl

from .. import base


class DirectStableKeywords(base.Error):
    """Newly committed ebuild with stable keywords."""

    __slots__ = ('category', 'package', 'version', 'keywords')
    threshold = base.versioned_feed

    def __init__(self, pkg, keywords):
        super().__init__()
        self._store_cpv(pkg)
        self.keywords = tuple(keywords)

    @property
    def short_desc(self):
        return f'directly committed with stable keyword%s: [ %s ]' % (
            _pl(self.keywords), ', '.join(self.keywords))


class GitCommitsCheck(base.Template):
    """Check unpushed git commits for various issues."""

    feed_type = base.versioned_feed
    filter_type = base.git_filter
    known_results = (DirectStableKeywords,)

    def __init__(self, options):
        super().__init__(options)

    def feed(self, pkg, reporter):
        # TODO: check copyright on new/modified ebuilds for gentoo repo
        if pkg.status == 'A':
            try:
                match = self.options.target_repo.match(pkg.versioned_atom)[0]
                stable_keywords = sorted(x for x in match.keywords if x[0] not in '~-')
                if stable_keywords:
                    reporter.add_report(DirectStableKeywords(pkg, stable_keywords))
            except IndexError:
                # weird situation where an ebuild was locally committed and then removed
                pass
