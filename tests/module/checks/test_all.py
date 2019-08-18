from pkgcheck import const

_known_keywords = set()

def test_checks():
    """Scan through all public checks and verify various aspects."""
    for name, cls in const.CHECKS.items():
        assert cls.known_results, f"check class {name!r} doesn't define known results"
        _known_keywords.update(cls.known_results)


def test_keywords():
    """Scan through all public result keywords and verify various aspects."""
    for name, cls in const.KEYWORDS.items():
        assert cls in _known_keywords, f"result class {name!r} not used by any checks"
    # verify dynamically scanned keywords are equal to the known results set
    assert set(const.KEYWORDS.values()) == _known_keywords
