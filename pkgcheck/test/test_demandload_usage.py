# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: BSD/GPL2

from snakeoil.test import test_demandload_usage


class TestDemandLoadUsage(test_demandload_usage.TestDemandLoadTargets):
    target_namespace = "pkgcheck"
