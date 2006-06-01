# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

import logging, os, stat, errno
from operator import attrgetter
from reports.base import template, versioned_feed, Result
from reports.arches import default_arches

from pkgcore.util.demandload import demandload
from pkgcore.util.compatibility import any
from pkgcore.util.file import read_dict
from pkgcore.package.metadata import MetadataException
from pkgcore.package.atom import MalformedAtom, atom
from pkgcore.util.lists import iter_flatten
from pkgcore.util.iterables import expandable_chain
from pkgcore.fetch.fetchable import fetchable
from pkgcore.restrictions import packages
demandload(globals(), "pkgcore.util.xml:escape")

default_attrs = ("depends", "rdepends", "provides", "license", "fetchables", "iuse")

class MetadataReport(template):
	feed_type = versioned_feed
	
	def __init__(self, location):
		force_expansion = ("depends", "rdepends", "provides")
		self.attrs = [(a, attrgetter(a), a in force_expansion) for a in default_attrs]
		self.iuse_users = dict((x, attrgetter(x)) for x in 
			("fetchables", "depends", "rdepends", "provides"))
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

		if self.valid_iuse is not None:
			used_iuse = set()
			for attr_name, f in self.iuse_users.iteritems():
				i = expandable_chain(iter_flatten(f(pkg), (packages.Conditional, atom, basestring, fetchable)))
				for node in i:
					if not isinstance(node, packages.Conditional):
						continue
					# it's always a values.ContainmentMatch
					used_iuse.update(node.restriction.vals)
					i.append(iter_flatten(node.payload, (packages.Conditional, atom, basestring, fetchable)))
				unstated = used_iuse.difference(pkg.iuse).difference(default_arches)
				if unstated:
					# hack, see bug 134994.
					if unstated.difference(["bootstrap"]):
						reporter.add_report(UnstatedIUSE(pkg, attr_name, unstated))

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


class SrcUriReport(template):
	feed_type = versioned_feed

	def __init__(self, location):
		self.valid_protos = frozenset(["http", "https", "ftp"])
	
	def feed(self, pkg, reporter):
		lacks_uri = set()
		for f_inst in iter_flatten(pkg.fetchables, fetchable):
			if f_inst.uri is None:
				lacks_uri.add(f_inst.filename)
			elif isinstance(f_inst.uri, list):
				bad = set()
				for x in f_inst.uri:
					i = x.find("://")
					if i == -1:
						bad.add(x)
					else:
						if x[:i] not in self.valid_protos:
							bad.add(x)
				if bad:
					reporter.add_report(BadProto(pkg, f_inst.filename, bad))
		if not "fetch" in pkg.restrict:
			for x in lacks_uri:
				reporter.add_report(MissingUri(pkg, x))


class DescriptionReport(template):
	feed_type = versioned_feed
	
	def __init__(self, location):
		pass
	
	def feed(self, pkg, reporter):
		s = pkg.description.lower()
		if s.startswith("based on") and "eclass" in s:
			reporter.add_report(CrappyDescription(pkg, "generic eclass defined description"))
		elif pkg.package == s or pkg.key == s:
			reporter.add_report(CrappyDescription(pkg, "using the pkg name as the description isn't very helpful"))
		else:
			l = len(pkg.description)
			if not l:
				reporter.add_report(CrappyDescription(pkg, "empty/unset"))
			elif l > 250:
				reporter.add_report(CrappyDescription(pkg, "over 250 chars in length, bit long"))
			elif l < 5:
				reporter.add_report(CrappyDescription(pkg, "under 10 chars in length- too short"))


class RestrictsReport(template):
	feed_type = versioned_feed
	known_restricts = frozenset(("confcache", "stricter", "mirror", "fetch", "test", 	
		"sandbox", "userpriv", "primaryuri", "binchecks", "strip"))

	def __init__(self, location):
		pass
	
	def feed(self, pkg, reporter):
		bad = set(pkg.restrict).difference(self.known_restricts)
		if bad:
			deprecated = set(x for x in bad if x.startswith("no") and x[2:] in self.known_restricts)
			reporter.add_report(BadRestricts(pkg, bad.difference(deprecated), deprecated))


