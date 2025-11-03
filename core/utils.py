from django.utils import timezone


def drowsiness_alert_callback(source_key, score):
    # Import aquí para evitar problemas de inicialización al importar módulos Django
    try:
        from .models import Conductor, Vehiculo, CriticalEvent
        # buscar conductor por camera_source
        conductor = Conductor.objects.filter(camera_source=source_key).first()
        vehiculo = None
        if conductor:
            vehiculo = conductor.vehiculos.first()
        # registrar evento
        CriticalEvent.objects.create(
            conductor=conductor,
            vehiculo=vehiculo,
            score=score,
            note=f'Detected by source {source_key}'
        )
    except Exception as e:
        # No levantar errores en el hilo
        print('drowsiness_alert_callback error:', e)
