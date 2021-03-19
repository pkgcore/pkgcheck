"""Various miscellaneous utility functions."""

# based on https://github.com/audreyr/binaryornot
#
# Copyright (c) 2013, Audrey Roy
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# * Neither the name of BinaryOrNot nor the names of its contributors may be used
#   to endorse or promote products derived from this software without specific
#   prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

_control_chars = b'\n\r\t\f\b'
_printable_ascii = _control_chars + bytes(range(32, 127))
_printable_high_ascii = bytes(range(127, 256))


def is_binary(path, blocksize=1024):
    """Check if a given file is binary or not.

    Uses a simplified version of the Perl detection algorithm, based roughly on
    Eli Bendersky's translation to Python:
    http://eli.thegreenplace.net/2011/10/19/perls-guess-if-file-is-text-or-binary-implemented-in-python/

    This is biased slightly more in favour of deeming files as text files than
    the Perl algorithm, since all ASCII compatible character sets are accepted as
    text, not just utf-8.

    :param path: Path to a file to check.
    :param blocksize: Amount of bytes to read for determination.
    :returns: True if appears to be a binary, otherwise False.
    """
    try:
        with open(path, 'rb') as f:
            byte_str = f.read(blocksize)
    except IOError:
        return False

    # empty files are considered text
    if not byte_str:
        return False

    # Now check for a high percentage of ASCII control characters
    # Binary if control chars are > 30% of the string
    low_chars = byte_str.translate(None, _printable_ascii)
    nontext_ratio1 = len(low_chars) / len(byte_str)

    # and check for a low percentage of high ASCII characters:
    # Binary if high ASCII chars are < 5% of the string
    # From: https://en.wikipedia.org/wiki/UTF-8
    # If the bytes are random, the chances of a byte with the high bit set
    # starting a valid UTF-8 character is only 6.64%. The chances of finding 7
    # of these without finding an invalid sequence is actually lower than the
    # chance of the first three bytes randomly being the UTF-8 BOM.
    high_chars = byte_str.translate(None, _printable_high_ascii)
    nontext_ratio2 = len(high_chars) / len(byte_str)

    is_likely_binary = (
        (nontext_ratio1 > 0.3 and nontext_ratio2 < 0.05) or
        (nontext_ratio1 > 0.8 and nontext_ratio2 > 0.8)
    )

    decodable = False
    try:
        byte_str.decode()
        decodable = True
    except UnicodeDecodeError:
        # Delay import to hide during wheel/sdist builds that iterate over and
        # import most modules to generate check/keyword/reporter lists.
        import chardet

        # guess character encoding using chardet
        detected_encoding = chardet.detect(byte_str)
        if detected_encoding['confidence'] > 0.8:
            try:
                byte_str.decode(encoding=detected_encoding['encoding'])
                decodable = True
            except (UnicodeDecodeError, LookupError):
                pass

    # finally use all the checks to decide binary or text
    if decodable:
        return False
    if is_likely_binary or b'\x00' in byte_str:
        return True
    return False
