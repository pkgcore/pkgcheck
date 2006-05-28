# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

from pkgcore.util.compatibility import any
from pkgcore.util.file import read_dict
from pkgcore.package.metadata import MetadataException
from reports.base import template, versioned_feed
from operator import attrgetter
from pkgcore.fs.util import ensure_dirs
from pkgcore.package.atom import MalformedAtom, atom
from pkgcore.util.lists import iter_flatten
import logging, os, stat, errno

default_attrs = ("depends", "rdepends", "provides", "license", "fetchables", "iuse")

class MetadataSyntaxReport(template):
	feed_type = versioned_feed
	
	def __init__(self, location, attrs=default_attrs):
		self.location = location
		self.reportf = self.keywordsf = None
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
		if not ensure_dirs(self.location, mode=0755):
			raise Exception("failed creating reports directory %s" % self.location)
		self.reportf = open(os.path.join(self.location, "metadata_checks"), "w", 8096)
		self.keywordsf = open(os.path.join(self.location, "stupid_keywords"), "w", 8096)
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
			
		
	def feed(self, pkg):
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
							self.write_entry(pkg, "license", "licenses don't exist- [ %s ]" % ", ".join(licenses))
					elif not o:
						self.write_entry(pkg, "license", "no license defined")
				elif attr_name == "iuse":
					if self.valid_iuse is not None:
						iuse = set(o).difference(self.valid_iuse)
						if iuse:
							self.write_entry(pkg, "iuse", "iuse unknown flags- [ %s ]" % ", ".join(iuse))
			except SystemExit:
				raise
			except (MetadataException, MalformedAtom, ValueError), e:
				self.write_entry(pkg, attr_name, e)
				del e
			except Exception, e:
				logging.error("unknown exception caught for pkg(%s) attr(%s): type(%s), %s" % (pkg, attr_name, type(e), e))
				self.write_entry(pkg, attr_name, e)
				del e
		if not pkg.keywords:
			self.write_entry(pkg, "keywords", "keywords is empty")
		if "-*" in pkg.keywords:
			self.write_entry(pkg, "keywords", "keywords contains '-*', should use package.mask instead", fd=self.keywordsf)
						
	def write_entry(self, pkg, attr, error, fd=None):
		if fd is None:
			fd = self.reportf
		fd.write("%s: attr(%s)\n  error: %s\n\n" % (pkg, attr, error))

	def finish(self):
		self.reportf.close()
		self.keywordsf.close()
		self.reportf = self.keywordsf = None
