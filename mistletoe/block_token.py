"""
Built-in block-level token classes.
"""

import re
from itertools import zip_longest
import mistletoe.block_tokenizer as tokenizer
from mistletoe import token, span_token
from mistletoe.core_tokens import (
        follows,
        shift_whitespace,
        whitespace,
        is_control_char,
        normalize_label,
)


"""
Tokens to be included in the parsing process, in the order specified.
"""
__all__ = ['BlockCode', 'Heading', 'Quote', 'CodeFence', 'ThematicBreak',
           'List', 'Table', 'Footnote', 'Paragraph']


def tokenize(lines):
    """
    A wrapper around block_tokenizer.tokenize. Pass in all block-level
    token constructors as arguments to block_tokenizer.tokenize.

    Doing so (instead of importing block_token module in block_tokenizer)
    avoids cyclic dependency issues, and allows for future injections of
    custom token classes.

    _token_types variable is at the bottom of this module.

    See also: block_tokenizer.tokenize, span_token.tokenize_inner.
    """
    return tokenizer.tokenize(lines, _token_types)


def add_token(token_cls, position=0):
    """
    Allows external manipulation of the parsing process.
    This function is usually called in BaseRenderer.__enter__.

    Arguments:
        token_cls (SpanToken): token to be included in the parsing process.
        position (int): the position for the token class to be inserted into.
    """
    _token_types.insert(position, token_cls)


def remove_token(token_cls):
    """
    Allows external manipulation of the parsing process.
    This function is usually called in BaseRenderer.__exit__.

    Arguments:
        token_cls (BlockToken): token to be removed from the parsing process.
    """
    _token_types.remove(token_cls)


def reset_tokens():
    """
    Resets global _token_types to all token classes in __all__.
    """
    global _token_types
    _token_types = [globals()[cls_name] for cls_name in __all__]


class BlockToken(token.Token):
    """
    Base class for block-level tokens. Recursively parse inner tokens.

    Naming conventions:

        * lines denotes a list of (possibly unparsed) input lines, and is
          commonly used as the argument name for constructors.

        * BlockToken.children is a list with all the inner tokens (thus if
          a token has children attribute, it is not a leaf node; if a token
          calls span_token.tokenize_inner, it is the boundary between
          span-level tokens and block-level tokens);

        * BlockToken.start takes a line from the document as argument, and
          returns a boolean representing whether that line marks the start
          of the current token. Every subclass of BlockToken must define a
          start function (see block_tokenizer.tokenize).

        * BlockToken.read takes the rest of the lines in the ducment as an
          iterator (including the start line), and consumes all the lines
          that should be read into this token.

          Default to stop at an empty line.
          
          Note that BlockToken.read does not have to return a list of lines.
          Because the return value of this function will be directly
          passed into the token constructor, we can return any relevant
          parsing information, sometimes even ready-made tokens,
          into the constructor. See block_tokenizer.tokenize.

          If BlockToken.read returns None, the read result is ignored,
          but the token class is responsible for resetting the iterator
          to a previous state. See block_tokenizer.FileWrapper.anchor,
          block_tokenizer.FileWrapper.reset.

    Attributes:
        children (list): inner tokens.
    """
    def __init__(self, lines, tokenize_func):
        self.children = tokenize_func(lines)

    def __contains__(self, text):
        return any(text in child for child in self.children)
    
    @staticmethod
    def read(lines):
        line_buffer = [next(lines)]
        for line in lines:
            if line == '\n':
                break
            line_buffer.append(line)
        return line_buffer


class Document(BlockToken):
    """
    Document token.
    This is a container block token. Its children are block tokens - container or leaf ones.
    """
    def __init__(self, lines):
        if isinstance(lines, str):
            lines = lines.splitlines(keepends=True)
        lines = [line if line.endswith('\n') else '{}\n'.format(line) for line in lines]
        self.footnotes = {}
        token._root_node = self
        self.children = tokenize(lines)
        token._root_node = None


