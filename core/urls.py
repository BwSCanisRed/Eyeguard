from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('login/', views.login_view, name='login'),
    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('conductor-dashboard/', views.conductor_dashboard, name='conductor_dashboard'),
    path('monitor-conductores/', views.monitor_conductores, name='monitor_conductores'),
    path('edit-conductor/<uuid:conductor_id>/', views.edit_conductor, name='edit_conductor'),
    path('stream/<uuid:conductor_id>/', views.stream_mjpeg, name='stream_mjpeg'),
    path('stream-score/<uuid:conductor_id>/', views.stream_score, name='stream_score'),
    path('delete-conductor/<uuid:conductor_id>/', views.delete_conductor, name='delete_conductor'),
    path('export-critical-events/', views.export_critical_events, name='export_critical_events'),
    path('logout/', views.logout_view, name='logout'),
]
    