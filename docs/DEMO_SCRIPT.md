# Demo video script: 3 speakers, ≤ 5:00

**Roles**
- **Adarsh Gupta (M1):** intro, problem, architecture. Slides only.
- **Aryan Sandilya (M2):** live demo of the core queries. Drives the web UI.
- **Ujjwal Pratap Singh (M3):** semantic and bonus features, results, wrap-up. Drives the UI and then the terminal.

**Setup before recording**
- Run `python -m cartographer serve` and open http://localhost:8000.
- Maximise the browser and set zoom to 110–125%.
- Have the deck open in a second window and a terminal ready in the repo folder.
- Record with OBS (or Win+G) at 1080p.
- Easiest workflow: each person records their part, then you join the clips in any editor (Clipchamp is built into Windows). Or record on one screen share and pass control at the handovers.

---

## M1 · Adarsh · Intro, problem, architecture (0:00 – 1:30)

**[Slide 1: title] 0:00 – 0:20**
> "Hi, we're team **SpaceX** from **SRM**: I'm **Adarsh Gupta**, with **Aryan Sandilya** and **Ujjwal Pratap Singh**. This is **CodeCartographer**, our solution for Theme 1, Agentic Code Intelligence."

**[Slide 2: problem] 0:20 – 0:50**
> "Voice-assistant codebases have dozens of agents and tools spread across thousands of files. A new developer can't hold all of that in their head, and neither can an LLM. Even at 860 files, our test repo is about 237 thousand tokens, far beyond any context window. Keyword search can't answer structural questions like 'which files call tool A before tool B', and plain LLMs guess file paths and line numbers. Finding *where* something happens is the slow part of every fix."

**[Slide 3: four query types] 0:50 – 1:05**
> "CodeCartographer answers four kinds of questions: semantic, usage, structural, and callers with optimisation tips. Every answer comes back as exact file and line numbers."

**[Slide 4: architecture] 1:05 – 1:30**
> "First we index the JavaScript with tree-sitter. That gives a call graph where every call is stored in execution order and knows which if/else branch it's in, plus CPU code embeddings and keyword search. On top sits an agent: it plans, calls tools, reads only the exact lines it needs, refines its search, and then **verifies every file and line it cites** against the source. It all runs on CPU and works without any API key. Over to Aryan for the live demo."

---

## M2 · Aryan · Live demo, the core queries (1:30 – 3:25)

**[UI, Ask tab → click the chip "Which files call tool checkPermission before tool openDeeplink?"] 1:30 – 2:15**
> "Thanks, Adarsh. Let's start with the structural query straight from the problem statement. On the left you can watch the agent's trace live: it resolves both tool names and then walks the call graph. Four agents match.
> Look at SettingsAgent: the permission check and the deeplink launch are in two separate helper methods, and we follow the calls across functions to find it.
> AccessibilityAgent is **not** listed, because it opens the deeplink *first* and checks permission *after*. That's a real bug.
> And in CallAgent, the dialer and placeCall are in different branches of an if/else, so we never report them as ordered."

*(Scroll to one code card. Point at the yellow highlighted lines and the ✓ verified badge.)*

**[Click "Which agents open a deeplink without checking permission first?"] 2:15 – 2:40**
> "Now flip the question and it becomes a security policy check. These are the places where a deeplink opens with no permission check before it: NavigationAgent, AccessibilityAgent, and the Bluetooth quick-settings shortcut."

**[Click "Where is the Bluetooth-settings deeplink used?"] 2:40 – 3:25**
> "Now a usage query. The agent finds the constant BLUETOOTH_SETTINGS, then its two direct uses. Then, in steps 3 and 4, it notices the constant is also stored inside two lookup tables and follows them. That finds TroubleshootAgent and the settings resolver, which never mention the constant by name. Keyword search and embeddings both miss those. This is the agent refining its own search, and you can see the whole path in the call graph. Ujjwal, over to you."

*(Hover over steps 3–4 in the trace, then over the graph.)*

---

## M3 · Ujjwal · Semantic, bonus, results, wrap-up (3:25 – 5:00)

**[Type "How does the assistant decide which agent handles an intent?"] 3:25 – 3:50**
> "Thanks, Aryan. Questions can be plain English too. The agent rewrites the question into code vocabulary, runs keyword and embedding search together, reads the top hits and expands along the call graph. It lands on handleUtterance and AgentRouter.route, which is exactly the routing logic."

**[Click "What is slow in smart home device discovery?" → then the Optimisations tab] 3:50 – 4:10**
> "And the bonus: optimisation suggestions. It flags an N+1 pattern, one network request per room awaited one after another, and suggests Promise.all. The Optimisations tab lists all twelve findings: blocking disk writes on every turn, a regex rebuilt for every utterance, and more."

**[Evaluation tab] 4:10 – 4:40**
> "We measured everything on 42 hand-labelled queries. For 98% of questions the agent has a correct answer in its top five, compared with 78% for keyword search. Its ranking score, MRR, is 0.88 versus 0.58, and it returns 2.8 times less noise. Structural questions are 100% correct, and it's the only system that correctly answers 'none' when nothing matches. At 860 files, re-indexing after a change takes under a second, and answers come back in about 50 milliseconds, on CPU."

**[Terminal: run the command below, then show the MCP line in the README] 4:40 – 5:00**
```
python -m cartographer ask sample_repo/nova-assistant "who calls withRetry" --code
```
> "It also works from the command line, and as an MCP server, so Claude Code, Cursor or VS Code can use it directly. Next steps are type-aware resolution through the TypeScript compiler and running these policy checks in CI. Thank you!"

---

**Tips**
- Rehearse once with a timer. If you run long, cut M3's semantic query (3:25–3:50) first.
- Keep each result on screen for 2–3 seconds before talking over the next click.
- Each speaker should say the next person's name at the handover. It makes the cut feel natural.
