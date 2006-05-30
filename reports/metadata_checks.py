# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

import logging, os, stat, errno
from pkgcore.util.compatibility import any
from pkgcore.util.file import read_dict
from pkgcore.package.metadata import MetadataException
from reports.base import template, versioned_feed, Result
from operator import attrgetter
from pkgcore.package.atom import MalformedAtom, atom
from pkgcore.util.lists import iter_flatten
from pkgcore.util.demandload import demandload
demandload(globals(), "pkgcore.util.xml:escape")

default_attrs = ("depends", "rdepends", "provides", "license", "fetchables", "iuse")

class MetadataSyntaxReport(template):
	feed_type = versioned_feed
	
	def __init__(self, location, attrs=default_attrs):
		force_expansion = set(x for x in attrs if x in ("depends", "rdepends", "provides"))
		self.attrs = [(a, attrgetter(a), a in force_expansion) for a in attrs]
	
	@staticmethod
	def load_valid_iuse(repo):
		base = os.path.join(repo.base, "profiles")
		known_iuse = set()
		fp = os.path.join(base, "use.desc")
		try:
			known_iuse.update(usef.strip() for usef in 
				read_dict(fp, None).iterkeys())
		except IOError, ie:
			if ie.errno != errno.ENOENT:
				raise

		fp = os.path.join(base, "use.local.desc")
		try:
			known_iuse.update(usef.rsplit(":", 1)[1].strip() for usef in 
				read_dict(fp, None).iterkeys())
		except IOError, ie:
			if ie.errno != errno.ENOENT:
				raise		

		use_expand_base = os.path.join(base, "desc")
		try:
			for entry in os.listdir(use_expand_base):
				estr = entry.rsplit(".", 1)[0].lower()+ "_"
				known_iuse.update(estr + usef.strip() for usef in 
					read_dict(os.path.join(use_expand_base, entry), None).iterkeys())
		except IOError, ie:
			if ie.errno != errno.ENOENT:
				raise
		return frozenset(known_iuse)
			
	def start(self, repo):
		if any(x[0] == "license" for x in self.attrs):
			lfp = os.path.join(repo.base, "licenses")
			if not os.path.exists(lfp):
				logging.warn("disabling license checks- %s doesn't exist" % lfp)
				self.licenses = None
			else:
				self.licenses = frozenset(x for x in os.listdir(lfp) if stat.S_ISREG(os.stat(os.path.join(lfp, x)).st_mode))
		else:
			self.licenses = None
		if any(x[0] == "iuse" for x in self.attrs):
			self.valid_iuse = self.load_valid_iuse(repo)
		else:
			self.valid_iuse = None

		
	def feed(self, pkg, reporter):
		for attr_name, getter, force_expansion in self.attrs:
			try:
				o = getter(pkg)
				if force_expansion:
					for d_atom in iter_flatten(o, atom):
						d_atom.key
						d_atom.category
						d_atom.package
				if attr_name == "license":
					if self.licenses is not None:
						licenses = set(iter_flatten(o, basestring)).difference(self.licenses)
						if licenses:
							reporter.add_report(MetadataError(pkg, "license",
								"licenses don't exist- [ %s ]" % ", ".join(licenses)))
					elif not o:
						reporter.add_report(MetadataError(pkg, "license", "no license defined"))
				elif attr_name == "iuse":
					if self.valid_iuse is not None:
						iuse = set(o).difference(self.valid_iuse)
						if iuse:
							reporter.add_report(MetadataError(pkg, "iuse", 
								"iuse unknown flags- [ %s ]" % ", ".join(iuse)))
			except SystemExit:
				raise
			except (MetadataException, MalformedAtom, ValueError), e:
				reporter.add_report(MetadataError(pkg, attr_name, "error- %s" % e))
				del e
			except Exception, e:
				logging.error("unknown exception caught for pkg(%s) attr(%s): type(%s), %s" % (pkg, attr_name, type(e), e))
				reporter.add_report(MetadataError(pkg, attr_name, "exception- %s" % e))
				del e
		if not pkg.keywords:
			reporter.add_report(EmptyKeywardsMinor(pkg))
		if "-*" in pkg.keywords:
			reporter.add_report(StupidKeywardsMinor(pkg))
						

class MetadataError(Result):
	description = "problem detected with a packages metadata"
	__slots__ = ("category", "package", "version", "attr", "msg")
	
	def __init__(self, pkg, attr, msg):
		self.category, self.package, self.version = pkg.category, pkg.package, pkg.fullver
		self.attr, self.msg = attr, str(msg)
	
	def to_str(self):
		return "%s/%s-%s: attr(%s): %s" % (self.category, self.package, self.version, 
			self.attr, self.msg)

	def to_xml(self):
		return \
"""<check name="%s">
	<category>%s</category>
	<package>%s</package>
	<version>%s</version>
	<msg>%s</msg>
</check>""" % (self.__class__.__name__, self.category, self.package, self.version,
	"attr '%s' threw an error- %s" % (self.attr, escape(self.msg)))


class EmptyKeywardsMinor(Result):
	description = "pkg has no set keywords"

	def __init__(self, pkg):
		self.category = pkg.category
		self.package = pkg.package
		self.version = pkg.fullver
	
	def to_str(self):
		return "%s/%s-%s: no keywords set" % (self.category, self.package, self.version)
	
	def to_xml(self):
		return \
"""<check name="%s">
	<category>%s</category>
	<package>%s</package>
	<version>%s</version>
	<msg>no keywords set</msg>
</check>""" % (self.__class__.__name__, self.category, self.package, self.version)

		
class StupidKeywardsMinor(Result):
	description = "pkg that is using -*; package.mask in profiles addresses this already"
	
	def __init__(self, pkg):
		self.category = pkg.category
		self.package = pkg.package
		self.version = pkg.fullver
	
	def to_str(self):
		return "%s/%s-%s: keywords contains -*, use package.mask instead" % \
			(self.category, self.package, self.version)
		
	def to_xml(self):
		return \
"""<check name="%s">
	<category>%s</category>
	<package>%s</package>
	<version>%s</version>
	<msg>keywords contains -*, should use package.mask</msg>
</check>""" % (self.__class__.__name__, self.category, self.package, self.version)
