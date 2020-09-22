"""Eclass specific support and addon."""

from collections import UserDict, defaultdict
import os
import pickle
import re

from snakeoil import klass
from snakeoil.cli.exceptions import UserException
from snakeoil.strings import pluralism

from . import base, caches
from .log import logger


# mapping between known eclass doc tags and parsing methods
_eclass_doc_tags = defaultdict(dict)
# mapping between known eclass block tags and related classes
_eclass_blocks = dict()


def eclass_doc(tag, required=False, name=None):
    """Decorator to register eclass doc tag parsing methods."""
    def wrapper(func):
        block, _, var = tag.partition('/')
        doc_name = name if name else func.__name__
        _eclass_doc_tags[block][var] = (func, required, doc_name)
    return wrapper


def eclass_block(block, name, singular=False):
    """Decorator to register eclass blocks."""
    def wrapper(cls):
        cls._block = block
        cls._name = name
        _eclass_blocks[block] = (cls(), singular)
    return wrapper


class EclassDocParsingError(Exception):
    """Error when parsing eclass docs."""


def _parsing_error_cb(exc):
    """Callback to handle parsing exceptions."""
    raise exc


class _EclassDoc:
    """Generic block for eclass docs."""

    # eclass doc block name
    _block = None
    # eclass doc parsed block name
    _name = None

    @klass.jit_attr
    def _block_tags_re(self):
        """Regex matching all known tags for the eclass doc block."""
        tags = rf'|'.join(_eclass_doc_tags[self._block])
        return re.compile(rf'^(?P<tag>{tags})(?P<value>.*)')

    @klass.jit_attr
    def _required(self):
        """Set of required eclass doc block tags."""
        tags = set()
        for k, (_func, required, _name) in _eclass_doc_tags[self._block].items():
            if required:
                tags.add(k)
        return frozenset(tags)

    def parse(self, lines, line_ind):
        """Parse an eclass block."""
        blocks = []
        data = dict()
        # track if all required tags are defined
        missing_tags = set(self._required)

        # split eclass doc block into separate blocks by tag
        for i, line in enumerate(lines):
            m = self._block_tags_re.match(line)
            if m is not None:
                tag = m.group('tag')
                missing_tags.discard(tag)
                value = m.group('value').strip()
                blocks.append((tag, line, line_ind + i, [value] if value else []))
            else:
                blocks[-1][-1].append(line)

        # parse each tag block
        for tag, header, line_ind, block_lines in blocks:
            func, required, name = _eclass_doc_tags[self._block][tag]
            try:
                data[name] = func(self, block_lines, header, line_ind)
            except EclassDocParsingError as e:
                _parsing_error_cb(e)

        # check if any required tags are missing
        if missing_tags:
            missing_tags_str = ', '.join(map(repr, missing_tags))
            s = pluralism(missing_tags)
            _parsing_error_cb(EclassDocParsingError(
                f'{repr(lines[0])}: missing tag{s}: {missing_tags_str}'))

        return data


