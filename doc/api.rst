API Documentation
=================

Third party usage of pkgcheck's API should always import from the pkgcheck
module. Any module or functionality that can't be accessed directly from the
main module is not considered to be stable and should be avoided.

Proper API usage example:

.. code-block:: python

    from pkgcheck import scan

    for result in scan(['-r', '/path/to/ebuild/repo']):
        print(result)
