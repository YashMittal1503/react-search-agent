"""Citation guard.

The writer cites source ids like ``[S7]``. While tokens stream, this rewrites them to reader-facing
numbers ``[1]``, ``[2]``... in order of first use, drops ids that don't exist in the run's registry
(hallucinated citations), and strips raw URLs the model may have typed. Every number in the final
answer therefore maps to a URL a tool actually returned: invalid citations are impossible by construction.
"""

from __future__ import annotations

import re

from .context import SourceRegistry

_GROUP = re.compile(r"\[(\s*S?\d+\s*(?:[,;]\s*S?\d+\s*)*)\]", re.IGNORECASE)
_ID = re.compile(r"S?(\d+)", re.IGNORECASE)
_RAW_URL = re.compile(r"(?<![\(\[<`])https?://[^\s)\]>`]+")


class CitationStreamer:
    def __init__(self, registry: SourceRegistry):
        self.registry = registry
        self.numbers: dict[int, int] = {}     # source id -> display number
        self.invalid: list[str] = []
        self._buf = ""

    def _replace(self, m: re.Match) -> str:
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
        text = _GROUP.sub(self._replace, text)
        return _RAW_URL.sub("", text)

    def feed(self, token: str) -> str:
        """Return text that is safe to emit now; hold back a possible partial ``[S..`` marker."""
        self._buf += token
        cut = self._buf.rfind("[")
        if cut != -1 and "]" not in self._buf[cut:] and len(self._buf) - cut < 24:
            ready, self._buf = self._buf[:cut], self._buf[cut:]
        else:
            ready, self._buf = self._buf, ""
        # also hold back a trailing partial URL so it can be stripped as a whole
        m = re.search(r"https?://\S*$", ready)
        if m and not self._buf:
            self._buf, ready = ready[m.start():], ready[: m.start()]
        return self._rewrite(ready)

    def flush(self) -> str:
        rest, self._buf = self._buf, ""
        return self._rewrite(rest)

    def cited_sources(self) -> list[dict]:
        out = []
        for sid, n in sorted(self.numbers.items(), key=lambda kv: kv[1]):
            src = self.registry.get(sid)
            if src:
                out.append({"n": n, **src.public()})
        return out


def rewrite_all(text: str, registry: SourceRegistry) -> tuple[str, CitationStreamer]:
    cs = CitationStreamer(registry)
    return cs.feed(text) + cs.flush(), cs
