# Diagrams

The architecture and data-flow diagrams are embedded as fenced Mermaid blocks in the
top-level [README.md](../../README.md). GitHub renders them natively.

SVG exports (for non-GitHub viewers) can be generated with the Mermaid CLI:

```bash
npm install -g @mermaid-js/mermaid-cli
mmdc -i README.md -o docs/diagrams/architecture.svg    # extract architecture block
mmdc -i README.md -o docs/diagrams/data-flow.svg       # extract data-flow block
```

`mmdc` was not available in the Phase 6A build environment, so SVG exports are deferred.
The fenced blocks in the README are the authoritative source.
