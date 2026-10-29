from django.contrib import admin

from .models import ClassBooking, ClassType, GymClass, PTAvailability, PTSession


@admin.register(PTAvailability)
class PTAvailabilityAdmin(admin.ModelAdmin):
    list_display = ("coach", "branch", "weekday", "start_time", "end_time", "session_minutes")
    list_filter = ("branch", "weekday")


@admin.register(PTSession)
class PTSessionAdmin(admin.ModelAdmin):
    list_display = ("coach", "member", "branch", "starts_at", "status", "attendance")
    list_filter = ("branch", "status")
    search_fields = ("coach__full_name", "member__name")


@admin.register(ClassType)
class ClassTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "branch", "max_capacity", "default_duration_minutes", "is_active")
    list_filter = ("branch", "is_active")
    search_fields = ("name",)


class ClassBookingInline(admin.TabularInline):
    model = ClassBooking
    extra = 0
    fields = ("member", "status", "booked_at", "cancel_reason", "attendance")
    readonly_fields = ("booked_at",)


@admin.register(GymClass)
class GymClassAdmin(admin.ModelAdmin):
    list_display = ("name", "class_type", "branch", "starts_at", "ends_at", "coach", "room", "capacity", "status")
    list_filter = ("branch", "status")
    search_fields = ("name", "coach__full_name", "room")
    inlines = [ClassBookingInline]
