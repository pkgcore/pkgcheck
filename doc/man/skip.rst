Skip results annotations
========================

pkgcheck supports skipping ebuilds results via special annotation. This is
useful in cases where you are aware of false positive in pkgcheck check, and
fixing pkgcheck is hard or impossible.

The annotation must appear in the ebuild before any non-comment non-empty line
(most of the times it would be just before the EAPI declaration line and after
the copyright lines). Empty lines between the copyright and the annotation are
allowed.

You can't skip *error* level results. Skipping *warning* level results requires
QA team member approval (should include name and RFC 3339 data). *info* and
*style* level can be skipped without approval. Do consider to just ignore them
instead of skipping.

An example of skipping a *info* and *warning* level results::

    # Copyright 2023 Gentoo Authors
    # Distributed under the terms of the GNU General Public License v2

    # pkgcheck skip: PythonCompatUpdate

    # Approved by larry 2023-04-31
    # pkgcheck skip: VariableScope

    EAPI=8
