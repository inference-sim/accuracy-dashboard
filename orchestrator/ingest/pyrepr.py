"""Read the Python reprs vLLM prints in its server log into plain values.

vLLM logs its `non-default args` as a Python dict repr and its resolved engine config as
`key=value` pairs. Both mix literals with object reprs:

    {'max_num_seqs': 16, 'kernel_config': KernelConfig(moe_backend='auto', ...),
     'compilation_config': {'mode': <CompilationMode.VLLM_COMPILE: 3>, ...}}

`parse` turns one such repr into JSON-like values: dicts, lists, str, int, float, bool, None.
An object repr `Name(a=1, b=2)` becomes {"a": 1, "b": 2}; an enum member `<Enum.MEMBER: v>`
becomes "MEMBER". Floats keep the text the log printed (`Float`), so a value is never
re-rounded on its way into the fidelity record. Anything else raises ReprError: an
unreadable value must be reported, not guessed.
"""
from __future__ import annotations

import re


class ReprError(ValueError):
    pass


class Float(str):
    """A float as the log printed it. Compares as text; `float(x)` gives the number."""


class Opaque(str):
    """A bare token that isn't a literal (e.g. `torch.bfloat16`, `cuda`), kept as text."""


_NUM = re.compile(r"-?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")


class _Reader:
    def __init__(self, text: str):
        self.s = text
        self.i = 0

    def error(self, msg: str):
        return ReprError(f"{msg} at offset {self.i}: {self.s[self.i:self.i + 40]!r}")

    def ws(self):
        while self.i < len(self.s) and self.s[self.i] in " \t\r\n":
            self.i += 1

    def peek(self) -> str:
        self.ws()
        return self.s[self.i] if self.i < len(self.s) else ""

    def expect(self, ch: str):
        if self.peek() != ch:
            raise self.error(f"expected {ch!r}")
        self.i += 1

    def value(self):
        c = self.peek()
        if not c:
            raise self.error("unexpected end of input")
        if c == "{":
            return self.mapping()
        if c == "[":
            return self.sequence("[", "]")
        if c == "(":
            return self.sequence("(", ")")
        if c in "'\"":
            return self.string()
        if c == "<":
            return self.enum()
        m = _NUM.match(self.s, self.i)
        if m and not (self.s[m.end():m.end() + 1].isalpha() or self.s[m.end():m.end() + 1] == "_"):
            self.i = m.end()
            text = m.group(0)
            if re.fullmatch(r"-?\d+", text):
                return int(text)
            return Float(text)
        m = _IDENT.match(self.s, self.i)
        if m:
            self.i = m.end()
            word = m.group(0)
            if word in ("True", "False"):
                return word == "True"
            if word == "None":
                return None
            if word in ("inf", "nan"):
                return Float(word)
            if self.peek() == "(":
                return self.call()
            return Opaque(word)
        raise self.error("unreadable value")

    def string(self) -> str:
        q = self.s[self.i]
        self.i += 1
        out = []
        while self.i < len(self.s):
            ch = self.s[self.i]
            if ch == "\\":
                nxt = self.s[self.i + 1:self.i + 2]
                out.append({"n": "\n", "t": "\t", "\\": "\\", "'": "'", '"': '"'}.get(nxt, "\\" + nxt))
                self.i += 2
                continue
            if ch == q:
                self.i += 1
                return "".join(out)
            out.append(ch)
            self.i += 1
        raise self.error("unterminated string")

    def enum(self) -> str:
        # <Enum.MEMBER: value> -> "MEMBER"
        m = re.compile(r"<([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)(?::[^<>]*)?>").match(self.s, self.i)
        if not m:
            raise self.error("unreadable enum")
        self.i = m.end()
        return m.group(2)

    def mapping(self) -> dict:
        self.expect("{")
        out = {}
        while True:
            if self.peek() == "}":
                self.i += 1
                return out
            key = self.value()
            if isinstance(key, (dict, list)):
                raise self.error("unhashable key")
            self.expect(":")
            out[str(key)] = self.value()
            if self.peek() == ",":
                self.i += 1

    def sequence(self, open_: str, close: str) -> list:
        self.expect(open_)
        out = []
        while True:
            if self.peek() == close:
                self.i += 1
                return out
            out.append(self.value())
            if self.peek() == ",":
                self.i += 1

    def call(self) -> dict:
        # Name(a=1, b=x) -> {"a": 1, "b": x}. Positional arguments have no name to keep.
        self.expect("(")
        out = {}
        while True:
            if self.peek() == ")":
                self.i += 1
                return out
            m = _IDENT.match(self.s, self.i)
            if not m or self.s[m.end():m.end() + 1] != "=":
                raise self.error("positional argument in an object repr")
            self.i = m.end() + 1
            out[m.group(0)] = self.value()
            if self.peek() == ",":
                self.i += 1


def parse(text: str):
    """One repr, whole. Trailing text is an error."""
    r = _Reader(text)
    v = r.value()
    if r.peek():
        raise r.error("trailing text")
    return v


def parse_prefix(text: str):
    """One repr at the start of text; returns (value, characters consumed)."""
    r = _Reader(text)
    v = r.value()
    return v, r.i


def parse_kwargs(text: str) -> dict:
    """`a=1, b='x', c=Obj(d=2)` (vLLM's resolved engine-config line) -> dict.

    Values run to the next top-level `, name=`; a value that isn't a readable repr is kept as
    Opaque text, since the config line prints some fields as bare words (`device_config=cuda`).
    """
    out = {}
    i, n = 0, len(text)
    while i < n:
        while i < n and text[i] in " ,":
            i += 1
        m = _IDENT.match(text, i)
        if not m or text[m.end():m.end() + 1] != "=":
            raise ReprError(f"expected name= at offset {i}: {text[i:i + 40]!r}")
        key = m.group(0)
        i = m.end() + 1
        try:
            value, used = parse_prefix(text[i:])
            j = i + used
            while j < n and text[j] == " ":
                j += 1
            if j < n and text[j] != ",":
                raise ReprError("not a whole value")
            out[key] = value
            i = j
        except ReprError:
            # A bare value: up to the next ", name=" at depth 0.
            depth, j = 0, i
            while j < n:
                ch = text[j]
                if ch in "([{<":
                    depth += 1
                elif ch in ")]}>":
                    depth -= 1
                elif ch == "," and depth == 0 and re.match(r",\s*[A-Za-z_][A-Za-z0-9_]*=", text[j:]):
                    break
                j += 1
            out[key] = Opaque(text[i:j].strip())
            i = j
    return out
