# Copy/paste prompt for Claude

You are reviewing a retail options research platform called Christiania.

Act as a hostile quantitative reviewer. Your job is to find ways the system can
fool itself into believing it has an edge.

Read `docs/CLAUDE_REVIEW_PAUSE_POINT_2026-08-29.md` and
`research/edge_discovery/EDGE_DISCOVERY_PROTOCOL_V1.md`.

Do not praise the architecture unless a claim survives attack.

Focus on identification, economic realism, multiplicity, data provenance,
selection bias, dependence, cost modeling, and harvestability.

Classify every issue as BLOCKER / MAJOR / MINOR / ACCEPTABLE.

For BLOCKER and MAJOR issues, give the smallest concrete fix.

At the end answer these five questions:

1. Is the current empirical ThetaData work scientifically usable as descriptive
   evidence?
2. Is the current edge-discovery governance strong enough to start building a
   scanner?
3. What is the single most dangerous remaining self-deception risk?
4. What must be done before the first real defined-risk trade?
5. What work should Christiania explicitly NOT do yet?

The correct answer may be INSUFFICIENT EVIDENCE.
