import os
import textwrap
import time
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from pkgcheck.base import PkgcheckUserException
from pkgcheck.checks import git as git_mod
from pkgcheck.addons.git import GitCommit
from pkgcore.ebuild.cpv import VersionedCPV as CPV, UnversionedCPV as CP
from pkgcore.test.misc import FakeRepo
from snakeoil.cli import arghparse
from snakeoil.fileutils import touch
from snakeoil.osutils import pjoin

from ..misc import ReportTestCase, init_check


class FakeCommit(GitCommit):
    """Fake git commit objects with default values."""

    def __init__(self, **kwargs):
        commit_data = {
            "hash": "7f9abd7ec2d079b1d0c36fc2f5d626ae0691757e",
            "commit_time": 1613438722,
            "author": "author@domain.com",
            "committer": "author@domain.com",
            "message": (),
        }
        commit_data.update(kwargs)
        super().__init__(**commit_data)


class TestGitCommitMessageCheck(ReportTestCase):
    check_kls = git_mod.GitCommitMessageCheck
    options = arghparse.Namespace(target_repo=FakeRepo(), commits="origin", gentoo_repo=True)
    check = git_mod.GitCommitMessageCheck(options)

    def test_sign_offs(self):
        # assert that it checks for both author and committer
        r = self.assertReport(
            self.check, FakeCommit(author="user1", committer="user2", message=["blah"])
        )
        assert isinstance(r, git_mod.MissingSignOff)
        assert r.missing_sign_offs == ("user1", "user2")

        # assert that it handles author/committer being the same
        self.assertNoReport(
            self.check,
            FakeCommit(
                author="user@user.com",
                committer="user@user.com",
                message=["summary", "", "Signed-off-by: user@user.com"],
            ),
        )

        # assert it can handle multiple sign offs.
        self.assertNoReport(
            self.check,
            FakeCommit(
                author="user1",
                committer="user2",
                message=["summary", "", "Signed-off-by: user2", "Signed-off-by: user1"],
            ),
        )

    def SO_commit(self, summary="summary", body="", tags=(), **kwargs):
        """Create a commit object from summary, body, and tags components."""
        author = kwargs.pop("author", "author@domain.com")
        committer = kwargs.pop("committer", "author@domain.com")
        message = summary
        if message:
            if body:
                message += "\n\n" + body
            sign_offs = tuple(f"Signed-off-by: {user}" for user in {author, committer})
            message += "\n\n" + "\n".join(tuple(tags) + sign_offs)
        return FakeCommit(author=author, committer=committer, message=message.splitlines())

    def test_invalid_commit_tag(self):
        # assert it doesn't puke if there are no tags
        self.assertNoReport(self.check, self.SO_commit())

        self.assertNoReport(self.check, self.SO_commit(tags=["Bug: https://gentoo.org/blah"]))
        self.assertNoReport(self.check, self.SO_commit(tags=["Close: https://gentoo.org/blah"]))

        r = self.assertReport(self.check, self.SO_commit(tags=["Bug: 123455"]))
        assert isinstance(r, git_mod.InvalidCommitTag)
        assert (r.tag, r.value, r.error) == ("Bug", "123455", "value isn't a URL")

        # Do a protocol check; this is more of an assertion against the parsing model
        # used in the implementation.
        r = self.assertReport(self.check, self.SO_commit(tags=["Closes: ftp://blah.com/asdf"]))
        assert isinstance(r, git_mod.InvalidCommitTag)
        assert r.tag == "Closes"
        assert "protocol" in r.error

    def test_gentoo_bug_tag(self):
        commit = self.SO_commit(tags=["Gentoo-Bug: https://bugs.gentoo.org/1"])
        assert "Gentoo-Bug tag is no longer valid" in self.assertReport(self.check, commit).error

    def test_commit_tags(self):
        ref = "d8337304f09"

        for tag in ("Fixes", "Reverts"):
            # no results on `git cat-file` failure
            with patch("pkgcheck.checks.git.subprocess.Popen") as git_cat:
                # force using a new `git cat-file` process for each iteration
                self.check._git_cat_file = None
                git_cat.return_value.poll.return_value = -1
                commit = self.SO_commit(tags=[f"{tag}: {ref}"])
                self.assertNoReport(self.check, commit)

            # missing and ambiguous object refs
            for status in ("missing", "ambiguous"):
                self.check._git_cat_file = None
                with patch("pkgcheck.checks.git.subprocess.Popen") as git_cat:
                    git_cat.return_value.poll.return_value = None
                    git_cat.return_value.stdout.readline.return_value = f"{ref} {status}"
                    commit = self.SO_commit(tags=[f"{tag}: {ref}"])
                    r = self.assertReport(self.check, commit)
                    assert isinstance(r, git_mod.InvalidCommitTag)
                    assert f"{status} commit" in r.error

            # valid tag reference
            with patch("pkgcheck.checks.git.subprocess.Popen") as git_cat:
                self.check._git_cat_file = None
                git_cat.return_value.poll.return_value = None
                git_cat.return_value.stdout.readline.return_value = f"{ref} commit 1234"
                commit = self.SO_commit(tags=[f"{tag}: {ref}"])
                self.assertNoReport(self.check, commit)

    def test_summary_length(self):
        self.assertNoReport(self.check, self.SO_commit("single summary headline"))
        self.assertNoReport(self.check, self.SO_commit("a" * 69))
        assert "no commit message" in self.assertReport(self.check, self.SO_commit("")).error
        assert (
            "summary is too long" in self.assertReport(self.check, self.SO_commit("a" * 70)).error
        )

    def test_message_body_length(self):
        # message body lines longer than 80 chars are flagged
        long_line = "a" + " b" * 40
        assert (
            "line 2 greater than 80 chars"
            in self.assertReport(self.check, self.SO_commit(body=long_line)).error
        )

        # but not non-word lines
        long_line = "a" * 81
        self.assertNoReport(self.check, self.SO_commit(body=long_line))

    def test_message_empty_lines(self):
        message = textwrap.dedent(
            """\
                foo

                bar

                Signed-off-by: author@domain.com
            """
        ).splitlines()
        commit = FakeCommit(message=message)
        self.assertNoReport(self.check, commit)

        # missing empty line between summary and body
        message = textwrap.dedent(
            """\
                foo
                bar

                Signed-off-by: author@domain.com
            """
        ).splitlines()
        commit = FakeCommit(message=message)
        r = self.assertReport(self.check, commit)
        assert "missing empty line before body" in str(r)

        # missing empty line between summary and tags
        message = textwrap.dedent(
            """\
                foo
                Signed-off-by: author@domain.com
            """
        ).splitlines()
        commit = FakeCommit(message=message)
        r = self.assertReport(self.check, commit)
        assert "missing empty line before tags" in str(r)

        # missing empty lines between summary, body, and tags
        message = textwrap.dedent(
            """\
                foo
                bar
                Signed-off-by: author@domain.com
            """
        ).splitlines()
        commit = FakeCommit(message=message)
        reports = self.assertReports(self.check, commit)
        assert "missing empty line before body" in str(reports[0])
        assert "missing empty line before tags" in str(reports[1])

    def test_footer_empty_lines(self):
        for whitespace in ("\t", " ", ""):
            # empty lines in footer are flagged
            message = textwrap.dedent(
                f"""\
                    foon

                    blah: dar
                    {whitespace}
                    footer: yep
                    Signed-off-by: author@domain.com
                """
            ).splitlines()
            commit = FakeCommit(message=message)
            r = self.assertReport(self.check, commit)
            assert "empty line 4 in footer" in str(r)

            # empty lines at the end of a commit message are ignored
            message = textwrap.dedent(
                f"""\
                    foon

                    blah: dar
                    footer: yep
                    Signed-off-by: author@domain.com
                    {whitespace}
                """
            ).splitlines()
            commit = FakeCommit(message=message)
            self.assertNoReport(self.check, commit)

    def test_footer_non_tags(self):
        message = textwrap.dedent(
            """\
                foon

                blah: dar
                footer: yep
                some random line
                Signed-off-by: author@domain.com
            """
        ).splitlines()
        commit = FakeCommit(message=message)
        r = self.assertReport(self.check, commit)
        assert "non-tag in footer, line 5" in str(r)


