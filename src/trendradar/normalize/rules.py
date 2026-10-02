"""Zero-cost pain lexicon. Stage 1 of the cost pyramid: only signals that read like a problem
statement reach the (paid) classifier. Scores are 0..1 and explainable (matched patterns)."""

from __future__ import annotations

import re

PAIN_PATTERNS: list[tuple[str, float, str]] = [
    (
        r"\bis there (a|any|an)( \w+)? (tool|app|way|service|extension|plugin|script|product)\b",
        0.35,
        "asks for a tool",
    ),
    (
        r"\b(any|some) (tool|app|way|service) (to|that|for)\b|\banyone (know|have|use) (a|an|any)\b",
        0.25,
        "asks for a tool",
    ),
    (r"\bwish (there was|there were|someone would|i could|it (could|would))\b", 0.30, "wish"),
    (
        r"\bwhy (is there no|isn't there|doesn't|does no|is (this|it) still|are (these|they) still)\b",
        0.30,
        "why is there no",
    ),
    (r"\balternative(s)? to\b|\breplace(ment)? for\b", 0.25, "seeks alternative"),
    (
        r"\bi hate\b|\bdrives me (crazy|nuts|insane)\b|\bthe worst part\b|\bkilling my\b|\bgoing insane\b|\bchaos\b",
        0.30,
        "frustration",
    ),
    (r"\bevery (time|day|week|month|morning|evening|friday|sunday|night)\b", 0.15, "recurring"),
    (
        r"\b(manually|by hand|re-?typ(e|ing)|re-?enter|copy(ing)? (and paste|entries|hours|from)|paste (screenshots|it|them))\b",
        0.30,
        "manual work",
    ),
    (
        r"\b(too|so|very|really|way too|far too) (expensive|complicated|complex|slow|hard|clunky|bloated|much|big|heavy|fiddly)\b|\boverkill\b|\bbloated\b|\bduct tape\b|\bhacky\b|\bfragile\b",
        0.30,
        "cost/complexity complaint",
    ),
    (
        r"\b(would|happily|gladly|'d) pay\b|\bwin my money\b|\btake my money\b|\bpay (for|per) (seat|month|it)\b|\$\d+ ?(/|a |per )?(mo|month)|\bpriced (for|accordingly)\b|\bpricing\b|\bcosts? more than\b",
        0.25,
        "pricing / willingness to pay",
    ),
    (
        r"\bi (wrote|built|made|hacked together|ended up (writing|building|keeping|with))( a| my own)?( \w+){0,2} (script|tool|wrapper|flow|automation|bot|page|spreadsheet|checklist)\b|\btook (me )?a weekend\b",
        0.35,
        "self-built workaround",
    ),
    (
        r"\bworkaround\b|\bspreadsheet\b|\bzapier\b|\bnotion page\b|\bwhiteboard\b|\bword template\b|\bgoogle doc\b",
        0.20,
        "workaround",
    ),
    (
        r"\b(missing|lacks?|doesn't have|no way to|can't|cannot|impossible to|not possible to)\b",
        0.20,
        "missing capability",
    ),
    (r"\b(gave up|abandoned|stopped using|switched away|never got working)\b", 0.25, "churned from tool"),
    (
        r"\b(time sink|eats an hour|hours? (a|per|every) (day|week|month)|takes me (a full|all|longer|forever)|full day|(lost|burn) \d+ (minutes|hours)|\d+ hours? (a|per) week)\b",
        0.30,
        "time cost",
    ),
    (
        r"\bfeature request\b|\bwould be great if\b|\bplease add\b|\bwould (remove|cover|be enough)\b|\bwould save me\b",
        0.25,
        "feature request",
    ),
    (
        r"\b(lost|losing|lose|keep losing)( \w+){0,2} (work|context|track|data|hours|time|state|sessions?|plan)\b",
        0.30,
        "loss",
    ),
    (
        r"\b(everything|every tool|all the tools|the tools that exist|the (options|apps|tools) i (found|tried))\b.*\b(either|assume|built for|too|expensive|complicated|enterprise|agenc)",
        0.30,
        "existing tools don't fit",
    ),
    (
        r"\bhuge gap\b|\bbig gap\b|\bthere should be\b|\bstate of the art for\b|\bstill the state\b",
        0.25,
        "gap statement",
    ),
    (
        r"\b(forget|forgetting) to\b|\bchas(e|ing) (payment|people|clients|invoices)\b|\bno-?shows?\b|\bnag(s|ging)?\b",
        0.20,
        "follow-up pain",
    ),
    (
        r"\binstead of (me|us) (remembering|doing|having to|clicking)\b|\brequires? (configuring|a webhook|three apps|a paid plan)\b|\bnon-?technical\b",
        0.25,
        "complexity for non-technical",
    ),
]

_COMPILED = [(re.compile(p, re.I | re.S), w, label) for p, w, label in PAIN_PATTERNS]

NOISE_PATTERNS = [
    re.compile(r"\b(released?|release notes|changelog|version \d)", re.I),
    re.compile(r"\b(ama|ask me anything|self-?promotion thread|weekly thread|megathread)\b", re.I),
    re.compile(r"\btypo\b", re.I),
]


def rule_score(title: str, content: str) -> tuple[float, list[str]]:
    text = f"{title}\n{content}"
    score = 0.0
    matched: list[str] = []
    for pattern, weight, label in _COMPILED:
        if pattern.search(text):
            score += weight
            if label not in matched:
                matched.append(label)
    if any(p.search(title) for p in NOISE_PATTERNS) and score < 0.5:
        score *= 0.3
        matched.append("noise-penalty")
    if len(content) < 80:
        score *= 0.6
    return min(1.0, round(score, 3)), matched
