from django.urls import path

from . import views

app_name = "monitors"

urlpatterns = [
    path("monitors/", views.monitor_list, name="list"),
    path("monitors/new/", views.monitor_create, name="create"),
    path("monitors/<int:pk>/", views.monitor_detail, name="detail"),
    path("monitors/<int:pk>/edit/", views.monitor_edit, name="edit"),
    path("monitors/<int:pk>/delete/", views.monitor_delete, name="delete"),
    path("monitors/<int:pk>/results/", views.monitor_results_partial, name="results_partial"),
    path("monitors/<int:pk>/data.json", views.monitor_data, name="data"),
    path("upgrade/", views.upgrade, name="upgrade"),
    path("s/<slug:slug>/", views.public_status, name="public_status"),
    path("s/<slug:slug>/data.json", views.public_status_data, name="public_status_data"),
]
