from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        # registrar callback para eventos críticos de somnolencia
        try:
            from . import drowsiness
            from . import utils
            drowsiness.register_callback(utils.drowsiness_alert_callback)
        except Exception as e:
            print('Error registering drowsiness callback:', e)
