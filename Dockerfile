FROM python:3-alpine
ARG PKGCHECK_VERSION

RUN apk add --no-cache "bash>=5.3" git perl xz zstd && \
    apk add --no-cache --virtual .build build-base perl-app-cpanminus && \
    cpanm --quiet --notest Gentoo::PerlMod::Version && \
    pip install --root-user-action=ignore pkgcheck==${PKGCHECK_VERSION} setuptools requests && \
    # TODO: drop once py-tree-sitter releases past 0.26.0, which segfaults
    pip install --root-user-action=ignore --force-reinstall --no-deps \
        "tree-sitter @ git+https://github.com/tree-sitter/py-tree-sitter.git@2e556e540dd4ccce0e24c92d4413ef9ac85284a5" && \
    apk del .build && \
    pip cache purge && \
    ln -sv /bin/bash /usr/bin/bash && \
    git config --global --add safe.directory '*'
