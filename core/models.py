from django.contrib.auth.models import AbstractUser
from django.db import models
from django.core.validators import RegexValidator
import uuid

class Usuario(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ROLES = [
        ('admin', 'Administrador'),
        ('conductor', 'Conductor'),
    ]
    rol = models.CharField(max_length=20, choices=ROLES, default='conductor')

    def __str__(self):
        return f"{self.username} ({self.rol})"


class Conductor(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    usuario = models.OneToOneField('core.Usuario', on_delete=models.CASCADE, related_name='perfil_conductor')
    nombres = models.CharField(max_length=100, verbose_name='Nombres', null=True, blank=True)
    apellidos = models.CharField(max_length=100, verbose_name='Apellidos', null=True, blank=True)
    # Fuente opcional de cámara: índice (0,1...) o URL (rtsp://... http://...)
    camera_source = models.CharField(max_length=200, null=True, blank=True, verbose_name='Fuente de cámara', help_text='Índice de cámara (0) o URL RTSP/HTTP')
    documento = models.CharField(
        max_length=50,
        unique=True,
        validators=[RegexValidator(r'^\d+$', message='El número de documento debe contener sólo dígitos.')]
    )

    # Licencia: usar un conjunto de categorías predefinidas
    LICENCIA_CHOICES = [
        ('A1', 'A1'), ('A2', 'A2'),
        ('B1', 'B1'), ('B2', 'B2'), ('B3', 'B3'),
        ('C1', 'C1'), ('C2', 'C2'), ('C3', 'C3'),
    ]
    licencia = models.CharField(max_length=2, choices=LICENCIA_CHOICES)
    licencia_vencimiento = models.DateField(null=True, blank=True, verbose_name='Vencimiento de licencia')

    telefono = models.CharField(
        max_length=20,
        verbose_name='Teléfono de contacto',
        null=True,
        blank=True,
        validators=[RegexValidator(r'^\d+$', message='El teléfono debe contener sólo dígitos.')]
    )
    estado_fatiga = models.FloatField(default=0.0)
    autenticado = models.BooleanField(default=False)

    def nombre_completo(self):
        return f"{self.nombres} {self.apellidos}"

    def __str__(self):
        return f"{self.nombre_completo()} - {self.documento}"

    def __str__(self):
        return f"{self.usuario.username} - {self.documento}"

class Vehiculo(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    placa = models.CharField(
        max_length=6,
        unique=True,
        validators=[RegexValidator(r'^[A-Za-z]{3}\d{3}$', message='La placa debe tener el formato AAA111 (3 letras y 3 dígitos).')]
    )
    marca = models.CharField(max_length=50)
    modelo = models.IntegerField()
    color = models.CharField(max_length=30)
    tipo_carroceria = models.CharField(max_length=50)
    SERVICIO_CHOICES = [
        ('particular', 'Particular'),
        ('publico', 'Público'),
    ]
    servicio = models.CharField(max_length=20, choices=SERVICIO_CHOICES)
    conductor_asignado = models.ForeignKey(
        Conductor, on_delete=models.SET_NULL, null=True, blank=True, related_name='vehiculos'
    )

    def __str__(self):
        return f"{self.placa} ({self.marca})"


class CriticalEvent(models.Model):
    """Registro de eventos críticos detectados por el sistema de somnolencia."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conductor = models.ForeignKey(Conductor, on_delete=models.SET_NULL, null=True, blank=True, related_name='critical_events')
    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.SET_NULL, null=True, blank=True, related_name='critical_events')
    timestamp = models.DateTimeField(auto_now_add=True)
    score = models.IntegerField()
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"CriticalEvent {self.id} - {self.score} @ {self.timestamp}"
