from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse


def health(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health", health),
    path("api/members", include("members.urls")),
    path("api/plans", include("plans.urls")),
    path("api", include("administration.urls")),
]