class Heading(BlockToken):
    """
    ATX heading token. (["### some heading ###\\n"])
    This is a leaf block token. Its children are inline (span) tokens.

    Attributes:
        level (int): heading level.
        children (list): inner tokens.
    """
    repr_attributes = ("level",)
    pattern = re.compile(r' {0,3}(#{1,6})(?:\n|\s+?(.*?)(?:\n|\s+?#+\s*?$))')
    level = 0
    content = ''

    def __init__(self, match):
        self.level, content = match
        super().__init__(content, span_token.tokenize_inner)

    @classmethod
    def start(cls, line):
        match_obj = cls.pattern.match(line)
        if match_obj is None:
            return False
        cls.level = len(match_obj.group(1))
        cls.content = (match_obj.group(2) or '').strip()
        if set(cls.content) == {'#'}:
            cls.content = ''
        return True

    @classmethod
    def read(cls, lines):
        next(lines)
        return cls.level, cls.content

class SetextHeading(BlockToken):
    """
    Setext heading token.
    This is a leaf block token. Its children are inline (span) tokens.

    Not included in the parsing process, but called by Paragraph.__new__.

    Attributes:
        level (int): heading level.
    """
    repr_attributes = ("level",)
    def __init__(self, lines):
        self.level = 1 if lines.pop().lstrip().startswith('=') else 2
        content = '\n'.join([line.strip() for line in lines])
        super().__init__(content, span_token.tokenize_inner)

    @classmethod
    def start(cls, line):
        raise NotImplementedError()

    @classmethod
    def read(cls, lines):
        raise NotImplementedError()


class Quote(BlockToken):
    """
    Block quote token. (["> # heading\\n", "> paragraph\\n"])
    This is a container block token. Its children are block tokens - container or leaf ones.
    """
    def __init__(self, parse_buffer):
        # span-level tokenizing happens here.
        self.children = tokenizer.make_tokens(parse_buffer)

    @staticmethod
    def start(line):
        stripped = line.lstrip(' ')
        if len(line) - len(stripped) > 3:
            return False
        return stripped.startswith('>')

    @classmethod
    def read(cls, lines):
        # first line
        line = cls.convert_leading_tabs(next(lines).lstrip()).split('>', 1)[1]
        if len(line) > 0 and line[0] == ' ':
            line = line[1:]
        line_buffer = [line]

        # set booleans
        in_code_fence = CodeFence.start(line)
        in_block_code = BlockCode.start(line)
        blank_line = line.strip() == ''

        # loop
        next_line = lines.peek()
        while (next_line is not None
                and next_line.strip() != ''
                and not Heading.start(next_line)
                and not CodeFence.start(next_line)
                and not ThematicBreak.start(next_line)
                and not List.start(next_line)):
            stripped = cls.convert_leading_tabs(next_line.lstrip())
            prepend = 0
            if stripped[0] == '>':
                # has leader, not lazy continuation
                prepend += 1
                if stripped[1] == ' ':
                    prepend += 1
                stripped = stripped[prepend:]
                in_code_fence = CodeFence.start(stripped)
                in_block_code = BlockCode.start(stripped)
                blank_line = stripped.strip() == ''
                line_buffer.append(stripped)
            elif in_code_fence or in_block_code or blank_line:
                # not paragraph continuation text
                break
            else:
                # lazy continuation, preserve whitespace
                line_buffer.append(next_line)
            next(lines)
            next_line = lines.peek()

        # block level tokens are parsed here, so that footnotes
        # in quotes can be recognized before span-level tokenizing.
        Paragraph.parse_setext = False
        parse_buffer = tokenizer.tokenize_block(line_buffer, _token_types)
        Paragraph.parse_setext = True
        return parse_buffer

    @staticmethod
    def convert_leading_tabs(string):
        string = string.replace('>\t', '   ', 1)
        count = 0
        for i, c in enumerate(string):
            if c == '\t':
                count += 4
            elif c == ' ':
                count += 1
            else:
                break
        if i == 0:
            return string
        return '>' + ' ' * count + string[i:]