class TestGitCommitMessageRepoCheck(ReportTestCase):
    check_kls = git_mod.GitCommitMessageCheck

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, tool, make_repo, make_git_repo):
        self._tool = tool
        self.cache_dir = str(tmp_path)

        # initialize parent repo
        self.parent_git_repo = make_git_repo()
        self.parent_repo = make_repo(self.parent_git_repo.path, repo_id="gentoo", arches=["amd64"])
        self.parent_git_repo.add_all("initial commit")
        # create a stub pkg and commit it
        self.parent_repo.create_ebuild("cat/pkg-0")
        self.parent_git_repo.add_all("cat/pkg-0")

        # initialize child repo
        self.child_git_repo = make_git_repo()
        self.child_git_repo.run(["git", "remote", "add", "origin", self.parent_git_repo.path])
        self.child_git_repo.run(["git", "pull", "origin", "main"])
        self.child_git_repo.run(["git", "remote", "set-head", "origin", "main"])
        self.child_repo = make_repo(self.child_git_repo.path)

    def init_check(self, options=None, future=0):
        self.options = options if options is not None else self._options()
        self.check, required_addons, self.source = init_check(self.check_kls, self.options)
        for k, v in required_addons.items():
            setattr(self, k, v)
        if future:
            self.check.today = datetime.today() + timedelta(days=+future)

    def _options(self, **kwargs):
        args = [
            "scan",
            "-q",
            "--cache-dir",
            self.cache_dir,
            "--repo",
            self.child_repo.location,
            "--commits",
        ]
        options, _ = self._tool.parse_args(args)
        return options

    def test_bad_commit_summary_pkg(self):
        # properly prefixed commit summary
        self.child_repo.create_ebuild("cat/pkg-1")
        self.child_git_repo.add_all("cat/pkg: version bump to 1", signoff=True)
        self.init_check()
        self.assertNoReport(self.check, self.source)

        # properly prefixed multiple ebuild commit summary
        self.child_repo.create_ebuild("cat/pkg-2")
        self.child_repo.create_ebuild("cat/pkg-3")
        self.child_git_repo.add_all("cat/pkg: more version bumps", signoff=True)
        self.init_check()
        self.assertNoReport(self.check, self.source)

        # special categories that allow not having version in new package summary
        self.child_repo.create_ebuild("acct-user/pkgcheck-1")
        self.child_git_repo.add_all("acct-user/pkgcheck: add user for pkgcheck", signoff=True)
        self.init_check()
        self.assertNoReport(self.check, self.source)

        # special categories that allow not having version in bump version summary
        self.child_repo.create_ebuild("acct-user/pkgcheck-2")
        self.child_git_repo.add_all("acct-user/pkgcheck: bump user for pkgcheck", signoff=True)
        self.init_check()
        self.assertNoReport(self.check, self.source)

        # poorly prefixed commit summary
        self.child_repo.create_ebuild("cat/pkg-4")
        self.child_git_repo.add_all("version bump to 4", signoff=True)
        commit1 = self.child_git_repo.HEAD
        # commit summary missing package version
        self.child_repo.create_ebuild("cat/pkg-5")
        self.child_git_repo.add_all("cat/pkg: version bump", signoff=True)
        commit2 = self.child_git_repo.HEAD
        # commit summary missing renamed package version
        self.child_git_repo.move(
            "cat/pkg/pkg-3.ebuild",
            "cat/pkg/pkg-6.ebuild",
            msg="cat/pkg: version bump and remove old",
            signoff=True,
        )
        commit3 = self.child_git_repo.HEAD
        # revision bumps aren't flagged
        self.child_repo.create_ebuild("cat/pkg-6-r1")
        self.child_git_repo.add_all("cat/pkg: revision bump", signoff=True)
        self.init_check()
        # allow vVERSION
        self.child_repo.create_ebuild("cat/pkg-7")
        self.child_git_repo.add_all("cat/pkg: bump to v7", signoff=True)
        self.init_check()
        results = self.assertReports(self.check, self.source)
        r1 = git_mod.BadCommitSummary(
            "summary missing 'cat/pkg' package prefix", "version bump to 4", commit=commit1
        )
        r2 = git_mod.BadCommitSummary(
            "summary missing package version '5'", "cat/pkg: version bump", commit=commit2
        )
        r3 = git_mod.BadCommitSummary(
            "summary missing package version '6'",
            "cat/pkg: version bump and remove old",
            commit=commit3,
        )
        assert set(results) == {r1, r2, r3}

    def test_bad_commit_summary_category(self):
        # properly prefixed commit summary
        self.child_repo.create_ebuild("cat/pkg1-1")
        self.child_repo.create_ebuild("cat/pkg2-1")
        self.child_git_repo.add_all("cat: various pkg updates", signoff=True)
        self.init_check()
        self.assertNoReport(self.check, self.source)

        # multiple category commits are ignored
        self.child_repo.create_ebuild("newcat1/newcat1-1")
        self.child_repo.create_ebuild("newcat2/newpkg2-1")
        self.child_git_repo.add_all("various changes", signoff=True)
        self.init_check()
        self.assertNoReport(self.check, self.source)

        # poorly prefixed commit summary for single category changes
        self.child_repo.create_ebuild("cat/pkg3-1")
        self.child_repo.create_ebuild("cat/pkg4-1")
        self.child_git_repo.add_all("cat updates", signoff=True)
        commit = self.child_git_repo.HEAD
        self.init_check()
        r = self.assertReport(self.check, self.source)
        expected = git_mod.BadCommitSummary(
            "summary missing 'cat' category prefix", "cat updates", commit=commit
        )
        assert r == expected


