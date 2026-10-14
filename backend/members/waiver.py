# The liability waiver and health disclaimer every new member signs
# (SCRUM-83). Served to both signup forms by GET /api/members/waiver, so
# the receptionist's walk-in form and the online signup show exactly the
# same agreement, and each signed Waiver row records WAIVER_VERSION - the
# wording that person actually agreed to.
#
# Bump WAIVER_VERSION whenever the text below changes; existing signatures
# keep the version they were signed under.
#
# Wording from Ali's original waiver PR (#3). Placeholder for this FYP
# demo, not language reviewed by a lawyer.

WAIVER_VERSION = "2026-10"

LIABILITY_WAIVER_TEXT = (
    "I acknowledge that participation in physical exercise, group classes, and use of gym equipment "
    "carries inherent risks of injury, including but not limited to muscle strain, sprains, fractures, "
    "cardiovascular events, and, in rare cases, death. I voluntarily assume all such risks. In "
    "consideration of being permitted to use the facility, I release and forever discharge the gym, its "
    "owners, employees, and agents from any and all claims, demands, or causes of action arising out of "
    "my participation, except in cases of gross negligence or willful misconduct on the part of the gym "
    "or its staff."
)

HEALTH_DISCLAIMER_TEXT = (
    "I confirm that I am in good physical condition and am not aware of any medical reason why I should "
    "not participate in strenuous physical activity. If I have any pre-existing medical condition, I have "
    "consulted a physician before beginning any exercise program at this facility. I understand that gym "
    "staff are not medical professionals and their guidance does not substitute for medical advice. I "
    "agree to inform staff immediately of any pain, discomfort, or medical issue that arises during a "
    "session."
)
