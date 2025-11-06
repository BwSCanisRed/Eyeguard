from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.validators import RegexValidator
from .models import Usuario, Conductor, Vehiculo

# Reutilizables
NAME_REGEX = RegexValidator(r'^[A-Za-zÁÉÍÓÚáéíóúÑñ ]+$', message='Sólo letras y espacios son permitidos en nombres/apellidos.')
DIGITS_ONLY = RegexValidator(r'^\d+$', message='Este campo acepta sólo dígitos.')
# Aceptar formato común de placas: 3 letras + 3 dígitos (ej. LZP666).
PLACA_REGEX = RegexValidator(r'^[A-Za-z]{3}\d{3}$', message='La placa debe tener el formato AAA111 (3 letras y 3 dígitos).')

class ConductorForm(forms.ModelForm):
    username = forms.CharField(
        label='Nombre de usuario',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ingrese el nombre de usuario'})
    )
    password = forms.CharField(
        label='Contraseña',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Ingrese la contraseña'})
    )
    email = forms.EmailField(
        label='Correo electrónico',
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Ingrese el correo electrónico'})
    )
    licencia = forms.ChoiceField(
        label='Categoría de licencia',
        choices=Conductor.LICENCIA_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    licencia_vencimiento = forms.DateField(
        label='Vencimiento de licencia',
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )

    class Meta:
        model = Conductor
        fields = ['nombres', 'apellidos', 'documento', 'licencia', 'licencia_vencimiento', 'telefono']
        widgets = {
            'nombres': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ingrese los nombres'}),
            'apellidos': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ingrese los apellidos'}),
            'documento': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ingrese el número de documento'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ingrese el número de teléfono', 'type': 'tel'})
        }

    def save(self, commit=True):
        # Primero creamos el usuario
        password = self.cleaned_data.get('password')
        if not password:
            raise forms.ValidationError('La contraseña es requerida para crear el usuario.')

        # Crear el usuario y asegurar que la contraseña quede encriptada
        user = Usuario(
            username=self.cleaned_data['username'],
            email=self.cleaned_data.get('email', ''),
            rol='conductor'
        )
        user.set_password(password)
        if commit:
            user.save()

        # Luego creamos el perfil del conductor
        conductor = super().save(commit=False)
        conductor.usuario = user
        if commit:
            conductor.save()
        return conductor

    def clean_password(self):
        pwd = self.cleaned_data.get('password')
        if not pwd:
            raise forms.ValidationError('La contraseña es requerida.')
        if len(pwd) < 6:
            raise forms.ValidationError('La contraseña debe tener al menos 6 caracteres.')
        return pwd

    # Validaciones específicas de formulario
    def clean_nombres(self):
        nombre = self.cleaned_data.get('nombres', '')
        if nombre:
            NAME_REGEX(nombre)
        return nombre

    def clean_apellidos(self):
        apellido = self.cleaned_data.get('apellidos', '')
        if apellido:
            NAME_REGEX(apellido)
        return apellido

    def clean_documento(self):
        doc = self.cleaned_data.get('documento', '')
        if not doc:
            raise forms.ValidationError('El documento es requerido.')
        DIGITS_ONLY(doc)
        return doc

    def clean_telefono(self):
        tel = self.cleaned_data.get('telefono', '')
        if tel:
            DIGITS_ONLY(tel)
        return tel

class VehiculoForm(forms.ModelForm):
    placa = forms.CharField(
        label='Placa',
        validators=[PLACA_REGEX],
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: WWW125', 'maxlength': 6})
    )
    servicio = forms.ChoiceField(
        label='Tipo de servicio',
        choices=Vehiculo.SERVICIO_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    class Meta:
        model = Vehiculo
        fields = ['placa', 'marca', 'modelo', 'color', 'tipo_carroceria', 'servicio']
        widgets = {
            'modelo': forms.NumberInput(attrs={'min': 1900, 'max': 2030, 'class': 'form-control'}),
            'marca': forms.TextInput(attrs={'class': 'form-control'}),
            'color': forms.TextInput(attrs={'class': 'form-control'}),
            'tipo_carroceria': forms.TextInput(attrs={'class': 'form-control'})
        }

    def clean_placa(self):
        placa = self.cleaned_data.get('placa', '')
        PLACA_REGEX(placa)
        return placa

class EditConductorForm(forms.ModelForm):
    email = forms.EmailField(
        label='Correo electrónico',
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Ingrese el correo electrónico'})
    )
    licencia = forms.ChoiceField(
        label='Categoría de licencia',
        choices=Conductor.LICENCIA_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    licencia_vencimiento = forms.DateField(
        label='Vencimiento de licencia',
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    
    class Meta:
        model = Conductor
        fields = ['nombres', 'apellidos', 'documento', 'licencia', 'licencia_vencimiento', 'telefono']
        widgets = {
            'nombres': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ingrese los nombres'}),
            'apellidos': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ingrese los apellidos'}),
            'documento': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ingrese el número de documento'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ingrese el número de teléfono', 'type': 'tel'})
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.usuario:
            self.fields['email'].initial = self.instance.usuario.email
    
    def save(self, commit=True):
        conductor = super().save(commit=False)
        if commit:
            conductor.save()
            conductor.usuario.email = self.cleaned_data['email']
            conductor.usuario.save()
        return conductor

    def clean_nombres(self):
        nombre = self.cleaned_data.get('nombres', '')
        if nombre:
            NAME_REGEX(nombre)
        return nombre

    def clean_apellidos(self):
        apellido = self.cleaned_data.get('apellidos', '')
        if apellido:
            NAME_REGEX(apellido)
        return apellido

    def clean_documento(self):
        doc = self.cleaned_data.get('documento', '')
        if not doc:
            raise forms.ValidationError('El documento es requerido.')
        DIGITS_ONLY(doc)
        return doc

    def clean_telefono(self):
        tel = self.cleaned_data.get('telefono', '')
        if tel:
            DIGITS_ONLY(tel)
        return tel