class TestGitPkgCommitsCheck(ReportTestCase):
    check_kls = git_mod.GitPkgCommitsCheck

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, tool, make_repo, make_git_repo):
        self._tool = tool
        self.cache_dir = str(tmp_path)

        # initialize parent repo
        self.parent_git_repo = make_git_repo()
        self.parent_repo = make_repo(self.parent_git_repo.path, repo_id="gentoo", arches=["amd64"])
        os.makedirs(pjoin(self.parent_git_repo.path, "profiles/desc"), exist_ok=True)
        with open(pjoin(self.parent_git_repo.path, "profiles/desc/python_targets.desc"), "w") as f:
            f.write("python3_10 - Build with Python 3.10\n")
            f.write("python3_11 - Build with Python 3.11\n")
        self.parent_git_repo.add_all("initial commit")
        # create a stub pkg and commit it
        self.parent_repo.create_ebuild("cat/pkg-0", eapi="7")
        self.parent_git_repo.add_all("cat/pkg-0")

        # initialize child repo
        self.child_git_repo = make_git_repo()
        self.child_git_repo.run(["git", "remote", "add", "origin", self.parent_git_repo.path])
        self.child_git_repo.run(["git", "pull", "origin", "main"])
        self.child_git_repo.run(["git", "remote", "set-head", "origin", "main"])
        self.child_repo = make_repo(self.child_git_repo.path)

    def init_check(self, options=None, future=0):
        self.options = options if options is not None else self._options()
        self.check, required_addons, self.source = init_check(self.check_kls, self.options)
        for k, v in required_addons.items():
            setattr(self, k, v)
        if future:
            self.check.today = datetime.today() + timedelta(days=+future)

    def _options(self, **kwargs):
        args = [
            "scan",
            "-q",
            "--cache-dir",
            self.cache_dir,
            "--repo",
            self.child_repo.location,
            "--commits",
        ]
        options, _ = self._tool.parse_args(args)
        return options

    def test_broken_ebuilds_ignored(self):
        self.child_repo.create_ebuild("newcat/pkg-1", eapi="-1")
        self.child_git_repo.add_all("newcat/pkg: initial import")
        self.init_check()
        self.assertNoReport(self.check, self.source)

    def test_direct_stable(self):
        self.child_repo.create_ebuild("cat/pkg-1", keywords=["amd64"])
        self.child_git_repo.add_all("cat/pkg: version bump to 1")
        self.init_check()
        r = self.assertReport(self.check, self.source)
        expected = git_mod.DirectStableKeywords(["amd64"], pkg=CPV("cat/pkg-1"))
        assert r == expected

    def test_direct_no_maintainer(self):
        self.child_repo.create_ebuild("newcat/pkg-1")
        self.child_git_repo.add_all("newcat/pkg: initial import")
        self.init_check()
        r = self.assertReport(self.check, self.source)
        expected = git_mod.DirectNoMaintainer(pkg=CPV("newcat/pkg-1"))
        assert r == expected

    def test_ebuild_incorrect_copyright(self):
        self.child_repo.create_ebuild("cat/pkg-1")
        line = "# Copyright 1999-2019 Gentoo Authors"
        with open(pjoin(self.child_git_repo.path, "cat/pkg/pkg-1.ebuild"), "r+") as f:
            lines = f.read().splitlines()
            lines[0] = line
            f.seek(0)
            f.truncate()
            f.write("\n".join(lines))
        self.child_git_repo.add_all("cat/pkg: version bump to 1")
        self.init_check()
        r = self.assertReport(self.check, self.source)
        expected = git_mod.EbuildIncorrectCopyright("2019", line=line, pkg=CPV("cat/pkg-1"))
        assert r == expected

    def test_missing_copyright(self):
        """Ebuilds missing copyrights entirely are handled by EbuildHeaderCheck."""
        self.child_repo.create_ebuild("cat/pkg-1")
        with open(pjoin(self.child_git_repo.path, "cat/pkg/pkg-1.ebuild"), "r+") as f:
            lines = f.read().splitlines()
            f.seek(0)
            f.truncate()
            f.write("\n".join(lines[1:]))
        self.child_git_repo.add_all("cat/pkg: update ebuild")
        self.init_check()
        self.assertNoReport(self.check, self.source)

    def test_dropped_stable_keywords(self):
        # add stable ebuild to parent repo
        self.parent_repo.create_ebuild("cat/pkg-1", keywords=["amd64"])
        self.parent_git_repo.add_all("cat/pkg: version bump to 1")
        # pull changes and remove it from the child repo
        self.child_git_repo.run(["git", "pull", "origin", "main"])
        self.child_git_repo.remove("cat/pkg/pkg-1.ebuild", msg="cat/pkg: remove 1")
        commit = self.child_git_repo.HEAD
        self.init_check()
        r = self.assertReport(self.check, self.source)
        expected = git_mod.DroppedStableKeywords(["amd64"], commit, pkg=CPV("cat/pkg-1"))
        assert r == expected

        # git archive failures error out
        with patch("pkgcheck.checks.git.subprocess.Popen") as git_archive:
            git_archive.return_value.poll.return_value = -1
            with pytest.raises(PkgcheckUserException, match="failed populating archive repo"):
                self.assertNoReport(self.check, self.source)

    def test_dropped_unstable_keywords(self):
        # add stable ebuild to parent repo
        self.parent_repo.create_ebuild("cat/pkg-1", keywords=["~amd64"])
        self.parent_git_repo.add_all("cat/pkg: version bump to 1")
        # pull changes and remove it from the child repo
        self.child_git_repo.run(["git", "pull", "origin", "main"])
        self.child_git_repo.remove("cat/pkg/pkg-1.ebuild", msg="cat/pkg: remove 1")
        commit = self.child_git_repo.HEAD
        self.init_check()
        r = self.assertReport(self.check, self.source)
        expected = git_mod.DroppedUnstableKeywords(["~amd64"], commit, pkg=CPV("cat/pkg-1"))
        assert r == expected

    def test_dropped_keywords_inherit_eclass(self):
        # add stable ebuild to parent repo
        with open(pjoin(self.parent_git_repo.path, "eclass/make.eclass"), "w") as f:
            f.write(":")
        self.parent_git_repo.add_all("make.eclass: initial commit")
        self.parent_repo.create_ebuild("cat/pkg-1", keywords=["~amd64"], data="inherit make")
        self.parent_git_repo.add_all("cat/pkg: version bump to 1")
        # pull changes and remove it from the child repo
        self.child_git_repo.run(["git", "pull", "origin", "main"])
        self.child_git_repo.remove("cat/pkg/pkg-1.ebuild", msg="cat/pkg: remove 1")
        commit = self.child_git_repo.HEAD
        self.init_check()
        r = self.assertReport(self.check, self.source)
        expected = git_mod.DroppedUnstableKeywords(["~amd64"], commit, pkg=CPV("cat/pkg-1"))
        assert r == expected

    def test_rdepend_change(self):
        # add pkgs to parent repo
        self.parent_repo.create_ebuild("cat/dep1-0")
        self.parent_git_repo.add_all("cat/dep1: initial import")
        self.parent_repo.create_ebuild("cat/dep2-0")
        self.parent_git_repo.add_all("cat/dep2: initial import")
        self.parent_repo.create_ebuild("newcat/newpkg-1")
        self.parent_git_repo.add_all("newcat/newpkg: initial import")
        self.parent_repo.create_ebuild("newcat/newpkg-2", rdepend="cat/dep1 cat/dep2")
        self.parent_git_repo.add_all("newcat/newpkg: version bump")
        # pull changes to child repo
        self.child_git_repo.run(["git", "pull", "origin", "main"])
        # change pkg RDEPEND and commit
        with open(pjoin(self.child_git_repo.path, "cat/pkg/pkg-0.ebuild"), "a") as f:
            f.write('RDEPEND="cat/dep1"\n')
        self.child_git_repo.add_all("cat/pkg: update deps")
        # change live pkg RDEPEND and commit
        with open(pjoin(self.child_git_repo.path, "newcat/newpkg/newpkg-1.ebuild"), "a") as f:
            f.write('RDEPEND="cat/dep1"\n')
            f.write('PROPERTIES="live"\n')
        self.child_git_repo.add_all("newcat/newpkg: update deps")
        # reorder pkg RDEPEND and commit
        with open(pjoin(self.child_git_repo.path, "newcat/newpkg/newpkg-2.ebuild"), "a") as f:
            f.write('RDEPEND="cat/dep2 cat/dep1"\n')
        self.child_git_repo.add_all("newcat/newpkg: reorder deps")
        self.init_check()
        r = self.assertReport(self.check, self.source)
        # only one result is expected since live ebuilds are ignored
        expected = git_mod.RdependChange(pkg=CPV("cat/pkg-0"))
        assert r == expected

    def test_missing_slotmove(self):
        # add new ebuild to parent repo
        self.parent_repo.create_ebuild("cat/pkg-1", keywords=["~amd64"])
        self.parent_git_repo.add_all("cat/pkg: version bump to 1")
        # pull changes and modify its slot in the child repo
        self.child_git_repo.run(["git", "pull", "origin", "main"])
        self.child_repo.create_ebuild("cat/pkg-1", keywords=["~amd64"], slot="1")
        self.child_git_repo.add_all("cat/pkg: update SLOT to 1")
        self.init_check()
        r = self.assertReport(self.check, self.source)
        expected = git_mod.MissingSlotmove("0", "1", pkg=CPV("cat/pkg-1"))
        assert r == expected

        # create slot move update and the result goes away
        updates_dir = pjoin(self.child_git_repo.path, "profiles", "updates")
        os.makedirs(updates_dir, exist_ok=True)
        with open(pjoin(updates_dir, "4Q-2020"), "w") as f:
            f.write(
                textwrap.dedent(
                    """\
                        slotmove ~cat/foo-0 0 1
                        slotmove ~cat/pkg-1 0 1
                    """
                )
            )
        # force repo_config pkg updates jitted attr to be reset
        self.init_check()
        self.assertNoReport(self.check, self.source)

        # git archive failures error out
        with patch("pkgcheck.checks.git.subprocess.Popen") as git_archive:
            git_archive.return_value.poll.return_value = -1
            with pytest.raises(PkgcheckUserException, match="failed populating archive repo"):
                self.assertNoReport(self.check, self.source)

    def test_missing_move(self):
        # verify ebuild renames at the git level don't trigger
        self.child_repo.create_ebuild("cat/pkg-1")
        self.child_git_repo.run(["git", "rm", "cat/pkg/pkg-0.ebuild"])
        self.child_git_repo.add_all("cat/pkg: version bump and remove old")
        self.init_check()
        self.assertNoReport(self.check, self.source)

        self.child_git_repo.move("cat", "newcat", msg="newcat/pkg: moved pkg")
        self.init_check()
        r = self.assertReport(self.check, self.source)
        expected = git_mod.MissingMove("cat/pkg", "newcat/pkg", pkg=CPV("newcat/pkg-0"))
        assert r == expected

        # create package move update and the result goes away
        updates_dir = pjoin(self.child_git_repo.path, "profiles", "updates")
        os.makedirs(updates_dir, exist_ok=True)
        with open(pjoin(updates_dir, "4Q-2020"), "w") as f:
            f.write(
                textwrap.dedent(
                    """\
                        move cat/foo newcat/foo
                        move cat/pkg newcat/pkg
                    """
                )
            )
        # force repo_config pkg updates jitted attr to be reset
        self.init_check()
        self.assertNoReport(self.check, self.source)

    def test_revision_move(self):
        self.parent_git_repo.move(
            "cat/pkg/pkg-0.ebuild",
            "cat/pkg/pkg-0-r1.ebuild",
            msg="cat/pkg: some random fixes",
        )
        self.parent_repo.create_ebuild("cat/newpkg-0-r1", keywords=["~amd64"])
        self.parent_git_repo.add_all("cat/newpkg: new package, v0")

        self.child_git_repo.run(["git", "pull", "origin", "main"])
        self.child_git_repo.run(["git", "remote", "set-head", "origin", "main"])

        # moving revision version won't crash check
        self.child_git_repo.move(
            "cat/pkg/pkg-0-r1.ebuild",
            "cat/pkg/pkg-0-r2.ebuild",
            msg="cat/pkg: some extra random fixes",
            signoff=True,
        )
        self.child_git_repo.move(
            "cat/newpkg/newpkg-0-r1.ebuild",
            "cat/newpkg/newpkg-0-r2.ebuild",
            msg="cat/newpkg: some random fixes",
            signoff=True,
        )

        self.init_check()
        self.assertNoReport(self.check, self.source)

    def test_checksum_change(self):
        distfile = [
            "DIST",
            "pkgcheck-1.tar.gz",
            "549746",
            "BLAKE2B",
            "72ed97d93674ffd311978d03ad3738494a752bf1b02bea5eaaaf1b066c48e8c9ec5f82b79baeeabf3e56e618c76614ee6179b7115d1d875364ac6e3fbc3c6028",
            "SHA512",
            "6a8c135ca44ccbfe15548bd396aba9448c29f60147920b18b8be5aa5fcd1200e0b75bc5de50fc7892ad5460ddad1e7d28a7e44025bdc581a518d136eda8b0df2",
        ]
        with open(pjoin(self.parent_repo.path, "profiles/thirdpartymirrors"), "a") as f:
            f.write("gentoo  https://gentoo.org/distfiles\n")
        self.parent_repo.create_ebuild("cat/pkg-1", src_uri=f"mirror://gentoo/{distfile[1]}")
        with open(pjoin(self.parent_repo.path, "cat/pkg/Manifest"), "w") as f:
            f.write(" ".join(distfile) + "\n")
        self.parent_git_repo.add_all("cat/pkg: add 1", signoff=True)
        # pull changes and change checksum in child repo
        self.child_git_repo.run(["git", "pull", "origin", "main"])
        self.child_repo.create_ebuild("cat/pkg-1-r1", src_uri=f"mirror://gentoo/{distfile[1]}")
        distfile[-1] = distfile[-1][:-1] + "0"
        with open(pjoin(self.child_repo.path, "cat/pkg/Manifest"), "w") as f:
            f.write(" ".join(distfile) + "\n")
        self.child_git_repo.add_all("cat/pkg: revbump", signoff=True)
        self.init_check()
        r = self.assertReport(self.check, self.source)
        assert r == git_mod.SrcUriChecksumChange(distfile[1], pkg=CP("cat/pkg"))

    def test_python_pep517_change(self):
        with open(pjoin(self.parent_git_repo.path, "eclass/distutils-r1.eclass"), "w") as f:
            f.write("# Copyright 1999-2019 Gentoo Authors")
        self.parent_git_repo.add_all("eclass: add distutils-r1")

        # add pkgs to parent repo
        self.parent_repo.create_ebuild("newcat/newpkg-1", data="inherit distutils-r1")
        self.parent_git_repo.add_all("newcat/newpkg: initial import")
        # pull changes to child repo
        self.child_git_repo.run(["git", "pull", "origin", "main"])
        # change an existing ebuild to have DISTUTILS_USE_PEP517 with no revbump
        with open(pjoin(self.child_git_repo.path, "newcat/newpkg/newpkg-1.ebuild"), "a") as f:
            f.write("\nDISTUTILS_USE_PEP517=setuptools\n")
        self.child_git_repo.add_all("newcat/newpkg: use PEP517")
        self.init_check()
        r = self.assertReport(self.check, self.source)
        expected = git_mod.PythonPEP517WithoutRevbump(pkg=CPV("newcat/newpkg-1"))
        assert r == expected

    def test_eapi_change(self):
        # bump eapi
        self.child_repo.create_ebuild("cat/pkg-0", eapi="8")
        self.child_git_repo.add_all("cat/pkg-0")
        # pull changes to child repo
        self.init_check()
        r = self.assertReport(self.check, self.source)
        expected = git_mod.EAPIChangeWithoutRevbump(pkg=CPV("cat/pkg-0"))
        assert r == expected

    def test_src_uri_change(self):
        distfile = [
            "DIST",
            "pkgcheck-1.tar.gz",
            "549746",
            "BLAKE2B",
            "72ed97d93674ffd311978d03ad3738494a752bf1b02bea5eaaaf1b066c48e8c9ec5f82b79baeeabf3e56e618c76614ee6179b7115d1d875364ac6e3fbc3c6028",
            "SHA512",
            "6a8c135ca44ccbfe15548bd396aba9448c29f60147920b18b8be5aa5fcd1200e0b75bc5de50fc7892ad5460ddad1e7d28a7e44025bdc581a518d136eda8b0df2",
        ]
        old_url = f"mirror://gentoo/{distfile[1]}"
        new_url = f"https://pkgcore.github.io/pkgcheck/{distfile[1]}"
        with open(pjoin(self.parent_repo.path, "profiles/thirdpartymirrors"), "a") as f:
            f.write("gentoo  https://gentoo.org/distfiles\n")
        self.parent_repo.create_ebuild("cat/pkg-1", src_uri=old_url)
        with open(pjoin(self.parent_repo.path, "cat/pkg/Manifest"), "w") as f:
            f.write(" ".join(distfile) + "\n")
        self.parent_git_repo.add_all("cat/pkg: add 1", signoff=True)
        # pull changes and change checksum in child repo
        self.child_git_repo.run(["git", "pull", "origin", "main"])
        self.child_repo.create_ebuild("cat/pkg-1", src_uri=new_url)
        self.child_git_repo.add_all("cat/pkg: change SRC_URI", signoff=True)
        self.init_check()
        r = self.assertReport(self.check, self.source)
        assert r == git_mod.SuspiciousSrcUriChange(old_url, new_url, distfile[1], pkg=CP("cat/pkg"))
        # revert change and check for no report with same mirror url
        self.child_git_repo.run(["git", "reset", "--hard", "origin/main"])
        self.child_repo.create_ebuild("cat/pkg-1", src_uri=old_url, homepage="https://gentoo.org")
        self.child_git_repo.add_all("cat/pkg: update HOMEPAGE", signoff=True)
        self.init_check()
        self.assertNoReport(self.check, self.source)

    def test_modified_added_file(self):
        self.child_repo.create_ebuild("cat/pkg-0", homepage="https://gentoo.org")
        self.child_git_repo.add_all("cat/pkg: update HOMEPAGE")
        time.sleep(1)
        self.child_repo.create_ebuild("cat/pkg-1", eapi="7")
        self.child_git_repo.add_all("cat/pkg: add 1")
        time.sleep(1)
        self.child_repo.create_ebuild("cat/pkg-1", eapi="8")
        self.child_git_repo.add_all("cat/pkg: bump EAPI")
        self.init_check()
        r = self.assertReport(self.check, self.source)
        expected = git_mod.EAPIChangeWithoutRevbump(pkg=CPV("cat/pkg-1"))
        assert r == expected

    def test_old_python_compat(self):
        # good compat
        self.child_repo.create_ebuild("cat/pkg-0", data="PYTHON_COMPAT=( python3_10 python3_11 )")
        self.child_git_repo.add_all("cat/pkg-0")
        self.init_check()
        self.assertNoReport(self.check, self.source)
        # one old compat
        self.child_repo.create_ebuild("cat/pkg-0", data="PYTHON_COMPAT=( python3_9 python3_10 )")
        self.child_git_repo.add_all("cat/pkg-0")
        self.init_check()
        r = self.assertReport(self.check, self.source)
        expected = git_mod.OldPythonCompat(["python3_9"], pkg=CPV("cat/pkg-0"))
        assert r == expected
        # two old compat
        self.child_repo.create_ebuild(
            "cat/pkg-0", data="PYTHON_COMPAT=( python3_9 python3_8 python3_10 )"
        )
        self.child_git_repo.add_all("cat/pkg-0")
        self.init_check()
        r = self.assertReport(self.check, self.source)
        expected = git_mod.OldPythonCompat(["python3_8", "python3_9"], pkg=CPV("cat/pkg-0"))
        assert r == expected


