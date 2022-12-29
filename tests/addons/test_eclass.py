import os
import textwrap
from time import sleep
from unittest.mock import patch

import pytest
from pkgcheck.addons import init_addon
from pkgcheck.addons.eclass import Eclass, EclassAddon
from pkgcheck.base import PkgcheckUserException
from pkgcheck.addons.caches import CacheDisabled
from snakeoil.fileutils import touch
from snakeoil.osutils import pjoin


class TestEclass:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        path = str(tmp_path / "foo.eclass")
        with open(path, "w") as f:
            f.write(
                textwrap.dedent(
                    """\
                        # eclass header
                        foo () { :; }
                    """
                )
            )
        self.eclass1 = Eclass("foo", path)
        path = str(tmp_path / "bar.eclass")
        self.eclass2 = Eclass("bar", path)

    def test_lines(self):
        assert self.eclass1.lines == ("# eclass header\n", "foo () { :; }\n")
        assert self.eclass2.lines == ()

    def test_lt(self):
        assert self.eclass2 < self.eclass1
        assert self.eclass1 < "zoo.eclass"

    def test_hash(self):
        eclasses = {self.eclass1, self.eclass2}
        assert self.eclass1 in eclasses and self.eclass2 in eclasses
        assert {self.eclass1, self.eclass1} == {self.eclass1}

    def test_eq(self):
        assert self.eclass1 == self.eclass1
        assert self.eclass1 == self.eclass1.path
        assert not self.eclass1 == self.eclass2


class TestEclassAddon:
    @pytest.fixture(autouse=True)
    def _setup(self, tool, tmp_path, repo):
        self.repo = repo
        self.cache_dir = str(tmp_path)

        self.eclass_dir = pjoin(repo.location, "eclass")

        args = ["scan", "--cache-dir", self.cache_dir, "--repo", repo.location]
        options, _ = tool.parse_args(args)
        self.addon = EclassAddon(options)
        self.cache_file = self.addon.cache_file(self.repo)

    def test_cache_disabled(self, tool):
        args = ["scan", "--cache", "no", "--repo", self.repo.location]
        options, _ = tool.parse_args(args)
        with pytest.raises(CacheDisabled, match="eclass cache support required"):
            init_addon(EclassAddon, options)

    def test_no_eclasses(self):
        self.addon.update_cache()
        assert not os.path.exists(self.cache_file)
        assert not self.addon.eclasses
        assert not self.addon.deprecated

    def test_eclasses(self):
        # non-eclass files are ignored
        for f in ("foo.eclass", "bar"):
            touch(pjoin(self.eclass_dir, f))
        self.addon.update_cache()
        assert list(self.addon.eclasses) == ["foo"]
        assert not self.addon.deprecated

    def test_cache_load(self):
        touch(pjoin(self.eclass_dir, "foo.eclass"))
        self.addon.update_cache()
        assert list(self.addon.eclasses) == ["foo"]

        with patch("pkgcheck.addons.caches.CachedAddon.save_cache") as save_cache:
            self.addon.update_cache()
            # verify the cache was loaded and not regenerated
            save_cache.assert_not_called()
            self.addon.update_cache(force=True)
            # and is regenerated on a forced cache update
            save_cache.assert_called_once()

    def test_outdated_cache(self):
        touch(pjoin(self.eclass_dir, "foo.eclass"))
        self.addon.update_cache()
        assert list(self.addon.eclasses) == ["foo"]

        # increment cache version and dump cache
        cache = self.addon.load_cache(self.cache_file)
        cache.version += 1
        self.addon.save_cache(cache, self.cache_file)

        # verify cache load causes regen
        with patch("pkgcheck.addons.caches.CachedAddon.save_cache") as save_cache:
            self.addon.update_cache()
            save_cache.assert_called_once()

    def test_eclass_changes(self):
        """The cache stores eclass mtimes and regenerates entries if they differ."""
        eclass_path = pjoin(self.eclass_dir, "foo.eclass")
        touch(eclass_path)
        self.addon.update_cache()
        assert list(self.addon.eclasses) == ["foo"]
        sleep(1)
        with open(eclass_path, "w") as f:
            f.write("# changed eclass\n")
        with patch("pkgcheck.addons.caches.CachedAddon.save_cache") as save_cache:
            self.addon.update_cache()
            save_cache.assert_called_once()

    def test_error_loading_cache(self):
        touch(pjoin(self.eclass_dir, "foo.eclass"))
        self.addon.update_cache()
        assert list(self.addon.eclasses) == ["foo"]

        with patch("pkgcheck.addons.caches.pickle.load") as pickle_load:
            # catastrophic errors are raised
            pickle_load.side_effect = MemoryError("unpickling failed")
            with pytest.raises(MemoryError, match="unpickling failed"):
                self.addon.update_cache()

            # but various load failure exceptions cause cache regen
            pickle_load.side_effect = Exception("unpickling failed")
            with patch("pkgcheck.addons.caches.CachedAddon.save_cache") as save_cache:
                self.addon.update_cache()
                save_cache.assert_called_once()

    def test_error_dumping_cache(self):
        touch(pjoin(self.eclass_dir, "foo.eclass"))
        # verify IO related dump failures are raised
        with patch("pkgcheck.addons.caches.pickle.dump") as pickle_dump:
            pickle_dump.side_effect = IOError("unpickling failed")
            with pytest.raises(PkgcheckUserException, match="failed dumping eclass cache"):
                self.addon.update_cache()

    def test_eclass_removal(self):
        for name in ("foo", "bar"):
            touch(pjoin(self.eclass_dir, f"{name}.eclass"))
        self.addon.update_cache()
        assert sorted(self.addon.eclasses) == ["bar", "foo"]
        os.unlink(pjoin(self.eclass_dir, "bar.eclass"))
        self.addon.update_cache()
        assert list(self.addon.eclasses) == ["foo"]

    def test_deprecated(self):
        with open(pjoin(self.eclass_dir, "foo.eclass"), "w") as f:
            f.write(
                textwrap.dedent(
                    """\
                        # @ECLASS: foo.eclass
                        # @MAINTAINER:
                        # Random Person <random.person@random.email>
                        # @AUTHOR:
                        # Random Person <random.person@random.email>
                        # @BLURB: Example deprecated eclass with replacement.
                        # @DEPRECATED: foo2
                    """
                )
            )
        self.addon.update_cache()
        assert list(self.addon.eclasses) == ["foo"]
        assert self.addon.deprecated == {"foo": "foo2"}
