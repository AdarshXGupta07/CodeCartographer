"""Core behaviour tests. Run: python -m pytest -q   (uses the hashing embedder for speed)."""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CARTO_EMBED_MODEL", "hashing")
os.environ.setdefault("CARTO_INDEX_HOME", str(ROOT / ".cartographer-test"))

from cartographer.agent import Agent  # noqa: E402
from cartographer.graph import GraphQueries  # noqa: E402
from cartographer.indexer import CodeIndex  # noqa: E402
from cartographer.llm import LLM  # noqa: E402
from cartographer.parser import parse_file  # noqa: E402
from cartographer.tools import classify  # noqa: E402

REPO = ROOT / "sample_repo" / "nova-assistant"


@pytest.fixture(scope="module")
def ix():
    index = CodeIndex(REPO)
    index.build(force=True)
    return index


@pytest.fixture(scope="module")
def agent(ix):
    return Agent(ix, LLM(provider="none"))


def test_parser_extracts_ordered_tool_calls_and_guards():
    src = (REPO / "src/agents/callAgent.js").read_bytes()
    _, funcs, _ = parse_file("src/agents/callAgent.js", src)
    run = next(f for f in funcs.values() if f.name == "CallAgent.run")
    tools = [c.tool for c in run.calls if c.tool]
    assert tools == ["checkPermission", "lookupContact", "openDeeplink", "placeCall"]
    open_dl = next(c for c in run.calls if c.tool == "openDeeplink")
    place = next(c for c in run.calls if c.tool == "placeCall")
    # same if-statement, different arms
    assert open_dl.guard[-1][0] == place.guard[-1][0] and open_dl.guard[-1][1] != place.guard[-1][1]


def test_tool_handlers_registered(ix):
    assert {"checkPermission", "openDeeplink", "toggleBluetooth", "fetchWeather"} <= set(ix.tool_handlers)


def test_call_order_is_interprocedural_and_branch_aware(ix):
    g = GraphQueries(ix)
    res = g.call_order("checkPermission", "openDeeplink")
    assert res["files"] == ["src/agents/bluetoothAgent.js", "src/agents/callAgent.js",
                            "src/agents/settingsAgent.js", "src/agents/troubleshootAgent.js"]
    # accessibilityAgent opens the deeplink BEFORE checking permission -> must not match
    assert "src/agents/accessibilityAgent.js" not in res["files"]
    # placeCall / openDeeplink live in exclusive if/else arms -> no ordering
    assert g.call_order("placeCall", "openDeeplink")["matches"] == []


def test_negated_order(ix):
    res = GraphQueries(ix).call_order("checkPermission", "openDeeplink", negate=True)
    names = {m["function"] for m in res["matches"]}
    assert {"AccessibilityAgent.run", "NavigationAgent.run", "SettingsAgent.openBluetoothSettings"} <= names


def test_term_resolution(ix):
    g = GraphQueries(ix)
    assert g.resolve_term("permission check")["name"] == "checkPermission"
    assert g.resolve_term("deeplink")["name"] == "openDeeplink"


@pytest.mark.parametrize("q,kind", [
    ("Which files call tool XYZ before tool ABC?", "structural"),
    ("which agents open a deeplink without checking permission first", "structural"),
    ("who calls getUserLocation", "callers"),
    ("Where is the Bluetooth-settings deeplink used?", "usage"),
    ("what is slow in device discovery", "optimize"),
    ("how are sessions saved", "semantic"),
])
def test_classifier(q, kind):
    assert classify(q)["type"] == kind


def test_usage_query_follows_alias_tables(agent):
    fin = agent.ask("Where is the Bluetooth-settings deeplink used?", use_llm=False)
    syms = {l["symbol"] for l in fin["locations"]}
    assert "BluetoothAgent.run" in syms
    assert "TroubleshootAgent.run" in syms        # via PROBLEM_TO_SETTINGS
    assert "SettingsAgent.detectPage" in syms     # via SETTINGS_ALIASES
    assert all(l["verified"] for l in fin["locations"])


def test_verifier_rejects_hallucinated_locations(agent):
    out = agent._verify([
        {"file": "src/agents/settingsAgent.js", "start": 40, "end": 40, "evidence": ["openDeeplink"]},
        {"file": "src/does/not/exist.js", "start": 1, "end": 2, "evidence": []},
        {"file": "src/agents/settingsAgent.js", "start": 9999, "end": 10000, "evidence": []},
        {"file": "src/agents/settingsAgent.js", "start": 1, "end": 3, "evidence": ["placeCall"]},
    ])
    assert [l["verified"] for l in out] == [True, False, False, False]


def test_optimizer_findings(ix):
    rules = {(f["file"], f["rule"]) for f in ix.findings}
    assert ("src/agents/smartHomeAgent.js", "await-in-loop") in rules
    assert ("src/core/sessionStore.js", "json-deep-clone") in rules
    # retry loops are sequential by design and must not be flagged
    assert ("src/utils/retry.js", "await-in-loop") not in rules


def test_incremental_reindex(ix):
    meta = ix.build()
    assert meta["stats"]["files_parsed"] == 0
    assert meta["stats"]["chunks_embedded"] == 0
