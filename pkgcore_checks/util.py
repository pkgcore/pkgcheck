# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

import os, errno
from operator import attrgetter
from pkgcore.util.demandload import demandload
demandload(globals(), "pkgcore.ebuild.profiles:OnDiskProfile "+
	"pkgcore.ebuild.domain:generate_masking_restrict "+
	"pkgcore.util.mapping:LazyValDict "+
	"pkgcore.util.packages:get_raw_pkg "+
	"logging ")


def get_profile_from_repo(repo, profile_name):
	return OnDiskProfile(profile_name, base_repo=repo)

def get_profile_from_path(path, profile_name):
	return OnDiskProfile(profile_name, base_path=path)

def get_profile_mask(profile):
	return generate_masking_restrict(profile.maskers)

def get_profiles_desc(repo):
	base = repo
	if not isinstance(base, basestring):
		# repo instance.
		base = os.path.join(repo.base, "profiles")
	fp = os.path.join(base, "profiles.desc")
	if not os.path.exists(fp):
		raise OSError(errno.ENOENT, fp)

	arches_dict = {}
	for line_no, line in enumerate(open(fp, "r")):
		l = line.split()
		if not l or l[0].startswith("#"):
			continue
		try:
			key, profile, status = l
		except ValueError, v:
			logging.error("%s: line number %i isn't of 'key profile status' form" % (fp, line_no))
			continue
		# yes, we're ignoring status.
		# it's a silly feature anyways.
		arches_dict.setdefault(key, []).append(profile)

	return arches_dict
		
def get_repo_known_arches(repo):
	fp = os.path.join(repo.base, "profiles", "arch.list")
	if not os.path.exists(fp):
		raise OSError(errno.ENOENT, fp)
	
	return set(open(fp, "r").read().split())


def get_cpvstr(pkg):
	pkg = get_raw_pkg(pkg)
	s = getattr(pkg, "cpvstr", None)
	if s is not None:
		return s
	return str(pkg)	
