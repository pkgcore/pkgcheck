from unittest.mock import patch

from pkgcore.test.misc import FakeRepo

from pkgcheck.checks import git as git_mod
from pkgcheck.git import GitCommit

from .. import misc


class FakeCommit(GitCommit):
    """Fake git commit objects with default values."""

    def __init__(self, **kwargs):
        commit_data =  {
            'hash': '7f9abd7ec2d079b1d0c36fc2f5d626ae0691757e',
            'commit_date': 'Sun Dec 8 02:13:58 2019 -0700',
            'author': 'author@domain.com',
            'committer': 'committer@domain.com',
            'message': (),
        }
        commit_data.update(kwargs)
        super().__init__(**commit_data)


class TestGitCheck(misc.ReportTestCase):
    check_kls = git_mod.GitCommitsCheck
    check = git_mod.GitCommitsCheck(misc.Options(target_repo=FakeRepo()))

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
                message=['summary', '', 'Signed-off-by: user@user.com']))

        # assert it can handle multiple sign offs.
        self.assertNoReport(
            self.check,
            FakeCommit(
                author='user1', committer='user2',
                message=['summary', '', 'Signed-off-by: user2', 'Signed-off-by: user1']))

    def SO_commit(self, summary='summary', body='', tags=(), **kwargs):
        """Create a commit object from summary, body, and tags components."""
        author = kwargs.pop('author', 'author@domain.com')
        committer = kwargs.pop('committer', 'author@domain.com')
        message = summary
        if body:
            message += '\n\n' + body
        sign_offs = tuple(f'Signed-off-by: {user}' for user in {author, committer})
        message += '\n\n' + '\n'.join(tuple(tags) + sign_offs)
        return FakeCommit(author=author, committer=committer, message=message.splitlines())

    def test_invalid_commit_tag(self):
        # assert it doesn't puke if there are no tags
        self.assertNoReport(self.check, self.SO_commit())

        self.assertNoReport(self.check, self.SO_commit(tags=['Bug: https://gentoo.org/blah']))
        self.assertNoReport(self.check, self.SO_commit(tags=['Close: https://gentoo.org/blah']))

        r = self.assertReport(self.check, self.SO_commit(tags=['Bug: 123455']))
        assert isinstance(r, git_mod.InvalidCommitTag)
        assert (r.tag, r.value, r.error) == ('Bug', '123455', "value isn't a URL")

        # Do a protocol check; this is more of an assertion against the parsing model
        # used in the implementation.
        r = self.assertReport(self.check, self.SO_commit(tags=['Closes: ftp://blah.com/asdf']))
        assert isinstance(r, git_mod.InvalidCommitTag)
        assert r.tag == 'Closes'
        assert 'protocol' in r.error

    def test_gentoo_bug_tag(self):
        commit = self.SO_commit(tags=['Gentoo-Bug: https://bugs.gentoo.org/1'])
        assert 'Gentoo-Bug tag is no longer valid' in self.assertReport(self.check, commit).error

    def test_commit_tags(self):
        ref = 'd8337304f09'

        for tag in ('Fixes', 'Reverts'):
            # no results on `git cat-file` failure
            with patch('subprocess.Popen') as git_cat:
                # force using a new `git cat-file` process for each iteration
                self.check._git_cat_file = None
                git_cat.return_value.poll.return_value = -1
                commit = self.SO_commit(tags=[f'{tag}: {ref}'])
                self.assertNoReport(self.check, commit)

            # missing and ambiguous object refs
            for status in ('missing', 'ambiguous'):
                self.check._git_cat_file = None
                with patch('subprocess.Popen') as git_cat:
                    git_cat.return_value.poll.return_value = None
                    git_cat.return_value.stdout.readline.return_value = f'{ref} {status}'
                    commit = self.SO_commit(tags=[f'{tag}: {ref}'])
                    r = self.assertReport(self.check, commit)
                    assert isinstance(r, git_mod.InvalidCommitTag)
                    assert f'{status} commit' in r.error

            # valid tag reference
            with patch('subprocess.Popen') as git_cat:
                self.check._git_cat_file = None
                git_cat.return_value.poll.return_value = None
                git_cat.return_value.stdout.readline.return_value = f'{ref} commit 1234'
                commit = self.SO_commit(tags=[f'{tag}: {ref}'])
                self.assertNoReport(self.check, commit)

    def test_summary_length(self):
        self.assertNoReport(self.check, self.SO_commit('single summary headline'))
        self.assertNoReport(self.check, self.SO_commit('a' * 69))
        assert 'summary is too long' in \
            self.assertReport(self.check, self.SO_commit('a' * 70)).error

    def test_message_body_length(self):
        # message body lines longer than 80 chars are flagged
        long_line = 'a' + ' b' * 40
        assert 'line 2 greater than 80 chars' in \
            self.assertReport(
                self.check,
                self.SO_commit(body=long_line)).error

        # but not non-word lines
        long_line = 'a' * 81
        self.assertNoReport(self.check, self.SO_commit(body=long_line))

    def test_message_empty_lines(self):

        self.assertNoReport(
            self.check,
            FakeCommit(author='author@domain.com', committer='author@domain.com', message="""\
foo

bar

Signed-off-by: author@domain.com
""".splitlines()))

        # missing empty line between summary and body
        assert 'missing empty line before body' in \
            self.assertReport(
                self.check,
                FakeCommit(author='author@domain.com', committer='author@domain.com', message="""\
foo
bar

Signed-off-by: author@domain.com
""".splitlines())).error

        # missing empty line between summary and tags
        assert 'missing empty line before tags' in \
            self.assertReport(
                self.check,
                FakeCommit(author='author@domain.com', committer='author@domain.com', message="""\
foo
Signed-off-by: author@domain.com
""".splitlines())).error

        # missing empty lines between summary, body, and tags
        reports = self.assertReports(
            self.check,
            FakeCommit(author='author@domain.com', committer='author@domain.com', message="""\
foo
bar
Signed-off-by: author@domain.com
""".splitlines()))

        assert 'missing empty line before body' in reports[0].error
        assert 'missing empty line before tags' in reports[1].error

    def test_footer_empty_lines(self):
        for whitespace in ('\t', ' ', ''):
            # empty lines in footer are flagged
            assert 'empty line 4 in footer' in \
                self.assertReport(
                    self.check,
                    FakeCommit(author='author@domain.com', committer='author@domain.com', message=f"""\
foon

blah: dar
{whitespace}
footer: yep
Signed-off-by: author@domain.com
""".splitlines())).error

            # empty lines at the end of a commit message are ignored
            self.assertNoReport(
                self.check,
                FakeCommit(author='author@domain.com', committer='author@domain.com', message=f"""\
foon

blah: dar
footer: yep
Signed-off-by: author@domain.com
{whitespace}
""".splitlines()))

    def test_footer_non_tags(self):
        assert 'non-tag in footer, line 5' in \
            self.assertReport(
                self.check,
                FakeCommit(author='author@domain.com', committer='author@domain.com', message=f"""\
foon

blah: dar
footer: yep
some random line
Signed-off-by: author@domain.com
""".splitlines())).error
