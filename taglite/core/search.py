"""Search engine: tokenizer, recursive-descent parser, AST, and executor."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select

from taglite.db.engine import session_scope
from taglite.db.models import File, FileTag, Tag


# ---------------------------------------------------------------------------
# AST nodes
# ---------------------------------------------------------------------------

class SearchNode:
    """Base class for search AST nodes."""
    pass


@dataclass
class TermNode(SearchNode):
    """Leaf node: a single search condition."""
    type: str       # "name", "tag", "ext", "size_gt", "size_lt", "after", "before"
    value: str      # condition value
    key: str = ""   # tag-specific: KV tag key


@dataclass
class AndNode(SearchNode):
    children: list[SearchNode] = field(default_factory=list)


@dataclass
class OrNode(SearchNode):
    children: list[SearchNode] = field(default_factory=list)


@dataclass
class NotNode(SearchNode):
    child: SearchNode = field(default_factory=lambda: TermNode(type="name", value=""))


@dataclass
class SearchQuery:
    """Parsed search query."""
    raw: str
    root: SearchNode | None
    parse_ok: bool
    error: str = ""


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

# Prefixed terms: tag:xxx, ext:xxx, size>N, size<N, after:date, before:date
_PREFIX_RE = re.compile(
    r"""(?x)
    -?(?:tag|ext|after|before):  # colon-based prefixes (optionally negated)
    | -?size[><]                 # size comparisons
    """
)

_SIZE_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*(b|kb|mb|gb|tb)?$", re.IGNORECASE)

_SIZE_UNITS = {
    "b": 1,
    "kb": 1024,
    "mb": 1024 ** 2,
    "gb": 1024 ** 3,
    "tb": 1024 ** 4,
}


def _parse_size(s: str) -> int | None:
    """Parse a size string like '1MB', '100KB', '500' into bytes."""
    m = _SIZE_RE.match(s.strip())
    if not m:
        return None
    num = float(m.group(1))
    unit = (m.group(2) or "b").lower()
    return int(num * _SIZE_UNITS.get(unit, 1))


def _parse_date(s: str) -> datetime | None:
    """Parse a date string into a UTC datetime."""
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


@dataclass
class Token:
    type: str  # "TERM", "AND", "OR", "NOT", "LPAREN", "RPAREN"
    value: str = ""
    node: SearchNode | None = None  # pre-built node for TERM tokens


def _has_prefix(text: str) -> bool:
    """Check if the text contains any search prefix operators."""
    prefixes = ("tag:", "ext:", "size>", "size<", "after:", "before:",
                "-tag:", "-ext:")
    return any(p in text.lower() for p in prefixes)


def _tokenize(text: str, strict: bool = False) -> list[Token]:
    """Tokenize search text into a list of tokens.

    If strict=True (prefixed search mode), bare words without a recognized
    prefix raise ParseError.
    """
    tokens: list[Token] = []
    i = 0
    n = len(text)

    while i < n:
        # Skip whitespace
        if text[i].isspace():
            i += 1
            continue

        # Parentheses
        if text[i] == "(":
            tokens.append(Token(type="LPAREN"))
            i += 1
            continue
        if text[i] == ")":
            tokens.append(Token(type="RPAREN"))
            i += 1
            continue

        # Check for operators AND, OR, NOT (case-insensitive)
        rest = text[i:]
        for op in ("AND", "OR", "NOT"):
            if rest.upper().startswith(op):
                after = i + len(op)
                # Must be followed by space, paren, or end
                if after >= n or text[after].isspace() or text[after] in "()":
                    tokens.append(Token(type=op.upper()))
                    i = after
                    break
        else:
            # Parse a term (possibly prefixed)
            negated = False
            if text[i] == "-" and i + 1 < n and not text[i + 1].isspace():
                # Check if this is a negation prefix (e.g., -tag:xxx, -ext:xxx)
                peek = text[i + 1:]
                if any(peek.lower().startswith(p) for p in ("tag:", "ext:")):
                    negated = True
                    i += 1

            # Collect the term text (until space, paren, or end)
            start = i
            while i < n and not text[i].isspace() and text[i] not in "()":
                i += 1
            term_text = text[start:i]

            if not term_text:
                i += 1
                continue

            node = _parse_term(term_text)

            # In strict mode, bare name terms are errors
            if strict and isinstance(node, TermNode) and node.type == "name":
                raise ParseError(f"无法识别 '{term_text}'")

            if negated:
                node = NotNode(child=node)

            tokens.append(Token(type="TERM", value=term_text, node=node))

    return tokens


def _parse_term(text: str) -> SearchNode:
    """Parse a single term like 'tag:重要', 'ext:pdf', 'size>1MB' into a TermNode."""
    lower = text.lower()

    # tag:value or tag:key=value
    if lower.startswith("tag:"):
        val = text[4:]
        if "=" in val:
            key, _, value = val.partition("=")
            return TermNode(type="tag", value=value, key=key)
        # Could be a key-only match (match all values for this key) or simple tag
        return TermNode(type="tag", value=val)

    # ext:xxx
    if lower.startswith("ext:"):
        return TermNode(type="ext", value=text[4:])

    # size>N
    if lower.startswith("size>"):
        return TermNode(type="size_gt", value=text[5:])

    # size<N
    if lower.startswith("size<"):
        return TermNode(type="size_lt", value=text[5:])

    # after:date
    if lower.startswith("after:"):
        return TermNode(type="after", value=text[6:])

    # before:date
    if lower.startswith("before:"):
        return TermNode(type="before", value=text[7:])

    # Plain text → filename match
    return TermNode(type="name", value=text)


# ---------------------------------------------------------------------------
# Recursive descent parser
# Priority: NOT > AND > OR
# Grammar:
#   expr     = and_expr (OR and_expr)*
#   and_expr = not_expr (AND? not_expr)*
#   not_expr = NOT not_expr | atom
#   atom     = LPAREN expr RPAREN | TERM
# ---------------------------------------------------------------------------

class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> Token | None:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def consume(self) -> Token | None:
        tok = self.peek()
        if tok:
            self.pos += 1
        return tok

    def expect(self, ttype: str) -> Token:
        tok = self.consume()
        if tok is None or tok.type != ttype:
            raise ParseError(f"期望 '{ttype}'，实际 '{tok.type if tok else 'EOF'}'")
        return tok

    def parse(self) -> SearchNode:
        node = self._expr()
        if self.pos < len(self.tokens):
            tok = self.tokens[self.pos]
            raise ParseError(f"无法识别 '{tok.value or tok.type}'")
        return node

    def _expr(self) -> SearchNode:
        """expr = and_expr (OR and_expr)*"""
        left = self._and_expr()
        children = [left]
        while self.peek() and self.peek().type == "OR":
            self.consume()
            children.append(self._and_expr())
        if len(children) == 1:
            return children[0]
        return OrNode(children=children)

    def _and_expr(self) -> SearchNode:
        """and_expr = not_expr (AND? not_expr)*"""
        left = self._not_expr()
        children = [left]
        while True:
            tok = self.peek()
            if tok is None:
                break
            if tok.type == "AND":
                self.consume()
                children.append(self._not_expr())
            elif tok.type in ("TERM", "NOT", "LPAREN"):
                # Implicit AND
                children.append(self._not_expr())
            else:
                break
        if len(children) == 1:
            return children[0]
        return AndNode(children=children)

    def _not_expr(self) -> SearchNode:
        """not_expr = NOT not_expr | atom"""
        if self.peek() and self.peek().type == "NOT":
            self.consume()
            child = self._not_expr()
            # Don't double-wrap NotNode
            return NotNode(child=child)
        return self._atom()

    def _atom(self) -> SearchNode:
        """atom = LPAREN expr RPAREN | TERM"""
        tok = self.peek()
        if tok is None:
            raise ParseError("意外的输入结尾")
        if tok.type == "LPAREN":
            self.consume()
            node = self._expr()
            self.expect("RPAREN")
            return node
        if tok.type == "TERM":
            self.consume()
            return tok.node
        raise ParseError(f"无法识别 '{tok.value or tok.type}'")


class ParseError(Exception):
    pass


# ---------------------------------------------------------------------------
# Public parse function
# ---------------------------------------------------------------------------

def parse_search(text: str) -> SearchQuery:
    """Parse search text into an AST.

    - Pure text without prefixes → single TermNode(type="name")
    - Prefixed terms → full parse with boolean logic
    - Parse failure → parse_ok=False with error message
    """
    text = text.strip()
    if not text:
        return SearchQuery(raw=text, root=None, parse_ok=True)

    # If no prefixes detected, treat entire text as filename search
    if not _has_prefix(text) and not any(
        w.upper() in ("AND", "OR", "NOT") for w in text.split()
    ):
        return SearchQuery(
            raw=text,
            root=TermNode(type="name", value=text),
            parse_ok=True,
        )

    try:
        strict = _has_prefix(text)
        tokens = _tokenize(text, strict=strict)
        if not tokens:
            return SearchQuery(raw=text, root=None, parse_ok=True)

        # Check for unknown terms that look like malformed operators
        # (only when we're in "structured" mode with prefixes)
        parser = _Parser(tokens)
        root = parser.parse()
        return SearchQuery(raw=text, root=root, parse_ok=True)
    except ParseError as e:
        return SearchQuery(raw=text, root=None, parse_ok=False, error=str(e))


# ---------------------------------------------------------------------------
# Search executor
# ---------------------------------------------------------------------------

def _evaluate(node: SearchNode, f: File, file_tags: list[Tag]) -> bool:
    """Evaluate a search AST node against a file and its tags."""
    if isinstance(node, TermNode):
        return _eval_term(node, f, file_tags)
    if isinstance(node, AndNode):
        return all(_evaluate(c, f, file_tags) for c in node.children)
    if isinstance(node, OrNode):
        return any(_evaluate(c, f, file_tags) for c in node.children)
    if isinstance(node, NotNode):
        return not _evaluate(node.child, f, file_tags)
    return False


def _eval_term(node: TermNode, f: File, file_tags: list[Tag]) -> bool:
    """Evaluate a single TermNode."""
    if node.type == "name":
        # Fuzzy filename match (case-insensitive substring)
        return node.value.lower() in f.filename.lower()

    if node.type == "tag":
        if node.key:
            # KV tag: exact key=value match
            return any(
                t.key == node.key and t.value == node.value
                for t in file_tags
            )
        # Could be simple tag (key="") or key-only match
        val = node.value
        # First try exact simple tag match (key="" and value matches)
        if any(t.key == "" and t.value == val for t in file_tags):
            return True
        # Then try key-only match (any tag with this key)
        if any(t.key == val for t in file_tags):
            return True
        return False

    if node.type == "ext":
        val = node.value.lower()
        if val == "folder":
            return f.is_directory
        ext = (f.file_extension or "").lstrip(".").lower()
        return ext == val

    if node.type == "size_gt":
        size = _parse_size(node.value)
        if size is None:
            return False
        return (f.file_size or 0) > size

    if node.type == "size_lt":
        size = _parse_size(node.value)
        if size is None:
            return False
        return (f.file_size or 0) < size

    if node.type == "after":
        dt = _parse_date(node.value)
        if dt is None or f.file_mtime is None:
            return False
        return f.file_mtime >= dt

    if node.type == "before":
        dt = _parse_date(node.value)
        if dt is None or f.file_mtime is None:
            return False
        return f.file_mtime < dt

    return False


def execute_search(db_uri: str, query: SearchQuery) -> tuple[list[File], dict[int, list[Tag]]]:
    """Execute a search query across all libraries.

    Returns (matched_files, {file_id: [Tag, ...]}).
    """
    if query.root is None:
        return [], {}

    # Load all non-missing files
    with session_scope(db_uri) as session:
        all_files = list(
            session.scalars(
                select(File).where(File.is_missing == False)  # noqa: E712
            )
        )
        if not all_files:
            return [], {}

        # Batch load all file_tags
        file_ids = [f.id for f in all_files]
        rows = session.execute(
            select(FileTag.file_id, Tag)
            .join(Tag, FileTag.tag_id == Tag.id)
            .where(FileTag.file_id.in_(file_ids))
        ).all()

    # Build tags dict
    tags_dict: dict[int, list[Tag]] = {fid: [] for fid in file_ids}
    for file_id, tag in rows:
        tags_dict[file_id].append(tag)

    # Evaluate each file
    matched: list[File] = []
    matched_tags: dict[int, list[Tag]] = {}
    for f in all_files:
        ftags = tags_dict.get(f.id, [])
        if _evaluate(query.root, f, ftags):
            matched.append(f)
            matched_tags[f.id] = ftags

    return matched, matched_tags
