"""Promo rules and ranking weights, in one place so they are easy to review and tune."""

MIN_DURATION = 20.0
MAX_DURATION = 60.0
HOOK_WINDOW = 3.0
CLIFF_TOLERANCE = 1.0
DEDUPE_IOU = 0.5
# A window longer than MAX_DURATION is condensed to the opening after the hook plus the run-up to the cliffhanger.
CONDENSE_HEAD = 20.0
CONDENSE_TAIL = 25.0

JUDGE_WEIGHTS = {"hook": 0.30, "cliff": 0.25, "standalone": 0.25, "emotion": 0.20}
SCORE_KEYS = tuple(JUDGE_WEIGHTS)
SWEET_SPOT = (30.0, 45.0)
SWEET_SPOT_BONUS = 0.3
SPOILER_PENALTY = 0.6
# Maximum penalty, applied to a promo whose earliest moment is in the final episode.
FUNNEL_PENALTY = 0.4
DIVERSITY_WINDOW = 0.25

# Assumed paid-tier list prices (USD per 1M tokens) for a Flash-class model; used only for cost estimates.
PRICE_PER_M_INPUT = 0.30
PRICE_PER_M_OUTPUT = 2.50
