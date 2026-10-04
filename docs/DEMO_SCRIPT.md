# Demo video script (≤ 5:00)

**Setup before recording:** run `python -m cartographer serve` and open http://localhost:8000 in a maximised browser
at 1440 px or wider, with browser zoom at 110–125%. Use OBS (or the Windows Game Bar, Win+G) at 1080p with a mic.
Close notifications. Keep a terminal ready in the repo folder.

| Time | On screen | Say (roughly) |
|---|---|---|
| **0:00 – 0:25** | Title slide (deck slide 1) | "Hi, we're <team> from <college>. This is CodeCartographer, our entry for Theme 1: Agentic Code Intelligence." |
| **0:25 – 0:55** | Problem slide | "Voice-assistant codebases have dozens of agents and tools spread over thousands of files. A new developer can't hold that in their head, and an LLM can't either, because the repo never fits in a context window. Finding *where* something happens is the slow part." |
| **0:55 – 1:30** | Architecture slide | "We index JavaScript with tree-sitter into a call graph whose call sites are execution-ordered and branch-aware, plus CPU code embeddings. On top of that an agent plans, calls tools, reads only the exact spans it needs, refines, and then **verifies every file and line it cites**. All of it runs on CPU, and it works without any API key." |
| **1:30 – 2:15** | UI → click chip *"Which files call tool checkPermission before tool openDeeplink?"* | "First, the structural query from the brief. Watch the trace on the left: it resolves both tool names, then walks the call graph. Four agents. Note SettingsAgent: the check and the launch live in two helper methods, and we follow them across functions. AccessibilityAgent is *not* listed: it opens the deeplink and *then* checks permission. In CallAgent the dialer and placeCall are in different if/else branches, so we never call them ordered." Scroll to show a code card with highlighted lines and the ✓ verified badge. |
| **2:15 – 2:45** | Click *"Which agents open a deeplink without checking permission first?"* | "Flip it around and it becomes a policy check: these are real gaps, for example NavigationAgent and the Bluetooth quick-settings shortcut." |
| **2:45 – 3:25** | Click *"Where is the Bluetooth-settings deeplink used?"* | "A usage query. It finds the constant, then its direct uses. Then it notices the constant is stored in two lookup tables and follows them, finding TroubleshootAgent and the settings resolver, which never mention the constant by name. That's the agent refining its own search." Point at steps 3 and 4 in the trace and at the call graph. |
| **3:25 – 3:50** | Type *"How does the assistant decide which agent handles an intent?"* | "Plain English. The agent rewrites the question into code vocabulary, runs a hybrid multi-query search, reads the top hits and expands along the call graph: handleUtterance, then AgentRouter.route." |
| **3:50 – 4:10** | Click *"What is slow in smart home device discovery?"* → Optimisations tab | "The bonus: static detectors flag an N+1 sequential await in a loop, with a concrete fix. Here are all twelve findings: sync disk writes on the hot path, a regex compiled per utterance, and others." |
| **4:10 – 4:40** | Evaluation tab | "We measured it. On 41 labelled queries the agent reaches 98% recall at 5 and an MRR of 0.88, against 78% and 0.58 for BM25, with 2.8 times less noise. Structural recall is 100%, and it's the only system that answers the negative query correctly. At 860 files, re-indexing after a change takes under a second, and answers come back in about 50 milliseconds on a CPU." |
| **4:40 – 5:00** | Terminal: `python -m cartographer ask … --code`, then show the MCP command in the README | "It's also a CLI and an MCP server, so Claude Code, Cursor or VS Code can use it directly. Next steps: TypeScript type-aware resolution, and policy checks in CI. Thank you!" |

**Tips:** rehearse once, and keep each query's result on screen for 2–3 seconds. Mouse over the line you're talking about.
If you go over time, cut the 3:25 semantic query first.