class Paragraph(BlockToken):
    """
    Paragraph token. (["some\\n", "continuous\\n", "lines\\n"])
    This is a leaf block token. Its children are inline (span) tokens.
    """
    setext_pattern = re.compile(r' {0,3}(=|-)+ *$')
    parse_setext = True  # can be disabled by Quote

    def __new__(cls, lines):
        if not isinstance(lines, list):
            # setext heading token, return directly
            return lines
        return super().__new__(cls)

    def __init__(self, lines):
        content = ''.join([line.lstrip() for line in lines]).strip()
        super().__init__(content, span_token.tokenize_inner)

    @staticmethod
    def start(line):
        return line.strip() != ''

    @classmethod
    def read(cls, lines):
        line_buffer = [next(lines)]
        next_line = lines.peek()
        while (next_line is not None
                and next_line.strip() != ''
                and not Heading.start(next_line)
                and not CodeFence.start(next_line)
                and not Quote.start(next_line)):

            # check if next_line starts List
            marker_tuple = ListItem.parse_marker(next_line)
            if (marker_tuple is not None):
                _, leader, content = marker_tuple
                # to break a paragraph, the first line may not be empty,
                # and the list must be unordered or start from 1.
                if not content.strip() == '':
                    if not leader[0].isdigit() or leader in ['1.', '1)']:
                        break

            # check if next_line starts HTMLBlock other than type 7
            html_block = HTMLBlock.start(next_line)
            if html_block and html_block != 7:
                break

            # check if we see a setext underline
            if cls.parse_setext and cls.is_setext_heading(next_line):
                line_buffer.append(next(lines))
                return SetextHeading(line_buffer)

            # check if we have a ThematicBreak (has to be after setext)
            if ThematicBreak.start(next_line):
                break

            # no other tokens, we're good
            line_buffer.append(next(lines))
            next_line = lines.peek()
        return line_buffer

    @classmethod
    def is_setext_heading(cls, line):
        return cls.setext_pattern.match(line)


class BlockCode(BlockToken):
    """
    Indented code block token.
    This is a leaf block token with a single child of type span_token.RawText.

    Attributes:
        children (list): contains a single span_token.RawText token.
        language (str): always the empty string.
    """
    repr_attributes = ("language",)
    def __init__(self, lines):
        self.language = ''
        self.children = (span_token.RawText(''.join(lines).strip('\n')+'\n'),)

    @staticmethod
    def start(line):
        return line.replace('\t', '    ', 1).startswith('    ')

    @classmethod
    def read(cls, lines):
        line_buffer = []
        for line in lines:
            if line.strip() == '':
                line_buffer.append(line.lstrip(' ') if len(line) < 5 else line[4:])
                continue
            if not line.replace('\t', '    ', 1).startswith('    '):
                lines.backstep()
                break
            line_buffer.append(cls.strip(line))
        return line_buffer

    @staticmethod
    def strip(string):
        count = 0
        for i, c in enumerate(string):
            if c == '\t':
                return string[i+1:]
            elif c == ' ':
                count += 1
            else:
                break
            if count == 4:
                return string[i+1:]
        return string


class CodeFence(BlockToken):
    """
    Fenced code block token. (["```sh\\n", "rm -rf /", ..., "```"])
    This is a leaf block token with a single child of type span_token.RawText.

    Attributes:
        children (list): contains a single span_token.RawText token.
        language (str): language of code block (default to empty).
    """
    repr_attributes = ("language",)
    pattern = re.compile(r'( {0,3})(`{3,}|~{3,}) *(\S*)')
    _open_info = None
    def __init__(self, match):
        lines, open_info = match
        self.language = span_token.EscapeSequence.strip(open_info[2])
        self.children = (span_token.RawText(''.join(lines)),)

    @classmethod
    def start(cls, line):
        match_obj = cls.pattern.match(line)
        if not match_obj:
            return False
        prepend, leader, lang = match_obj.groups()
        # info strings for backtick code blocks may not contain backticks,
        # but info strings for tilde code blocks may contain both tildes and backticks.
        if leader[0] == '`' and '`' in line[match_obj.end(2):]:
            return False
        cls._open_info = len(prepend), leader, lang
        return True

    @classmethod
    def read(cls, lines):
        next(lines)
        line_buffer = []
        for line in lines:
            stripped_line = line.lstrip(' ')
            diff = len(line) - len(stripped_line)
            if (stripped_line.startswith(cls._open_info[1])
                    and len(stripped_line.split(maxsplit=1)) == 1
                    and diff < 4):
                break
            if diff > cls._open_info[0]:
                stripped_line = ' ' * (diff - cls._open_info[0]) + stripped_line
            line_buffer.append(stripped_line)
        return line_buffer, cls._open_info


