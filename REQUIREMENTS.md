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
