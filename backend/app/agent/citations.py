"""Citation guard.

The writer cites source ids like ``[S7]``. While tokens stream, this rewrites them to reader-facing
numbers ``[1]``, ``[2]``... in order of first use, drops ids that don't exist in the run's registry
(hallucinated citations), and strips raw URLs the model may have typed. Every number in the final
answer therefore maps to a URL a tool actually returned: invalid citations are impossible by construction.
"""

from __future__ import annotations

import re

from .context import SourceRegistry

# A bracket group of one or more ids: "[S3]", "[S3, S7]", "[3; 5]" (models sometimes drop the S).
# gpt-oss models add a line-range suffix ("S3†L5-L9"); it is allowed and ignored.
_ID_PART = r"\s*S?\d+(?:†[^\],;]*)?\s*"
_GROUP = re.compile(rf"\[({_ID_PART}(?:[,;]{_ID_PART})*)\]", re.IGNORECASE)
# The same group in parentheses, "(S3)" / "(S3, S7)". The S is required here so "(2024)" stays prose.
_PAREN_GROUP = re.compile(r"\((\s*S\d+\s*(?:[,;]\s*S\d+\s*)*)\)", re.IGNORECASE)
# gpt-oss writes citations with full-width lenticular brackets: 【S11】. Mapped to [S11] as tokens arrive.
_FULLWIDTH = str.maketrans({"【": "[", "】": "]"})
_ID = re.compile(r"S?(\d+)", re.IGNORECASE)
# A bare URL typed into prose (not inside a markdown link/code). Removed: links come only from citation chips.
_RAW_URL = re.compile(r"(?<![\(\[<`])https?://[^\s)\]>`]+")


class CitationStreamer:
    """Rewrites ``[S#]`` citations in a token stream. Feed tokens in, emit what it returns.

    Attributes:
        numbers: source id -> display number, assigned in order of first citation.
        invalid: raw ids the model cited that don't exist (reported to the UI and evals).
    """

    def __init__(self, registry: SourceRegistry):
        self.registry = registry
        self.numbers: dict[int, int] = {}     # source id -> display number
        self.invalid: list[str] = []
        self._buf = ""                        # text held back until we know whether it is a complete marker

    def _replace(self, m: re.Match) -> str:
        """Regex callback: turn one bracket group into ``[1][2]`` chips, dropping unknown and duplicate ids."""
        out = []
        for raw in re.split(r"[,;]", m.group(1)):
            mm = _ID.search(raw)
            if not mm:
                continue
            sid = int(mm.group(1))
            if self.registry.get(sid) is None:
                self.invalid.append(raw.strip())
                continue
            if sid not in self.numbers:
                self.numbers[sid] = len(self.numbers) + 1
            n = f"[{self.numbers[sid]}]"
            if n not in out:
                out.append(n)
        return "".join(out)

    def _rewrite(self, text: str) -> str:
        """Rewrite all complete citation groups in ``text`` and strip raw URLs."""
        text = _PAREN_GROUP.sub(lambda m: f"[{m.group(1)}]", text)
        text = _GROUP.sub(self._replace, text)
        return _RAW_URL.sub("", text)

    def feed(self, token: str) -> str:
        """Return text that is safe to emit now; hold back a possible partial ``[S..`` marker.

        Tokens can split a marker anywhere ("[S" + "12]"), so an unclosed ``[`` near the end is kept in the buffer
        until its ``]`` arrives. 24 chars is longer than any realistic marker group, so ordinary brackets are not
        held back for long.
        """
        self._buf += token.translate(_FULLWIDTH)
        cut = self._buf.rfind("[")
        paren = self._buf.rfind("(")
        # A trailing "(" or "(S.." may be the start of "(S3)": hold it back too (but not "(2024", which is prose).
        if paren > cut and (paren == len(self._buf) - 1 or self._buf[paren + 1] in "Ss"):
            cut = paren
        closer = "]" if self._buf[cut:cut + 1] == "[" else ")"
        if cut != -1 and closer not in self._buf[cut:] and len(self._buf) - cut < 24:
            ready, self._buf = self._buf[:cut], self._buf[cut:]
        else:
            ready, self._buf = self._buf, ""
        # also hold back a trailing partial URL so it can be stripped as a whole
        m = re.search(r"https?://\S*$", ready)
        if m and not self._buf:
            self._buf, ready = ready[m.start():], ready[: m.start()]
        return self._rewrite(ready)

    def flush(self) -> str:
        """End of stream: rewrite and return whatever is still buffered."""
        rest, self._buf = self._buf, ""
        return self._rewrite(rest)

    def cited_sources(self) -> list[dict]:
        """The sources actually cited, in display order, each with its number ``n`` (for the UI's source list)."""
        out = []
        for sid, n in sorted(self.numbers.items(), key=lambda kv: kv[1]):
            src = self.registry.get(sid)
            if src:
                out.append({"n": n, **src.public()})
        return out


def rewrite_all(text: str, registry: SourceRegistry) -> tuple[str, CitationStreamer]:
    """Non-streaming helper: rewrite a whole text at once (used by tests)."""
    cs = CitationStreamer(registry)
    return cs.feed(text) + cs.flush(), cs