class List(BlockToken):
    """
    List token.
    This is a container block token. Its children are list item tokens.

    Attributes:
        children (list): a list of ListItem tokens.
        loose (bool): whether the list is loose.
        start (NoneType or int): None if unordered, starting number if ordered.
    """
    repr_attributes = ("loose", "start")
    pattern = re.compile(r' {0,3}(?:\d{0,9}[.)]|[+\-*])(?:[ \t]*$|[ \t]+)')
    def __init__(self, matches):
        self.children = [ListItem(*match) for match in matches]
        self.loose = any(item.loose for item in self.children)
        leader = self.children[0].leader
        self.start = None
        if len(leader) != 1:
            self.start = int(leader[:-1])

    @classmethod
    def start(cls, line):
        return cls.pattern.match(line)

    @classmethod
    def read(cls, lines):
        leader = None
        next_marker = None
        matches = []
        while True:
            output, next_marker = ListItem.read(lines, next_marker)
            item_leader = output[2]
            if leader is None:
                leader = item_leader
            elif not cls.same_marker_type(leader, item_leader):
                lines.reset()
                break
            matches.append(output)
            if next_marker is None:
                break

        if matches:
            # Only consider the last list item loose if there's more than one element
            last_parse_buffer = matches[-1][0]
            last_parse_buffer.loose = len(last_parse_buffer) > 1 and last_parse_buffer.loose

        return matches

    @staticmethod
    def same_marker_type(leader, other):
        if len(leader) == 1:
            return leader == other
        return leader[:-1].isdigit() and other[:-1].isdigit() and leader[-1] == other[-1]


class ListItem(BlockToken):
    """
    List item token.
    This is a container block token. Its children are block tokens - container or leaf ones.

    Not included in the parsing process, but called by List.
    """
    repr_attributes = ("leader", "prepend", "loose")
    pattern = re.compile(r' {0,3}(\d{0,9}[.)]|[+\-*])($|\s+)')
    continuation_pattern = re.compile(r'([ \t]*)(\S.*\n|\n)')

    def __init__(self, parse_buffer, prepend, leader):
        self.leader = leader
        self.prepend = prepend
        self.children = tokenizer.make_tokens(parse_buffer)
        self.loose = parse_buffer.loose

    @classmethod
    def parse_continuation(cls, line, prepend):
        """
        Returns content (i.e. the line with the prepend stripped off) iff the line
        is a valid continuation line for a list item with the given prepend length,
        otherwise None.

        Note that the list item may still continue even if this test doesn't pass
        due to lazy continuation.
        """
        match_obj = cls.continuation_pattern.match(line)
        if match_obj is None:
            return None
        if match_obj.group(2) == '\n':
            return '\n'
        expanded_spaces = match_obj.group(1).expandtabs(4)
        return expanded_spaces[prepend:] + match_obj.group(2) if len(expanded_spaces) >= prepend else None

    @staticmethod
    def other_token(line):
        return (Heading.start(line)
                or Quote.start(line)
                or CodeFence.start(line)
                or ThematicBreak.start(line))

    @classmethod
    def parse_marker(cls, line):
        """
        Returns a tuple (prepend, leader, content) iff the line has a valid leader and at
        least one space separating leader and content, or if the content is empty, in which
        case there need not be any spaces.
        The return value is None if the line doesn't have a valid marker.

        The leader is a bullet list marker, or an ordered list marker.

        The prepend is the start position of the content, i.e., the indentation required
        for continuation lines.
        """
        match_obj = cls.pattern.match(line)
        if match_obj is None:
            return None
        prepend = len(match_obj.group(0).expandtabs(4))
        leader = match_obj.group(1)
        content = line[match_obj.end(0):]
        n_spaces = prepend - match_obj.end(1)
        if n_spaces > 4:
            # if there are more than 4 spaces after the leader, we treat them as part of the content
            # with the exception of the first (marker separator) space.
            prepend -= n_spaces - 1
            content = ' ' * (n_spaces - 1) + content
        return prepend, leader, content

    @classmethod
    def read(cls, lines, prev_marker=None):
        next_marker = None
        lines.anchor()
        line_buffer = []

        # first line
        line = next(lines)
        next_line = lines.peek()
        prepend, leader, content = prev_marker if prev_marker else cls.parse_marker(line)
        if content.strip() == '':
            # item starting with a blank line: look for the next non-blank line
            prepend = len(leader) + 1
            blanks = 1
            while next_line is not None and next_line.strip() == '':
                blanks += 1
                next(lines)
                next_line = lines.peek()
            # if the line following the list marker is also empty, then this is an empty
            # list item.
            if blanks > 1:
                parse_buffer = tokenizer.ParseBuffer()
                parse_buffer.loose = True
                next_marker = cls.parse_marker(next_line) if next_line is not None else None
                return (parse_buffer, prepend, leader), next_marker
        else:
            line_buffer.append(content)

        # loop over the following lines, looking for the end of the list item
        newline_count = 0
        while True:
            if next_line is None:
                # list item ends here because we have reached the end of content
                if newline_count:
                    lines.backstep()
                    del line_buffer[-newline_count:]
                break

            continuation = cls.parse_continuation(next_line, prepend)
            if not continuation:
                # the line doesn't have the indentation to show that it belongs to
                # the list item, but it should be included anyway by lazy continuation...
                # ...unless it's the start of another token
                if cls.other_token(next_line):
                    if newline_count:
                        lines.backstep()
                        del line_buffer[-newline_count:]
                    break
                # ...or it's a new list item
                marker_info = cls.parse_marker(next_line)
                if marker_info is not None:
                    next_marker = marker_info
                    break
                # ...or the line above it was blank
                if newline_count:
                    lines.backstep()
                    del line_buffer[-newline_count:]
                    break
                continuation = next_line

            line_buffer.append(continuation)
            newline_count = newline_count + 1 if continuation == '\n' else 0
            next(lines)
            next_line = lines.peek()

        # block-level tokens are parsed here, so that footnotes can be
        # recognized before span-level parsing.
        parse_buffer = tokenizer.tokenize_block(line_buffer, _token_types)
        return (parse_buffer, prepend, leader), next_marker