class TestGitEclassCommitsCheck(ReportTestCase):
    check_kls = git_mod.GitEclassCommitsCheck

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, tool, make_repo, make_git_repo):
        self._tool = tool
        self.cache_dir = str(tmp_path)

        # initialize parent repo
        self.parent_git_repo = make_git_repo()
        self.parent_repo = make_repo(self.parent_git_repo.path, repo_id="gentoo", arches=["amd64"])
        self.parent_git_repo.add_all("initial commit")
        # create a stub eclass and commit it
        touch(pjoin(self.parent_git_repo.path, "eclass", "foo.eclass"))
        self.parent_git_repo.add_all("eclass: add foo eclass")

        # initialize child repo
        self.child_git_repo = make_git_repo()
        self.child_git_repo.run(["git", "remote", "add", "origin", self.parent_git_repo.path])
        self.child_git_repo.run(["git", "pull", "origin", "main"])
        self.child_git_repo.run(["git", "remote", "set-head", "origin", "main"])
        self.child_repo = make_repo(self.child_git_repo.path)

    def init_check(self, options=None, future=0):
        self.options = options if options is not None else self._options()
        self.check, required_addons, self.source = init_check(self.check_kls, self.options)
        for k, v in required_addons.items():
            setattr(self, k, v)
        if future:
            self.check.today = datetime.today() + timedelta(days=+future)

    def _options(self, **kwargs):
        args = [
            "scan",
            "-q",
            "--cache-dir",
            self.cache_dir,
            "--repo",
            self.child_repo.location,
            "--commits",
        ]
        options, _ = self._tool.parse_args(args)
        return options

    def test_eclass_incorrect_copyright(self):
        line = "# Copyright 1999-2019 Gentoo Authors"
        with open(pjoin(self.child_git_repo.path, "eclass/foo.eclass"), "w") as f:
            f.write(f"{line}\n")
        self.child_git_repo.add_all("eclass: update foo")
        self.init_check()
        r = self.assertReport(self.check, self.source)
        expected = git_mod.EclassIncorrectCopyright("2019", line, eclass="foo")
        assert r == expected

        # correcting the year results in no report
        year = datetime.today().year
        line = f"# Copyright 1999-{year} Gentoo Authors"
        with open(pjoin(self.child_git_repo.path, "eclass/foo.eclass"), "w") as f:
            f.write(f"{line}\n")
        self.child_git_repo.add_all("eclass: fix copyright year")
        self.init_check()
        self.assertNoReport(self.check, self.source)

    def test_eclass_missing_copyright(self):
        """Eclasses missing copyrights entirely are handled by EclassHeaderCheck."""
        with open(pjoin(self.child_git_repo.path, "eclass/foo.eclass"), "w") as f:
            f.write("# comment\n")
        self.child_git_repo.add_all("eclass: update foo")
        self.init_check()
        self.assertNoReport(self.check, self.source)
