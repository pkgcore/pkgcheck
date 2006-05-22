from pkgcore.package.metadata import MetadataException
from reports.base import template, versioned_feed
from operator import attrgetter
from pkgcore.fs.util import ensure_dirs
from pkgcore.package.atom import MalformedAtom
import logging, os

default_attrs = ("depends", "rdepends", "provides", "license", "fetchables")

class MetadataSyntaxReport(template):
	feed_type = versioned_feed
	
	def __init__(self, location, attrs=default_attrs):
		self.location = location
		self.reportf = None
		self.attrs = [(a, attrgetter(a)) for a in attrs]
	
	def start(self, repo):
		if not ensure_dirs(self.location, mode=0755):
			raise Exception("failed creating reports directory %s" % self.location)
		self.reportf = open(os.path.join(self.location, "metadata_checks"), "w", 8096)
		
	def feed(self, pkg):
		for attr_name, getter in self.attrs:
			try:
				getter(pkg)
			except SystemExit:
				raise
			except (MetadataException, TypeError, MalformedAtom), e:
				self.write_entry(pkg, attr_name, e)
				del e
			except Exception, e:
				logging.error("unknown exception caught for pkg(%s) attr(%s): %s" % (pkg, attr_name, e))
				self.write_entry(pkg, attr_name, e)
				del e
	
	def write_entry(self, pkg, attr, error):
		self.reportf.write("pkg %s: attr(%s)\n  error: %s\n\n" % (pkg, attr, error))

	def finish(self):
		self.reportf.close()
		self.reportf = None