class Table(BlockToken):
    """
    Table token.
    This is a container block token. Its children are table row tokens.

    Attributes:
        has_header (bool): whether table has header row.
        column_align (list): align options for each column (default to [None]).
        children (list): inner tokens (TableRows).
    """
    repr_attributes = ("column_align",)
    def __init__(self, lines):
        if '---' in lines[1]:
            self.column_align = [self.parse_align(column)
                    for column in self.split_delimiter(lines[1])]
            self.header = TableRow(lines[0], self.column_align)
            self.children = [TableRow(line, self.column_align) for line in lines[2:]]
        else:
            self.column_align = [None]
            self.children = [TableRow(line) for line in lines]

    @staticmethod
    def split_delimiter(delimiter):
        """
        Helper function; returns a list of align options.

        Args:
            delimiter (str): e.g.: "| :--- | :---: | ---: |\n"

        Returns:
            a list of align options (None, 0 or 1).
        """
        return re.findall(r':?---+:?', delimiter)

    @staticmethod
    def parse_align(column):
        """
        Helper function; returns align option from cell content.

        Returns:
            None if align = left;
            0    if align = center;
            1    if align = right.
        """
        return (0 if column[0] == ':' else 1) if column[-1] == ':' else None

    @staticmethod
    def start(line):
        return '|' in line

    @staticmethod
    def read(lines):
        lines.anchor()
        line_buffer = [next(lines)]
        while lines.peek() is not None and '|' in lines.peek():
            line_buffer.append(next(lines))
        if len(line_buffer) < 2 or '---' not in line_buffer[1]:
            lines.reset()
            return None
        return line_buffer


class TableRow(BlockToken):
    """
    Table row token. Supports escaped pipes in table cells (for primary use within code spans).
    This is a container block token. Its children are table cell tokens.

    Should only be called by Table.__init__().
    """
    repr_attributes = ("row_align",)
    # Note: Python regex requires fixed-length look-behind,
    # so we cannot use a more precise alternative: r"(?<!\\(?:\\\\)*)(\|)"
    split_pattern = re.compile(r"(?<!\\)\|")
    escaped_pipe_pattern = re.compile(r"(?<!\\)(\\\\)*\\\|")

    def __init__(self, line, row_align=None):
        self.row_align = row_align or [None]
        cells = filter(None, self.split_pattern.split(line.strip()))
        self.children = [TableCell(self.escaped_pipe_pattern.sub('\\1|', cell.strip()) if cell else '', align)
                         for cell, align in zip_longest(cells, self.row_align)]


