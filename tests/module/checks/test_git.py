from pkgcheck.checks import git as git_mod
from .. import misc
from pkgcheck.git import GitCommit

def mk_commit(
        message,
        commit="7f9abd7ec2d079b1d0c36fc2f5d626ae0691757e",
        author="author@domain.com", committer="committer@domain.com",
        commit_date="Sun Dec 8 02:13:58 2019 -0700",
    ):
    return GitCommit(commit, commit_date, author, committer, message)


class TestGitCheck(misc.ReportTestCase):
    check_kls = git_mod.GitCommitsCheck
    check = git_mod.GitCommitsCheck(None)

    @staticmethod
    def commit(message, **kwargs):
        """Helper function to create commits and cleanup message

        Due to developer convenience, errant leading whitespace is
        in the messages- this will strip that out so tags are properly
        parsed.
        """
        return (mk_commit(tuple(x.lstrip() for x in message.splitlines()), **kwargs),)

    def test_sign_offs(self):
        # assert that it checks for both author and comitter
        r = self.assertReport(
            self.check,
            self.commit("blah", author="user1", committer="user2")
        )
        assert isinstance(r, git_mod.MissingSignOff)
        assert r.missing_sign_offs == ('user1', 'user2')

        # assert that it handles author/committer being the same
        self.assertNoReport(
            self.check,
            self.commit(
                "Signed-off-by: user@user.com",
                author="user@user.com", committer="user@user.com"))
        # assert it can handle multiple sign offs.
        self.assertNoReport(
            self.check,
            self.commit(
                "Signed-off-by: user2\nSigned-off-by: user1",
                author="user1", committer="user2"))

    def SO_commit(self, message, **kwargs):
        """Create a commit object with valid Signed-off-by tags"""
        author = kwargs.pop('author', 'user')
        committer = kwargs.pop('committer', 'user')
        return self.commit(
            message.rstrip() + "\n" + "\n".join(
                "Signed-off-by: {}".format(user) for user in [author, committer]),
            author=author,
            committer=committer
        )

    def test_invalid_tag_format(self):
        # assert it doesn't puke if there are no tags
        self.assertNoReport(self.check, self.SO_commit(""))

        self.assertNoReport(self.check, self.SO_commit("Bug: https://gentoo.org/blah"))
        self.assertNoReport(self.check, self.SO_commit("Close: https://gentoo.org/blah"))

        r = self.assertReport(self.check, self.SO_commit("Bug: 123455"))
        assert isinstance(r, git_mod.InvalidTagFormat)
        assert (r.tag, r.value, r.error) == ('Bug', '123455', "value isn't a URL")

        # do a protocol check; this is more of an assertion against the parsing model
        # used in the implementation.
        r = self.assertReport(self.check, self.SO_commit("Closes: ftp://blah.com/asdf"))
        assert isinstance(r, git_mod.InvalidTagFormat)
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