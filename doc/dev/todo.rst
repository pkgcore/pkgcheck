- back out package.provided hack in visibility, fix start prototype
- rework filter-env so it dumps a struct representing the parsing instead of
  doing it inline; add python bindings, use that for source flow analysis
- look into trying to identify unused functions in an ebuild; eclasses, and
  bash support for f() { echo "monkeys"; };x=f;${!x}; makes this potentially
  likely to be a major false positive source.
- some form of exemption syntax, for spots where the ebuild is doing something
  normally bad, but valid in this scenario
- some form of -jN test (complex/hard)