class TableCell(BlockToken):
    """
    Table cell token.
    This is a leaf block token. Its children are inline (span) tokens.

    Should only be called by TableRow.__init__().

    Attributes:
        align (bool): align option for current cell (default to None).
        children (list): inner (span-)tokens.
    """
    repr_attributes = ("align",)
    def __init__(self, content, align=None):
        self.align = align
        super().__init__(content, span_token.tokenize_inner)


class Footnote(BlockToken):
    """
    Footnote token. A "link reference definition" according to the spec.
    This is a leaf block token. Its children are inline (span) tokens.

    The constructor returns None, because the footnote information
    is stored in Footnote.read.
    """
    def __new__(cls, _):
        return None

    @classmethod
    def start(cls, line):
        return line.lstrip().startswith('[')

    @classmethod
    def read(cls, lines):
        line_buffer = []
        next_line = lines.peek()
        while next_line is not None and next_line.strip() != '':
            line_buffer.append(next(lines))
            next_line = lines.peek()
        string = ''.join(line_buffer)
        offset = 0
        matches = []
        while offset < len(string) - 1:
            match_info = cls.match_reference(string, offset)
            if match_info is None:
                # backtrack the lines that have not been consumed
                lines._index -= string[offset:].count('\n')
                break
            offset, match = match_info
            matches.append(match)
        cls.append_footnotes(matches, token._root_node)
        return matches or None

    @classmethod
    def match_reference(cls, string, offset):
        # up to three spaces, "[", label, "]"
        match_info = cls.match_link_label(string, offset)
        if not match_info:
            return None
        _, label_end, label = match_info

        # ":"
        if not follows(string, label_end-1, ':'):
            return None

        # optional spaces or tabs (including up to one line ending)
        dest_start = shift_whitespace(string, label_end + 1)
        if dest_start == len(string):
            return None

        # link destination
        match_info = cls.match_link_dest(string, dest_start)
        if not match_info:
            return None
        _, dest_end, dest = match_info

        # either of:
        # 1) optional spaces or tabs and then a line break to finish the link reference definition.
        # 2) optional spaces or tabs (including up to one line ending) followed by a title.
        # in any case, if the destination is followed directly by non-whitespace, then it's not
        # a valid link reference definition.
        title_start = shift_whitespace(string, dest_end)
        if title_start == dest_end and title_start < len(string):
            return None

        # link title
        match_info = cls.match_link_title(string, title_start)
        if not match_info:
            # no valid title found. if there was a line break following the destination,
            # we still have a valid link reference definition. otherwise not.
            eol_pos = string[dest_end:title_start].find("\n")
            if eol_pos >= 0:
                return dest_end + eol_pos + 1, (label, dest, "")
            else:
                return None
        _, title_end, title = match_info

        # optional spaces or tabs. final line ending.
        line_end = title_end
        while line_end < len(string):
            if string[line_end] == '\n':
                return line_end + 1, (label, dest, title)
            elif string[line_end] in whitespace:
                line_end += 1
            else:
                break

        # non-whitespace found on the same line as the title, making it invalid.
        # if there was a line break following the destination,
        # we still have a valid link reference definition. otherwise not.
        eol_pos = string[dest_end:title_start].find("\n")
        if eol_pos >= 0:
            return dest_end + eol_pos + 1, (label, dest, "")
        else:
            return None

    @classmethod
    def match_link_label(cls, string, offset):
        """
        Matches: up to three spaces, "[", label, "]".
        """
        start = -1
        escaped = False
        for i, c in enumerate(string[offset:], start=offset):
            if escaped:
                escaped = False
            elif c == '\\':
                escaped = True
            elif c == '[':
                if start == -1:
                    start = i
                else:
                    return None
            elif c == ']':
                label = string[start+1:i]
                if label.strip() != '':
                    return start, i+1, label
                return None
            # only spaces allowed before the opening bracket
            if start == -1 and not (c == " " and i - offset < 3):
                return None
        return None

    @classmethod
    def match_link_dest(cls, string, offset):
        if string[offset] == '<':
            escaped = False
            for i, c in enumerate(string[offset+1:], start=offset+1):
                if c == '\\' and not escaped:
                    escaped = True
                elif c == '\n' or (c == '<' and not escaped):
                    return None
                elif c == '>' and not escaped:
                    return offset, i+1, string[offset+1:i]
                elif escaped:
                    escaped = False
            return None
        else:
            escaped = False
            count = 0
            for i, c in enumerate(string[offset:], start=offset):
                if c == '\\' and not escaped:
                    escaped = True
                elif c in whitespace:
                    break
                elif not escaped:
                    if c == '(':
                        count += 1
                    elif c == ')':
                        count -= 1
                elif is_control_char(c):
                    return None
                elif escaped:
                    escaped = False
            if count != 0:
                return None
            return offset, i, string[offset:i]

    @classmethod
    def match_link_title(cls, string, offset):
        if offset == len(string):
            return None
        if string[offset] == '"':
            closing = '"'
        elif string[offset] == "'":
            closing = "'"
        elif string[offset] == '(':
            closing = ')'
        else:
            return None
        escaped = False
        for i, c in enumerate(string[offset+1:], start=offset+1):
            if c == '\\' and not escaped:
                escaped = True
            elif c == closing and not escaped:
                return offset, i+1, string[offset+1:i]
            elif escaped:
                escaped = False
        return None

    @staticmethod
    def append_footnotes(matches, root):
        for key, dest, title in matches:
            key = normalize_label(key)
            dest = span_token.EscapeSequence.strip(dest.strip())
            title = span_token.EscapeSequence.strip(title)
            if key not in root.footnotes:
                root.footnotes[key] = dest, title


