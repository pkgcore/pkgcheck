- back out package.provided hack in visibility, fix start prototype
- tests (dar)
- silence profile deprecation warnings; pkgcore mod, but noting it here since
  it's bit more relevant to pkgcheck
- rework filter-env so it dumps a struct representing the parsing instead of
  doing it inline; add python bindings, use that for source flow analysis
- look into trying to identify unused functions in an ebuild; eclasses, and
  bash support for f() { echo "monkeys"; };x=f;${!x}; makes this potentially
  likely to be a major false positive source.
- subshelled dies
- some form of exemption syntax, for spots where the ebuild is doing something
  normally bad, but valid in this scenario
- some form of -jN test (complex/hard)
- parallelize the bugger (potentially hard).  can probably thread it splitting
  it such that check x handles checks using globals x (cache mainly), other
  checks being bits that don't; gain may not be much since the major time
  consumers are visibility and unported_mod_x
