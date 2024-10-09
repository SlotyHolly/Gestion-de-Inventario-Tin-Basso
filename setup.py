import os
from cx_Freeze import setup, Executable

# Establecer la ruta de la carpeta actual para templates y static
current_path = os.path.dirname(os.path.abspath(__file__))

# Definir la ruta del ícono
icon_path = os.path.join(os.path.dirname(__file__), "app_icon.ico")

# Crear opciones para build_exe
build_exe_options = {
    'packages': ['flask'],
    'include_files': [
        (os.path.join(current_path, 'templates'), 'templates'),
        (os.path.join(current_path, 'static'), 'static'),
        'inventario.json',
        'tags.json'
    ]
}

# Definir el ejecutable y agregar el icono
executables = [Executable("app.py",
                          base="Console",         # Usar 'Win32GUI' si es una aplicación GUI (sin consola)
                          target_name="Inventario.exe",  # Nombre del ejecutable
                          icon=icon_path)]        # Ruta del archivo de icono

# Configuración de setup
setup(
    name='FlaskApp',
    version='1.0',
    description='Aplicación Flask de Inventario',
    options={'build_exe': build_exe_options},
    executables=executables
)
