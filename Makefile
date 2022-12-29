PYTHON ?= python
SPHINX_BUILD ?= $(PYTHON) -m sphinx.cmd.build

.PHONY: man html
man html:
	$(SPHINX_BUILD) -a -b $@ doc build/sphinx/$@

.PHONY: sdist wheel
sdist wheel:
	$(PYTHON) -m build --$@

.PHONY: clean
clean:
	$(RM) -r build doc/man/pkgcheck doc/generated dist

.PHONY: format
format:
	$(PYTHON) -m black .
