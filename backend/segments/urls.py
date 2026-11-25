from django.urls import path

from . import trends, uptake, views

urlpatterns = [
    path("", views.segment_list),
    path("/meta", views.meta),
    path("/preview", views.preview),
    path("/clusters", views.clusters),
    path("/clusters/run", views.clusters_run),
    path("/clusters/<int:group_id>/save", views.cluster_save),
    path("/trends", trends.trends),
    path("/uptake", uptake.uptake),
    path("/<int:segment_id>", views.segment_detail),
]
