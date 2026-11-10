# Every tunable number behind the at-risk list (SCRUM-118/119/120) lives
# here, so the scoring can be adjusted in one place instead of hunting
# through the code.

# ---------------------------------------------------------------------------
# Rule-based score (always available)
# ---------------------------------------------------------------------------
#
# Each feature is turned into a 0-1 "signal" (features.signals), then
# multiplied by its weight. The weights add up to 100, so the score is
# 0-100 and each weighted term is that feature's share of the score - the
# largest terms are the reasons shown to staff (SCRUM-119).
RULE_WEIGHTS = {
    # Visits in the last 4 weeks vs the member's previous 8 weeks (per week).
    "attendance_drop": 25,
    # Days since the member last checked in.
    "inactivity": 20,
    # Booked classes / PT sessions they didn't turn up to (last 30 days).
    "no_shows": 12,
    # Subscription lapsed and not renewed, or renewals paid late.
    "payment": 15,
    # A freeze running now, or one in the last 6 months.
    "freeze": 10,
    # In their first 90 days (new members leave most often).
    "new_member": 8,
    # Membership ends within 30 days.
    "renewal_soon": 10,
}

# Windows for the attendance features.
RECENT_WEEKS = 4
PRIOR_WEEKS = 8
# Inactivity signal: 0 at or below this many days since the last visit...
INACTIVE_FROM_DAYS = 7
# ...rising to 1 at this many.
INACTIVE_FULL_DAYS = 35
# No-shows counted over this many days; this many reach the full signal.
NO_SHOW_WINDOW_DAYS = 30
NO_SHOWS_FULL = 3
# A renewal paid more than this many days after the previous expiry is late.
LATE_PAYMENT_GRACE_DAYS = 3
# Late payments and past freezes are looked for over this many days.
HISTORY_WINDOW_DAYS = 180
# "New member" covers the first NEW_MEMBER_DAYS of membership.
NEW_MEMBER_DAYS = 90
# Membership ending within this many days counts as "renewal soon".
RENEWAL_WINDOW_DAYS = 30

# A feature has to add at least this many points to the score to be given
# as a reason.
MIN_REASON_POINTS = 3
MAX_REASONS = 3

# ---------------------------------------------------------------------------
# Learned model (used per branch once there is enough history)
# ---------------------------------------------------------------------------
#
# Label: the member cancelled within LABEL_DAYS after a cutoff date.
LABEL_DAYS = 30
# Training cutoffs are taken every CUTOFF_STEP_DAYS, starting once there
# are PRIOR_WEEKS + RECENT_WEEKS of history to compute features from.
CUTOFF_STEP_DAYS = 14
# Below either of these, a branch falls back to the rule-based score.
MIN_CANCELLATIONS = 30
MIN_MEMBERS = 200
# The newest share of cutoffs is held out to validate the model; if it
# can't beat this AUC on them, the branch falls back to the rules too.
HOLDOUT_SHARE = 0.25
MIN_VALIDATION_AUC = 0.6
# Logistic regression training (plain gradient descent, standardized inputs).
TRAIN_EPOCHS = 600
LEARNING_RATE = 0.5
L2_PENALTY = 0.01

# ---------------------------------------------------------------------------
# Risk levels shown in the list
# ---------------------------------------------------------------------------
#
# Score thresholds per method. A rule score is a weighted sum of signals; a
# model score is 100 x the predicted chance of cancelling within 30 days,
# so its bands are lower: with a typical monthly cancellation rate around
# 5%, a 10% chance is already twice the norm.
LEVELS = {
    "rules": {"High": 55, "Medium": 30},
    "model": {"High": 30, "Medium": 10},
}

# How often the background thread checks whether this week's list exists.
SCHEDULER_INTERVAL_SECONDS = 3600

# ---------------------------------------------------------------------------
# Weekly call capacity and accuracy (SCRUM-120)
# ---------------------------------------------------------------------------

# Calls a branch's staff can make per week, until a manager sets their own.
DEFAULT_CALL_CAPACITY = 20
MAX_CALL_CAPACITY = 500
# The accuracy panel needs at least this many finished weeks (30 days have
# passed since the list was made) and this many listed members across them
# before it shows a number instead of "Not enough data yet".
ACCURACY_MIN_WEEKS = 2
ACCURACY_MIN_LISTED = 10
