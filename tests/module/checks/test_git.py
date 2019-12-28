from pkgcheck.checks import git as git_mod
from .. import misc
from pkgcheck.git import GitCommit


class FakeCommit(GitCommit):
    """Fake git commit objects with default values."""

    def __init__(self, **kwargs):
        commit_data =  {
            'commit': '7f9abd7ec2d079b1d0c36fc2f5d626ae0691757e',
            'commit_date': 'Sun Dec 8 02:13:58 2019 -0700',
            'author': 'author@domain.com',
            'committer': 'committer@domain.com',
            'message': (),
        }
        commit_data.update(kwargs)
        super().__init__(**commit_data)


class TestGitCheck(misc.ReportTestCase):
    check_kls = git_mod.GitCommitsCheck
    check = git_mod.GitCommitsCheck(None)

    def test_sign_offs(self):
        # assert that it checks for both author and comitter
        r = self.assertReport(
            self.check,
            FakeCommit(author='user1', committer='user2', message=['blah'])
        )
        assert isinstance(r, git_mod.MissingSignOff)
        assert r.missing_sign_offs == ('user1', 'user2')

        # assert that it handles author/committer being the same
        self.assertNoReport(
            self.check,
            FakeCommit(
                author='user@user.com', committer='user@user.com',
                message=['Signed-off-by: user@user.com']))

        # assert it can handle multiple sign offs.
        self.assertNoReport(
            self.check,
            FakeCommit(
                author='user1', committer='user2',
                message=['Signed-off-by: user2', 'Signed-off-by: user1']))

    def SO_commit(self, message, **kwargs):
        """Create a commit object with valid Signed-off-by tags"""
        author = kwargs.pop('author', 'user')
        committer = kwargs.pop('committer', 'user')
        sign_offs = [f'Signed-off-by: {user}' for user in (author, committer)]
        message = message.rstrip().splitlines() + [''] + sign_offs
        return FakeCommit(author=author, committer=committer, message=message)

    def test_invalid_tag_format(self):
        # assert it doesn't puke if there are no tags
        self.assertNoReport(self.check, self.SO_commit(""))

        self.assertNoReport(self.check, self.SO_commit("Bug: https://gentoo.org/blah"))
        self.assertNoReport(self.check, self.SO_commit("Close: https://gentoo.org/blah"))

        r = self.assertReport(self.check, self.SO_commit("Bug: 123455"))
        assert isinstance(r, git_mod.InvalidCommitTag)
        assert (r.tag, r.value, r.error) == ('Bug', '123455', "value isn't a URL")

        # Do a protocol check; this is more of an assertion against the parsing model
        # used in the implementation.
        r = self.assertReport(self.check, self.SO_commit("Closes: ftp://blah.com/asdf"))
        assert isinstance(r, git_mod.InvalidCommitTag)
        assert r.tag == 'Closes'
        assert "protocol" in r.error

    def test_gentoo_bug_tag(self):
        assert 'Bug:' in \
            self.assertReport(self.check, self.SO_commit('blah\nGentoo-Bug: foon')).error

    def test_commit_message_structure(self):
        self.assertNoReport(self.check, self.SO_commit('single summary headline'))
        assert "too long" in \
            self.assertReport(self.check, self.SO_commit("a "*40)).error
        assert "80 char" in \
            self.assertReport(
                self.check,
                self.SO_commit("asdf\n\n{}".format("a "*80))).error

        assert "non-footer block" in \
            self.assertReport(
                self.check,
                self.SO_commit("""foon

                    blah: dar
                    footer: yep
                    some random line
                    """)).error