@eclass_block('@ECLASS', None, singular=True)
class _EclassBlock(_EclassDoc):
    """ECLASS doc block."""

    @eclass_doc('@ECLASS/@ECLASS:', required=True)
    def name(self, lines, line, lineno):
        try:
            return lines[0]
        except IndexError:
            raise EclassDocParsingError(f'{repr(line)}, line {lineno}: missing eclass name')

    @eclass_doc('@ECLASS/@MAINTAINER:', required=True)
    def maintainers(self, lines, line, lineno):
        if not lines:
            raise EclassDocParsingError(f'{repr(line)}, line {lineno}: missing maintainers')
        return tuple(lines)

    @eclass_doc('@ECLASS/@AUTHOR:')
    def authors(self, lines, line, lineno):
        if not lines:
            raise EclassDocParsingError(f'{repr(line)}, line {lineno}: missing authors')
        return tuple(lines)

    @eclass_doc('@ECLASS/@BUGREPORTS:')
    def bugreports(self, lines, line, lineno):
        if not lines:
            raise EclassDocParsingError(f'{repr(line)}, line {lineno}: missing bug reporting info')
        return tuple(lines)

    @eclass_doc('@ECLASS/@VCSURL:')
    def vcsurl(self, lines, line, lineno):
        try:
            return lines[0]
        except IndexError:
            raise EclassDocParsingError(f'{repr(line)}, line {lineno}: missing vcs url')

    @eclass_doc('@ECLASS/@BLURB:', required=True)
    def blurb(self, lines, line, lineno):
        try:
            return lines[0]
        except IndexError:
            raise EclassDocParsingError(f'{repr(line)}, line {lineno}: missing blurb text')

    @eclass_doc('@ECLASS/@DESCRIPTION:')
    def description(self, lines, line, lineno):
        if not lines:
            raise EclassDocParsingError(f'{repr(line)}, line {lineno}: missing description')
        return tuple(lines)

    @eclass_doc('@ECLASS/@EXAMPLE:')
    def example(self, lines, line, lineno):
        if not lines:
            raise EclassDocParsingError(f'{repr(line)}, line {lineno}: missing examples')
        return tuple(lines)

    # undocumented in devmanual
    @eclass_doc('@ECLASS/@SUPPORTED_EAPIS:')
    def supported_eapis(self, lines, line, lineno):
        return frozenset(lines[0].split())

    # not yet added to devmanual
    @eclass_doc('@ECLASS/@DEPRECATED:')
    def deprecated(self, lines, line, lineno):
        try:
            return lines[0]
        except IndexError:
            raise EclassDocParsingError(f'{repr(line)}, line {lineno}: missing deprecated text')


@eclass_block('@ECLASS-VARIABLE', 'variables')
class _EclassVarBlock(_EclassDoc):
    """ECLASS-VARIABLE doc block."""

    @eclass_doc('@ECLASS-VARIABLE/@ECLASS-VARIABLE:', required=True)
    def name(self, lines, line, lineno):
        try:
            return lines[0]
        except IndexError:
            raise EclassDocParsingError(f'{repr(line)}, line {lineno}: missing eclass variable name')

    @eclass_doc('@ECLASS-VARIABLE/@DEFAULT_UNSET')
    def default_unset(self, lines, line, lineno):
        if lines:
            raise EclassDocParsingError(
                f'{repr(line)}, line {lineno}: '
                f'tag takes no args, got {repr(lines[0])}'
            )
        return True

    @eclass_doc('@ECLASS-VARIABLE/@INTERNAL')
    def internal(self, lines, line, lineno):
        if lines:
            raise EclassDocParsingError(
                f'{repr(line)}, line {lineno}: '
                f'tag takes no args, got {repr(lines[0])}'
            )
        return True

    @eclass_doc('@ECLASS-VARIABLE/@REQUIRED')
    def required(self, lines, line, lineno):
        if lines:
            raise EclassDocParsingError(
                f'{repr(line)}, line {lineno}: '
                f'tag takes no args, got {repr(lines[0])}'
            )
        return True

    # undocumented in devmanual
    @eclass_doc('@ECLASS-VARIABLE/@PRE_INHERIT')
    def pre_inherit(self, lines, line, lineno):
        if lines:
            raise EclassDocParsingError(
                f'{repr(line)}, line {lineno}: '
                f'tag takes no args, got {repr(lines[0])}'
            )
        return True

    # undocumented in devmanual
    @eclass_doc('@ECLASS-VARIABLE/@USER_VARIABLE')
    def user_variable(self, lines, line, lineno):
        if lines:
            raise EclassDocParsingError(
                f'{repr(line)}, line {lineno}: '
                f'tag takes no args, got {repr(lines[0])}'
            )
        return True

    # undocumented in devmanual
    @eclass_doc('@ECLASS-VARIABLE/@OUTPUT_VARIABLE')
    def output_variable(self, lines, line, lineno):
        if lines:
            raise EclassDocParsingError(
                f'{repr(line)}, line {lineno}: '
                f'tag takes no args, got {repr(lines[0])}'
            )
        return True

    @eclass_doc('@ECLASS-VARIABLE/@DESCRIPTION:', required=True)
    def description(self, lines, line, lineno):
        if not lines:
            raise EclassDocParsingError(f'{repr(line)}, line {lineno}: missing description')
        return tuple(lines)

    # not yet added to devmanual
    @eclass_doc('@ECLASS-VARIABLE/@DEPRECATED:')
    def deprecated(self, lines, line, lineno):
        try:
            return lines[0]
        except IndexError:
            raise EclassDocParsingError(f'{repr(line)}, line {lineno}: missing deprecated text')


