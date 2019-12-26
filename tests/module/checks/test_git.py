from pkgcheck.checks import git as git_mod
from .. import misc
from pkgcheck.git import _GitCommit

def mk_commit(
        message,
        commit="7f9abd7ec2d079b1d0c36fc2f5d626ae0691757e",
        author="author@domain.com", committer="committer@domain.com",
        commit_date="Sun Dec 8 02:13:58 2019 -0700",
    ):
    return _GitCommit(commit, commit_date, author, committer, message)


class TestGitCheck(misc.ReportTestCase):
    check_kls = git_mod.GitCommitsCheck
    check = git_mod.GitCommitsCheck(None)

    @staticmethod
    def commit(message, **kwargs):
        """Helper function to create commits and cleanup message

        Due to developer convenience, errant leading whitespace is
        in the messages- this will strip that out so tags are properly
        parsed."""
        return mk_commit(tuple(x.lstrip() for x in message.splitlines()), **kwargs)

    def test_sign_offs(self):
        # assert that it checks for both author and comitter
        r = self.assertReport(
            self.check,
            (self.commit("blah", author="user1", committer="user2"),)
        )
        assert isinstance(r, git_mod.MissingSignOff)
        assert r.missing_sign_offs == ('user1', 'user2')

        # assert that it handles author/committer being the same
        self.assertNoReport(
            self.check,
            (self.commit("Signed-off-by: user@user.com",
                author="user@user.com", committer="user@user.com"),
            )
        )

        # assert it can handle multiple sign offs.
        self.assertNoReport(
            self.check,
            (self.commit("Signed-off-by: user2\nSigned-off-by: user1",
                author="user1", committer="user2"),
            )
        )