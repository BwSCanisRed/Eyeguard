from django.urls import path
from . import views
from django.conf.urls.i18n import i18n_patterns

urlpatterns = [
    path('i18n/setlang/', views.set_language, name='set_language'),
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
    path('password-reset/', views.password_reset, name='password_reset'),
    path('conductor/send_frame/', views.conductor_send_frame, name='conductor_send_frame'),
    path('conductor/stop_stream/', views.conductor_stop_stream, name='conductor_stop_stream'),
    path('api/conductores_activos/', views.conductores_activos, name='conductores_activos'),
]
    