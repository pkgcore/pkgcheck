# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

from pkgcore_checks.base import template, versioned_feed, Result

class BadInheritsReport(template):
	feed_type = versioned_feed
	blacklist = frozenset((
	'64-bit',
	'darcs',
	'db4-fix',
	'debian',
	'embassy-2.10',
	'embassy-2.9',
	'gcc',
	'gnustep-old',
	'gtk-engines',
	'gtk-engines2',
	'inherit',
	'jakarta-commons',
	'kde-base',
	'kde-i18n',
	'kde-source',
	'kmod',
	'koffice-i18n',
	'motif',
	'mozilla',
	'myth',
	'pax-utils',
	'perl-post',
	'php',
	'php-2',
	'php-ext',
	'php-ext-base',
	'php-ext-pecl',
	'php-ext-source',
	'php-lib',
	'php-pear',
	'php-sapi',
	'php5-sapi',
	'php5-sapi-r1',
	'php5-sapi-r3',
	'tla',
	'xfree'))
	
	def feed(self, pkg, reporter):
		bad = self.blacklist.intersection(pkg.data["_eclasses_"])
		if bad:
			reporter.add_report(DeprecatedEclass(pkg, bad))


class DeprecatedEclass(Result):
	description = "pkg uses an eclass that is deprecated/abandoned"
	
	__slots__ = ("category", "package", "version", "eclasses")
	
	def __init__(self, pkg, eclasses):
		self.category, self.package, self.version = pkg.category, pkg.package, pkg.fullver
		self.eclasses = tuple(sorted(eclasses))

	def to_str(self):
		return "%s/%s-%s: deprecated eclasses [ %s ]" % (self.category, self.package, self.version,
			", ".join(self.eclasses))

	def to_xml(self):
		return \
"""<check name="%s">
	<category>%s</category>
	<package>%s</package>
	<version>%s</version>
	<msg>deprecated eclass usage- %s</msg>
</check>""" % (self.__class__.__name__, self.category, self.package, self.version, 
	", ".join(self.eclasses))