@eclass_block('@FUNCTION', 'functions')
class _EclassFuncBlock(_EclassDoc):
    """FUNCTION doc block."""

    @eclass_doc('@FUNCTION/@FUNCTION:', required=True)
    def name(self, lines, line, lineno):
        try:
            return lines[0]
        except IndexError:
            raise EclassDocParsingError(f'{repr(line)}, line {lineno}: missing function name')

    # TODO: The devmanual states this is required, but disabling for now since
    # many phase override functions don't document usage.
    @eclass_doc('@FUNCTION/@USAGE:')
    def usage(self, lines, line, lineno):
        # empty usage is allowed for functions with no arguments
        return tuple(lines)

    @eclass_doc('@FUNCTION/@RETURN:', name='return')
    def returns(self, lines, line, lineno):
        try:
            return lines[0]
        except IndexError:
            raise EclassDocParsingError(f'{repr(line)}, line {lineno}: missing return value')

    @eclass_doc('@FUNCTION/@MAINTAINER:')
    def maintainers(self, lines, line, lineno):
        if not lines:
            raise EclassDocParsingError(f'{repr(line)}, line {lineno}: missing maintainers')
        return tuple(lines)

    @eclass_doc('@FUNCTION/@INTERNAL')
    def internal(self, lines, line, lineno):
        if lines:
            raise EclassDocParsingError(
                f'{repr(line)}, line {lineno}: '
                f'tag takes no args, got {repr(lines[0])}'
            )
        return True

    @eclass_doc('@FUNCTION/@DESCRIPTION:')
    def description(self, lines, line, lineno):
        if not lines:
            raise EclassDocParsingError(f'{repr(line)}, line {lineno}: missing description')
        return tuple(lines)

    # not yet added to devmanual
    @eclass_doc('@FUNCTION/@DEPRECATED:')
    def deprecated(self, lines, line, lineno):
        try:
            return lines[0]
        except IndexError:
            raise EclassDocParsingError(f'{repr(line)}, line {lineno}: missing deprecated text')


@eclass_block('@VARIABLE', 'function-variables')
class _EclassFuncVarBlock(_EclassDoc):
    """VARIABLE doc block."""

    @eclass_doc('@VARIABLE/@VARIABLE:', required=True)
    def name(self, lines, line, lineno):
        try:
            return lines[0]
        except IndexError:
            raise EclassDocParsingError(f'{repr(line)}, line {lineno}: missing variable name')

    @eclass_doc('@VARIABLE/@DEFAULT_UNSET')
    def default_unset(self, lines, line, lineno):
        if lines:
            raise EclassDocParsingError(
                f'{repr(line)}, line {lineno}: '
                f'tag takes no args, got {repr(lines[0])}'
            )
        return True

    @eclass_doc('@VARIABLE/@INTERNAL')
    def internal(self, lines, line, lineno):
        if lines:
            raise EclassDocParsingError(
                f'{repr(line)}, line {lineno}: '
                f'tag takes no args, got {repr(lines[0])}'
            )
        return True

    @eclass_doc('@VARIABLE/@REQUIRED')
    def required(self, lines, line, lineno):
        if lines:
            raise EclassDocParsingError(
                f'{repr(line)}, line {lineno}: '
                f'tag takes no args, got {repr(lines[0])}'
            )
        return True

    @eclass_doc('@VARIABLE/@DESCRIPTION:', required=True)
    def description(self, lines, line, lineno):
        if not lines:
            raise EclassDocParsingError(f'{repr(line)}, line {lineno}: missing description')
        return tuple(lines)

    # not yet added to devmanual
    @eclass_doc('@VARIABLE/@DEPRECATED:')
    def deprecated(self, lines, line, lineno):
        try:
            return lines[0]
        except IndexError:
            raise EclassDocParsingError(f'{repr(line)}, line {lineno}: missing deprecated text')