class BadRestricts(Result):
	description = "pkg's restrict metadata has unknown/deprecated entries"
	
	__slots__ = ("category", "package", "version", "restricts", "deprecated")
	
	def __init__(self, pkg, restricts, deprecated=None):
		self.category, self.package, self.version = pkg.category, pkg.package, pkg.fullver
		self.restricts = restricts
		self.deprecated = deprecated
		if not restricts and not deprecated:
			raise TypeError("deprecated or restricts must not be empty")
	
	def to_str(self):
		s = ''
		if self.restricts:
			s = "unknown restricts- [ %s ]" % ", ".join(self.restricts)
		if self.deprecated:
			if s:
				s+=", "
			s += "deprecated (drop the 'no') [ %s ]" % ", ".join(self.deprecated)
		return "%s/%s-%s: %s" % (self.category, self.package, self.version, s)
		
	def to_xml(self):
		s = ''
		if self.restricts:
			s = "unknown restricts: %s" % ", ".join(self.restricts)
		if self.deprecated:
			if s:
				s += ".  "
			s += "deprecated (drop the 'no')- %s" % ", ".join(self.deprecated)

		return \
"""<check name="%s">
	<category>%s</category>
	<package>%s</package>
	<version>%s</version>
	<msg>%s</msg>
</check>""" % (self.__class__.__name__, self.category, self.package, self.version, 
	"unknown restricts- %s" % s)


class CrappyDescription(Result):
	description = "pkg's description sucks in some fashion"

	__slots__ = ("category", "package", "version", "msg")

	def __init__(self, pkg, msg):
		self.category, self.package, self.version = pkg.category, pkg.package, pkg.fullver
		self.msg = msg
	
	def to_str(self):
		return "%s/%s-%s: description: %s" % (self.category, self.package, self.version, self.msg)
	
	def to_xml(self):
		return \
"""<check name="%s">
	<category>%s</category>
	<package>%s</package>
	<version>%s</version>
	<msg>%s</msg>
</check>""" % (self.__class__.__name__, self.category, self.package, self.version, self.msg)


class UnstatedIUSE(Result):
	description = "pkg is reliant on conditionals that aren't in IUSE"
	__slots__ = ("category", "package", "version", "attr", "flags")
	
	def __init__(self, pkg, attr, flags):
		self.category, self.package, self.version = pkg.category, pkg.package, pkg.fullver
		self.attr, self.flags = attr, tuple(flags)
	
	def to_str(self):
		return "%s/%s-%s: attr(%s) uses unstated flags [ %s ]" % \
		(self.category, self.package, self.version, self.attr, ", ".join(self.flags))

	def to_xml(self):
		return \
"""<check name="%s">
	<category>%s</category>
	<package>%s</package>
	<version>%s</version>
	<msg>attr %s uses unstead flags: %s"</msg>
</check>""" % (self.__class__.__name__, self.category, self.package, self.version, 
	self.attr, ", ".join(self.flags))


class MissingUri(Result):
	description = "restrict=fetch isn't set, yet no full uri exists"
	__slots__ = ("category", "package", "version", "filename")

	def __init__(self, pkg, filename):
		self.category, self.package, self.version = pkg.category, pkg.package, pkg.fullver
		self.filename = filename
	
	def to_str(self):
		return "%s/%s-%s: no uri specified for %s and RESTRICT=fetch isn't on" % \
			(self.category, self.package, self.version, self.filename)
	
	def to_xml(self):
		return \
"""<check name="%s">
	<category>%s</category>
	<package>%s</package>
	<version>%s</version>
	<msg>no uri specified for %s</msg>
</check>""" % (self.__class__.__name__, self.category, self.package, self.version, escape(self.filename))


class BadProto(Result):
	description = "bad protocol"
	__slots__ = ("category", "package", "version", "filename", "bad_uri")

	def __init__(self, pkg, filename, bad_uri):
		self.category, self.package, self.version = pkg.category, pkg.package, pkg.fullver
		self.filename = filename
		self.bad_uri = bad_uri
	
	def to_str(self):
		return "%s/%s-%s: file %s, bad proto/uri- [ '%s' ]" % (self.category, self.package,
			self.version, self.filename, "', '".join(self.bad_uri))
	
	def to_xml(self):
		return \
"""<check name="%s">
	<category>%s</category>
	<package>%s</package>
	<version>%s</version>
	<msg>file %s has invalid uri- %s</msg>
</check>""" % (self.__class__.__name__, self.category, self.package, self.version, 
	escape(self.filename), escape(", ".join(self.bad_uri)))


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
