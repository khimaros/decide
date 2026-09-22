# REQUIREMENTS

the product requirements decide is built against. the topic data is the
product, so a row a reader cannot rank or trace is a product defect, not a
data entry problem.

## every topic

- a topic is a static page, publishable anywhere, with every url inside it
  relative
- a reader drags the requirements into their own order and every item is
  rescored and resorted in the browser, so two readers with different
  priorities get different answers from one file
- a score a reader cannot trace to a source is a guess wearing a number, so
  every scored evaluation cites where it came from
- a requirement an item has not been scored against stays `-inf` and reads as
  a gap rather than as a zero
- a requirement graded by a rule hands that rule to the reader: a **rubric**
  travels with the requirement and opens on the page, so that a 0.7 meaning
  "almost" and a 0.7 meaning "only on the vendor's cloud" never read the same
- `make check` gates the build on both rules, so a topic that breaks one never
  ships

## ai-harness topic

- the harnesses listed are ones a developer is plausibly choosing between now,
  each scored against its own documentation, README or shipped build rather
  than against an aggregator's summary
- **Mobile UI** tracks whether a harness can be driven from a phone: an app the
  project ships, or a web ui laid out for a small screen. running the terminal
  in a phone terminal emulator scores nothing here, because that is still the
  terminal, and a mobile app that drives a different product of the same
  vendor counts only as the adapter it is

## ade topic

an ADE is the surface a developer drives coding agents from, so its item is
the control surface and its backend is a harness. the harnesses themselves are
compared in the ai-harness topic and are only scored here as backends.

- an ADE is judged on reaching the work, not on doing it: **Web UI**, **iOS
  App**, **Android App**, **Desktop App** and **Desktop: Linux** each track a
  surface the project ships itself, and driving one ADE from another vendor's
  app counts only as the adapter it is
- a conversation has two ends, so speech is scored twice: **Voice: Dictation**
  for spoken input, **Voice: Speech** for read-aloud output, and **Voice:
  Conversation** for a hands-free mode that holds a turn taking dialogue
- **Git Worktrees** and **Parallel Agents** are separate rows, because fanning
  one prompt across isolated trees and running several agents in one checkout
  are different claims
- **Sandboxing** scores isolation *of the harness by the ADE*: a container, a
  VM, a seatbelt or a jail the agent runs inside. permission prompts and
  allow-lists are the harness's own, so they score nothing here
- **Browser Control** scores the ADE steering a browser on the agent's behalf,
  which is where an embedded preview, a click-to-prompt design mode or a
  computer-use tool all count
- the backend rows name the harnesses a reader can pick today: Claude Code,
  Codex, OpenCode, Pi, Cursor, **Harness: ACP** for anything speaking the agent
  client protocol, and **Harness: Any CLI** for a terminal escape hatch
- **Community Run** scores whether the project survives on its community: an
  outside pull request that merged, or a documented route for one, beats a
  README that says contributions are not being accepted
- **Telemetry** and **Vendor Cloud Required** are anti-requirements: a hosted
  relay that can be switched off and replaced by a direct connection scores as
  the option it is, not as the dependency