class Eclass(UserDict):
    """Support parsing eclass docs for a given eclass path."""

    _eclass_blocks_re = re.compile(
        rf'^(?P<prefix>\s*#) (?P<tag>{"|".join(_eclass_blocks)}):(?P<value>.*)')

    def __init__(self, path):
        self.path = path
        self.mtime = os.path.getmtime(self.path)
        data = self.parse(self.path)
        super().__init__(data)

    @property
    def functions(self):
        """Tuple of documented function names in the eclass."""
        return tuple(d['name'] for d in self.data.get('functions', []))

    @property
    def variables(self):
        """Tuple of documented variable names in the eclass."""
        return tuple(d['name'] for d in self.data.get('variables', []))

    @classmethod
    def parse(cls, path):
        """Parse eclass docs."""
        d = dict()
        duplicates = {k: set() for k in _eclass_blocks.keys()}

        with open(path) as f:
            lines = f.read().splitlines()
            line_ind = 0
            while line_ind < len(lines):
                m = cls._eclass_blocks_re.match(lines[line_ind])
                if m is not None:
                    # Isolate identified doc block by pulling all following
                    # lines with a matching prefix before the tag.
                    prefix = m.group('prefix')
                    block = []
                    block_start = line_ind + 1
                    while line_ind < len(lines):
                        line = lines[line_ind]
                        if not line.startswith(prefix):
                            break
                        line = line[len(prefix) + 1:]
                        block.append(line)
                        line_ind += 1

                    # parse identified doc block
                    tag = m.group('tag')
                    obj, singular = _eclass_blocks[tag]
                    data = obj.parse(block, block_start)
                    if singular:
                        if data.keys() & d.keys():
                            _parsing_error_cb(EclassDocParsingError('duplicate ECLASS block'))
                        d.update(data)
                    else:
                        # check if duplicate named blocks exist
                        name = data['name']
                        if name in duplicates[tag]:
                            _parsing_error_cb(
                                EclassDocParsingError(f'duplicate {repr(block[0])} block'))
                        duplicates[tag].add(name)
                        d.setdefault(obj._name, []).append(data)
                else:
                    line_ind += 1

        return d


class _EclassCache(UserDict, caches.Cache):
    """Cache that encapsulates eclass data."""

    def __init__(self, data):
        super().__init__(data)
        self._cache = EclassAddon.cache


class EclassAddon(base.Addon, caches.CachedAddon):
    """Eclass support for various checks."""

    # cache registry
    cache = caches.CacheData(type='eclass', file='eclass.pickle', version=1)

    def __init__(self, *args):
        super().__init__(*args)
        self.eclasses = {}

    def update_cache(self, output_lock, force=False):
        """Update related cache and push updates to disk."""
        try:
            # running from scan subcommand
            repos = self.options.target_repo.trees
        except AttributeError:
            # running from cache subcommand
            repos = self.options.domain.ebuild_repos

        if self.options.cache['eclass']:
            for repo in repos:
                if repo.repo_id == 'gentoo':
                    cache_file = self.cache_file(repo)
                    cache_eclasses = False
                    eclasses = {}

                    if not force:
                        # try loading cached eclass data
                        try:
                            with open(cache_file, 'rb') as f:
                                eclasses = pickle.load(f)
                            if eclasses.version != self.cache.version:
                                logger.debug('forcing eclass repo cache regen due to outdated version')
                                os.remove(cache_file)
                        except FileNotFoundError:
                            pass
                        except (AttributeError, EOFError, ImportError, IndexError) as e:
                            logger.debug('forcing eclass cache regen: %s', e)
                            os.remove(cache_file)

                    # check for eclass removals
                    for name, eclass in list(eclasses.items()):
                        if not os.path.exists(eclass.path):
                            del eclasses[name]
                            cache_eclasses = True

                    # check for eclass additions and updates
                    for name, eclass in sorted(repo.eclass_cache.eclasses.items()):
                        try:
                            if os.path.getmtime(eclass.path) != eclasses[name].mtime:
                                raise KeyError
                        except (KeyError, AttributeError):
                            try:
                                eclasses[name] = Eclass(eclass.path)
                                cache_eclasses = True
                            except (IOError, EclassDocParsingError):
                                continue

                    # push eclasses to disk if any changes were found
                    if cache_eclasses:
                        try:
                            os.makedirs(os.path.dirname(cache_file), exist_ok=True)
                            with open(cache_file, 'wb+') as f:
                                pickle.dump(_EclassCache(eclasses), f)
                        except IOError as e:
                            msg = f'failed dumping eclasses: {cache_file!r}: {e.strerror}'
                            raise UserException(msg)

                    self.eclasses = eclasses