class ThematicBreak(BlockToken):
    """
    Thematic break token (a.k.a. horizontal rule.)
    This is a leaf block token without children.
    """
    pattern = re.compile(r' {0,3}(?:([-_*])\s*?)(?:\1\s*?){2,}$')
    def __init__(self, _):
        pass

    @classmethod
    def start(cls, line):
        return cls.pattern.match(line)

    @staticmethod
    def read(lines):
        return [next(lines)]


class HTMLBlock(BlockToken):
    """
    Block-level HTML token.
    This is a leaf block token without children.

    Attributes:
        content (str): the raw HTML content.
    """
    _end_cond = None
    multiblock = re.compile(r'<(pre|script|style|textarea)[ >\n]')
    predefined = re.compile(r'<\/?(.+?)(?:\/?>|[ \n])')
    custom_tag = re.compile(r'(?:' + '|'.join((span_token._open_tag,
                                span_token._closing_tag)) + r')\s*$')

    def __init__(self, lines):
        self.content = ''.join(lines).rstrip('\n')

    @classmethod
    def start(cls, line):
        stripped = line.lstrip()
        if len(line) - len(stripped) >= 4:
            return False
        # rule 1: HTML tags designed to contain literal content, allow newlines in block
        match_obj = cls.multiblock.match(stripped)
        if match_obj is not None:
            cls._end_cond = '</{}>'.format(match_obj.group(1).casefold())
            return 1
        # rule 2: html comment tags, allow newlines in block
        if stripped.startswith('<!--'):
            cls._end_cond = '-->'
            return 2
        # rule 3: tags that starts with <?, allow newlines in block
        if stripped.startswith('<?'):
            cls._end_cond = '?>'
            return 3
        # rule 4: tags that starts with <!, allow newlines in block
        if stripped.startswith('<!') and stripped[2].isupper():
            cls._end_cond = '>'
            return 4
        # rule 5: CDATA declaration, allow newlines in block
        if stripped.startswith('<![CDATA['):
            cls._end_cond = ']]>'
            return 5
        # rule 6: predefined tags (see html_token._tags), read until newline
        match_obj = cls.predefined.match(stripped)
        if match_obj is not None and match_obj.group(1).casefold() in span_token._tags:
            cls._end_cond = None
            return 6
        # rule 7: custom tags, read until newline
        match_obj = cls.custom_tag.match(stripped)
        if match_obj is not None:
            cls._end_cond = None
            return 7
        return False

    @classmethod
    def read(cls, lines):
        # note: stop condition can trigger on the starting line
        line_buffer = []
        for line in lines:
            line_buffer.append(line)
            if cls._end_cond is not None:
                if cls._end_cond in line.casefold():
                    break
            elif line.strip() == '':
                line_buffer.pop()
                break
        return line_buffer


_token_types = []
reset_tokens()

