from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from administration.models import StaffAccount
from classes.models import ClassBooking, PTSession
from members.models import Member

# User story (SCRUM-40): "As a member, I want to rate and leave feedback for
# my coach after a session, so that I can help improve service quality."
#
# One rating per session the member actually attended: a group class booking
# or a private training session, never both. The coach, branch, session name
# and time are copied in when it's written, so the rating still reads right
# if the class is renamed later. The member can change it while the rating
# window is open (feedback/views.py), and a data deletion request keeps the
# stars but erases the comment (members/privacy.py).


class CoachFeedback(models.Model):
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="coach_feedback")
    coach = models.ForeignKey(StaffAccount, on_delete=models.PROTECT, related_name="feedback_received")
    class_booking = models.OneToOneField(
        ClassBooking, on_delete=models.CASCADE, null=True, blank=True, related_name="feedback",
    )
    pt_session = models.OneToOneField(
        PTSession, on_delete=models.CASCADE, null=True, blank=True, related_name="feedback",
    )
    branch = models.CharField(max_length=30, choices=Member.Branch.choices)
    session_name = models.CharField(max_length=120)
    session_starts_at = models.DateTimeField()
    session_ends_at = models.DateTimeField()
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(rating__gte=1, rating__lte=5), name="coach_feedback_rating_1_to_5"),
            models.CheckConstraint(
                condition=(Q(class_booking__isnull=False, pt_session__isnull=True)
                           | Q(class_booking__isnull=True, pt_session__isnull=False)),
                name="coach_feedback_one_session",
            ),
        ]

    def __str__(self):
        return f"{self.member} rated {self.coach.full_name} {self.rating}/5 for {self.session_name}"

    @property
    def kind(self):
        return "class" if self.class_booking_id else "pt"

    @property
    def session_id(self):
        return self.class_booking.gym_class_id if self.class_booking_id else self.pt_session_id
