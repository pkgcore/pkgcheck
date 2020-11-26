import os
import pickle
import textwrap
from unittest.mock import patch

import pytest
from pkgcheck.eclass import EclassAddon
from pkgcore.ebuild import repo_objs, repository
from pkgcore.ebuild.eclass import EclassDocParsingError
from snakeoil.cli.exceptions import UserException
from snakeoil.fileutils import touch
from snakeoil.osutils import pjoin


class TestEclassAddon:

    @pytest.fixture(autouse=True)
    def _setup(self, tool, tmp_path):
        # TODO: switch to using a repo fixture when available
        repo_dir = str(tmp_path / 'repo')
        self.cache_dir = str(tmp_path / 'cache')

        self.eclass_dir = pjoin(repo_dir, 'eclass')
        os.makedirs(pjoin(repo_dir, 'profiles'))
        os.makedirs(pjoin(repo_dir, 'metadata'))
        os.makedirs(self.eclass_dir)
        with open(pjoin(repo_dir, 'profiles', 'repo_name'), 'w') as f:
            f.write('fake\n')
        with open(pjoin(repo_dir, 'metadata', 'layout.conf'), 'w') as f:
            f.write('masters =\n')
        repo_config = repo_objs.RepoConfig(location=repo_dir)
        self.repo = repository.UnconfiguredTree(repo_config.location, repo_config=repo_config)

        args = ['scan', '--cache-dir', self.cache_dir, '--repo', self.repo.location]
        options, _ = tool.parse_args(args)
        self.addon = EclassAddon(options)
        self.cache_file = self.addon.cache_file(self.repo)

    def test_cache_disabled(self, tool):
        args = ['scan', '--cache', 'no', '--repo', self.repo.location]
        options, _ = tool.parse_args(args)
        self.addon = EclassAddon(options)
        assert not self.addon.eclasses
        assert not self.addon.deprecated

    def test_no_eclasses(self):
        self.addon.update_cache()
        assert not self.addon.eclasses
        assert not self.addon.deprecated

    def test_eclasses(self):
        # non-eclass files are ignored
        for f in ('foo.eclass', 'bar'):
            touch(pjoin(self.eclass_dir, f))
        self.addon.update_cache()
        assert list(self.addon.eclasses) == ['foo']
        assert not self.addon.deprecated

    def test_cache_load(self):
        touch(pjoin(self.eclass_dir, 'foo.eclass'))
        self.addon.update_cache()
        assert list(self.addon.eclasses) == ['foo']

        # verify the cache was loaded and not regenerated
        st = os.lstat(self.cache_file)
        self.addon.update_cache()
        assert list(self.addon.eclasses) == ['foo']
        assert st.st_mtime == os.lstat(self.cache_file).st_mtime

        # and is regenerated on a forced cache update
        self.addon.update_cache(force=True)
        assert list(self.addon.eclasses) == ['foo']
        assert st.st_mtime != os.lstat(self.cache_file).st_mtime

    def test_outdated_cache(self):
        touch(pjoin(self.eclass_dir, 'foo.eclass'))
        self.addon.update_cache()
        assert list(self.addon.eclasses) == ['foo']

        # increment cache version and dump cache
        with open(self.cache_file, 'rb') as f:
            cache_obj = pickle.load(f)
        cache_obj.version += 1
        with open(self.cache_file, 'wb') as f:
            pickle.dump(cache_obj, f, protocol=-1)

        # verify cache load causes regen
        st = os.lstat(self.cache_file)
        self.addon.update_cache()
        assert list(self.addon.eclasses) == ['foo']
        assert st.st_mtime != os.lstat(self.cache_file).st_mtime

    def test_error_loading_cache(self):
        touch(pjoin(self.eclass_dir, 'foo.eclass'))
        self.addon.update_cache()
        assert list(self.addon.eclasses) == ['foo']
        st = os.lstat(self.cache_file)

        # verify various load failure exceptions cause cache regen
        with patch('pkgcheck.eclass.pickle.load') as pickle_load:
            pickle_load.side_effect = Exception('unpickling failed')
            self.addon.update_cache()
        assert list(self.addon.eclasses) == ['foo']
        assert st.st_mtime != os.lstat(self.cache_file).st_mtime

        # but catastrophic errors are raised
        with patch('pkgcheck.eclass.pickle.load') as pickle_load:
            pickle_load.side_effect = MemoryError('unpickling failed')
            with pytest.raises(MemoryError):
                self.addon.update_cache()

    def test_error_dumping_cache(self):
        touch(pjoin(self.eclass_dir, 'foo.eclass'))
        # verify IO related dump failures are raised
        with patch('pkgcheck.eclass.pickle.dump') as pickle_dump:
            pickle_dump.side_effect = IOError('unpickling failed')
            with pytest.raises(UserException) as excinfo:
                self.addon.update_cache()
            assert 'failed dumping eclasses' in str(excinfo.value)

    def test_eclass_removal(self):
        for name in ('foo', 'bar'):
            touch(pjoin(self.eclass_dir, f'{name}.eclass'))
        self.addon.update_cache()
        assert list(self.addon.eclasses) == ['bar', 'foo']
        os.unlink(pjoin(self.eclass_dir, 'bar.eclass'))
        self.addon.update_cache()
        assert list(self.addon.eclasses) == ['foo']

    def test_eclass_parsing_failure(self):
        """Eclasses with doc parsing failures are ignored."""
        touch(pjoin(self.eclass_dir, 'foo.eclass'))
        with patch('pkgcheck.eclass.EclassDoc') as eclass_cls:
            eclass_cls.side_effect = EclassDocParsingError('failed parsing')
            self.addon.update_cache()
        assert list(self.addon.eclasses) == []

    def test_deprecated(self):
        with open(pjoin(self.eclass_dir, 'foo.eclass'), 'w') as f:
            f.write(textwrap.dedent("""
                # @ECLASS: foo.eclass
                # @MAINTAINER:
                # Random Person <random.person@random.email>
                # @AUTHOR:
                # Random Person <random.person@random.email>
                # @BLURB: Example deprecated eclass with replacement.
                # @DEPRECATED: foo2
        """))
        self.addon.update_cache()
        assert list(self.addon.eclasses) == ['foo']
        assert self.addon.deprecated == {'foo': 'foo2'}
