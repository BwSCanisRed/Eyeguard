from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Usuario, MobileTelemetrySnapshot

@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Rol', {'fields': ('rol',)}),
    )
    list_display = ('username', 'email', 'rol', 'is_staff', 'is_superuser')


@admin.register(MobileTelemetrySnapshot)
class MobileTelemetrySnapshotAdmin(admin.ModelAdmin):
    list_display = (
        'documento',
        'nombre_conductor',
        'placa',
        'fatigue_index',
        'estado',
        'face_detected',
        'last_seen_at',
    )
    search_fields = ('documento', 'nombre_conductor', 'placa')
    list_filter = ('estado', 'face_detected', 'source')
