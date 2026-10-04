"""Code-aware tokenisation shared by BM25, symbol search and the planner."""

from __future__ import annotations

import re

_IDENT = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*|\d+")
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")

STOPWORDS = {
    "the", "a", "an", "is", "are", "of", "to", "in", "on", "for", "and", "or", "it", "this", "that",
    "where", "which", "what", "how", "does", "do", "done", "find", "show", "me", "code", "file", "files",
    "function", "functions", "used", "use", "uses", "using", "called", "call", "calls", "get", "any",
    "there", "be", "with", "from", "by", "we", "i", "you", "can", "all", "its", "when", "happens",
    "happen", "logic", "implemented", "implementation", "handled", "handle", "handles", "our", "my",
    "const", "let", "var", "return", "await", "async", "new", "require", "module", "exports",
}

# Light domain synonyms so natural language reaches identifier vocabulary.
SYNONYMS = {
    "deeplink": ["deeplink", "intent", "uri", "launch"],
    "deeplinks": ["deeplink", "intent", "uri"],
    "bt": ["bluetooth"],
    "pair": ["pair", "connect", "bluetooth"],
    "permission": ["permission", "granted", "request"],
    "permissions": ["permission", "granted"],
    "speak": ["speak", "tts", "speech"],
    "speech": ["speech", "asr", "tts", "transcript"],
    "voice": ["asr", "tts", "speech"],
    "intent": ["intent", "classify", "classifier"],
    "remind": ["reminder", "remind"],
    "music": ["media", "music", "track", "play"],
    "song": ["media", "track"],
    "slow": ["latency", "await", "sync"],
    "retry": ["retry", "backoff", "attempts"],
    "cache": ["cache", "ttl", "cached"],
    "log": ["logger", "log"],
    "store": ["save", "persist", "store"],
    "persist": ["save", "persist", "write"],
    "location": ["location", "position", "gps", "lat"],
    "route": ["route", "router", "agent"],
    "routing": ["route", "router", "agent"],
    "wifi": ["wifi", "network"],
    "screen": ["display", "screen", "brightness"],
    "decide": ["route", "select", "dispatch"],
    "decides": ["route", "select", "dispatch"],
    "choose": ["route", "select", "pick"],
    "picks": ["route", "select", "pick"],
    "dispatch": ["route", "dispatch"],
    "handler": ["route", "handler", "agent"],
    "startup": ["bootstrap", "start", "init"],
    "boot": ["bootstrap", "start"],
    "understand": ["classify", "intent", "nlu"],
    "classify": ["classify", "intent"],
    "follow": ["clarification", "slot"],
    "missing": ["missing", "required", "clarification"],
}


def rewrite_query(text: str) -> str:
    """Deterministic code-vocabulary rewrite: keep content words, add domain synonyms."""
    return " ".join(dict.fromkeys(query_tokens(text, expand=True)))


def split_identifier(word: str) -> list[str]:
    parts = []
    for piece in re.split(r"[_$\-.]+", word):
        parts.extend(p.lower() for p in _CAMEL.findall(piece))
    return parts


def code_tokens(text: str) -> list[str]:
    """Identifier-aware tokens: full identifier + its camel/snake parts, lowercased."""
    out: list[str] = []
    for m in _IDENT.findall(text):
        low = m.lower()
        parts = split_identifier(m)
        out.append(low)
        if len(parts) > 1:
            out.extend(parts)
    return out


def query_tokens(text: str, expand: bool = True) -> list[str]:
    toks = [t for t in code_tokens(text) if t not in STOPWORDS and len(t) > 1]
    if expand:
        extra = []
        for t in toks:
            extra.extend(SYNONYMS.get(t, []))
        toks = toks + [e for e in extra if e not in toks]
    return toks
