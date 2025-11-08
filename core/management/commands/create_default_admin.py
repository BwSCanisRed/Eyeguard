import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = "Create a default superadmin using env vars ADMIN_USERNAME/ADMIN_PASSWORD."

    def handle(self, *args, **options):
        User = get_user_model()

        username = os.getenv("ADMIN_USERNAME")
        password = os.getenv("ADMIN_PASSWORD")
        email = os.getenv("ADMIN_EMAIL", "admin@example.com")
        force_update = os.getenv("ADMIN_FORCE_UPDATE", "False") == "True"

        if not username or not password:
            self.stdout.write(
                self.style.WARNING(
                    "ADMIN_USERNAME or ADMIN_PASSWORD not set. Skipping default admin creation."
                )
            )
            return

        user, created = User.objects.get_or_create(
            username=username,
            defaults={"email": email, "rol": "admin"},
        )

        changed = False
        if created:
            user.is_staff = True
            user.is_superuser = True
            user.rol = "admin"
            user.set_password(password)
            user.save()
            self.stdout.write(self.style.SUCCESS(f"Superadmin '{username}' created."))
            return

        # Ensure flags/role
        if not user.is_staff:
            user.is_staff = True
            changed = True
        if not user.is_superuser:
            user.is_superuser = True
            changed = True
        if getattr(user, "rol", None) != "admin":
            try:
                user.rol = "admin"
                changed = True
            except Exception:
                pass

        if force_update:
            user.set_password(password)
            changed = True

        if changed:
            user.save()
            self.stdout.write(self.style.SUCCESS(f"Superadmin '{username}' updated."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Superadmin '{username}' already exists and is up to date."))
