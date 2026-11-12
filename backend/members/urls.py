from django.urls import path

from billing import views as billing_views
from classes import views as class_views
from feedback import views as feedback_views
from headcount import busy as headcount_busy
from healthnotes import views as health_views
from notifications import views as notification_views
from progress import views as progress_views

from . import auth_views, privacy, views

urlpatterns = [
    path("/meta", views.member_meta),
    path("/waiver", views.waiver_text),
    path("/signup", auth_views.signup),
    path("/login", auth_views.login),
    path("/logout", auth_views.logout),
    path("/me", auth_views.me),
    path("/me/qr", auth_views.my_qr),
    path("/me/export", privacy.my_data_export),
    path("/me/delete", privacy.my_data_delete),
    path("/me/payment-method", billing_views.my_payment_method),
    path("/me/billing", billing_views.my_billing),
    path("/me/freeze", views.my_freeze),
    path("/me/resume", views.my_resume),
    path("/me/cancel", views.my_cancel),
    path("/me/busy", headcount_busy.my_branch_busy),
    path("/me/workouts", progress_views.my_workouts),
    path("/me/workouts/<int:entry_id>", progress_views.my_workout_detail),
    path("/me/metrics", progress_views.my_metrics),
    path("/me/metrics/<int:metric_id>", progress_views.my_metric_detail),
    path("/me/feedback", feedback_views.my_feedback),
    path("/me/feedback/<int:feedback_id>", feedback_views.my_feedback_detail),
    path("/me/health", health_views.my_health),
    path("/me/health/confirm", health_views.my_health_confirm),
    path("/me/health/<int:note_id>", health_views.my_health_note),
    path("/me/classes", class_views.my_classes),
    path("/me/classes/<int:class_id>/book", class_views.book_class),
    path("/me/classes/<int:class_id>/cancel", class_views.cancel_booking),
    path("/me/classes/<int:class_id>/waitlist", class_views.join_waitlist),
    path("/me/classes/<int:class_id>/waitlist/leave", class_views.leave_waitlist),
    path("/me/notifications", notification_views.my_member_notifications),
    path("/me/notifications/read-all", notification_views.member_read_all),
    path("/me/notifications/<int:notification_id>/read", notification_views.member_read_one),
    path("/me/reminders", notification_views.my_reminders),
    path("/me/coaches", class_views.my_coaches),
    path("/me/pt-slots", class_views.my_pt_slots),
    path("/me/pt-sessions", class_views.book_pt),
    path("/me/pt-sessions/<int:session_id>/cancel", class_views.cancel_my_pt),
    path("/<int:member_id>/billing", billing_views.member_billing),
    path("/<int:member_id>/payment-method", billing_views.member_payment_method),
    path("/<int:member_id>/renewal-quote", billing_views.member_renewal_quote),
    path("/<int:member_id>/payments", billing_views.member_payment),
    path("/<int:member_id>/cancel", views.member_cancel),
    path("/<int:member_id>/access-card", views.member_access_card),
    path("/<int:member_id>", views.member_detail),
    path("", views.member_list),
]
