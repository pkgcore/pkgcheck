# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

from pkgcore.package.metadata import MetadataException
from reports.base import template, versioned_feed
from operator import attrgetter
from pkgcore.fs.util import ensure_dirs
from pkgcore.package.atom import MalformedAtom, atom
from pkgcore.util.lists import iter_flatten
import logging, os

default_attrs = ("depends", "rdepends", "provides", "license", "fetchables")

class MetadataSyntaxReport(template):
	feed_type = versioned_feed
	
	def __init__(self, location, attrs=default_attrs):
		self.location = location
		self.reportf = None
		force_expansion = set(x for x in attrs if x in ("depends", "rdepends", "provides"))
		self.attrs = [(a, attrgetter(a), a in force_expansion) for a in attrs]
		
	def start(self, repo):
		if not ensure_dirs(self.location, mode=0755):
			raise Exception("failed creating reports directory %s" % self.location)
		self.reportf = open(os.path.join(self.location, "metadata_checks"), "w", 8096)
		
	def feed(self, pkg):
		for attr_name, getter, force_expansion in self.attrs:
			try:
				o = getter(pkg)
				if force_expansion:
					for d_atom in iter_flatten(o, atom):
						d_atom.key
						d_atom.category
						d_atom.package
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
#		if "-*" in pkg.keywords:
#			self.write_entry(pkg, "keywords", "keywords contains '-*', should use package.mask instead")
			
	def write_entry(self, pkg, attr, error):
		self.reportf.write("%s: attr(%s)\n  error: %s\n\n" % (pkg, attr, error))

	def finish(self):
		self.reportf.close()
		self.reportf = None
