from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
import os
import json
from PIL import Image  # Importar la biblioteca Pillow para manipulación de imágenes
from werkzeug.utils import secure_filename
import socket
import sys 

# Función para mostrar las rutas actuales en consola
def print_debug_paths():
    print("===== Información de Rutas =====")
    print(f"Ruta actual de trabajo: {os.getcwd()}")
    print(f"Ruta del archivo actual (__file__): {os.path.abspath(__file__)}")
    print(f"Ruta del directorio base (base_dir): {base_dir}")
    print(f"Ruta de templates: {app.template_folder}")
    print(f"Ruta de static: {app.static_folder}")
    print("================================")

# Definir la ruta base del directorio
base_dir = os.path.abspath(os.path.dirname(__file__))

# Cuando se empaqueta con cx_Freeze, el archivo __file__ apunta a library.zip
# Usamos esta lógica para identificar si estamos dentro de library.zip y ajustar la ruta base
if getattr(sys, 'frozen', False):  # Detecta si está ejecutándose como ejecutable empaquetado
    base_dir = os.path.dirname(sys.executable)  # Ruta del ejecutable actual

# Crear la aplicación Flask
app = Flask(__name__,
            template_folder=os.path.join(base_dir, 'templates'),  # Ruta completa de templates
            static_folder=os.path.join(base_dir, 'static'))       # Ruta completa de static
app.secret_key = 'supersecretkey'
app.config['UPLOAD_FOLDER'] = 'static/uploads/'  # Carpeta para guardar las imágenes
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}

tags_file = 'tags.json'

# Función para eliminar la imagen del sistema de archivos
def delete_image(image_path):
    if image_path:
        # Obtener la ruta completa del archivo basada en la ubicación del script actual
        full_image_path = os.path.abspath(os.path.join(app.config['UPLOAD_FOLDER'], os.path.basename(image_path)))
        print(f"Ruta completa de la imagen a eliminar: {full_image_path}")

        # Verificar si el archivo existe en la ruta absoluta
        if os.path.exists(full_image_path):
            try:
                os.remove(full_image_path)  # Eliminar la imagen usando la ruta absoluta
                print(f"Imagen eliminada exitosamente: {full_image_path}")
            except Exception as e:
                print(f"Error al eliminar la imagen: {e}")
        else:
            print(f"La imagen no existe en la ruta especificada: {full_image_path}")
    else:
        print("No se proporcionó una ruta de imagen válida para eliminar.")

# Asegurarse de que la carpeta de subida exista
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# Función para verificar si la extensión del archivo está permitida
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

# Función para generar un nombre de archivo basado en el nombre del producto
def generate_filename(nombre_producto, extension):
    nombre_seguro = secure_filename(nombre_producto).replace(" ", "_").lower()
    return f"{nombre_seguro}.{extension}"

# Función para cargar el inventario
def load_inventory():
    if os.path.exists('inventario.json'):
        with open('inventario.json', 'r') as file:
            return json.load(file)
    return []

# Función para guardar el inventario
def save_inventory(inventario):
    # Reemplazar las barras invertidas con barras normales para las rutas de imagen
    for producto in inventario:
        if 'imagen' in producto and producto['imagen']:
            # Convertir la ruta de Windows a una con barras normales
            producto['imagen'] = producto['imagen'].replace("\\", "/")
    with open('inventario.json', 'w') as file:
        json.dump(inventario, file, indent=4)

# Función para cargar los tags desde un archivo JSON
def load_tags():
    if os.path.exists(tags_file):
        with open(tags_file, 'r') as f:
            return json.load(f)
    return []

# Función para guardar los tags en un archivo JSON
def save_tags(tags):
    with open(tags_file, 'w') as f:
        json.dump(tags, f, indent=4)

# Función para recortar una imagen a 1:1 (cuadrada)
def crop_image_to_square(image_path):
    with Image.open(image_path) as img:
        width, height = img.size
        # Calcular el tamaño mínimo para hacer la imagen cuadrada
        new_size = min(width, height)
        
        # Coordenadas para centrar el recorte
        left = (width - new_size) / 2
        top = (height - new_size) / 2
        right = (width + new_size) / 2
        bottom = (height + new_size) / 2

        # Recortar la imagen
        img_cropped = img.crop((left, top, right, bottom))

        # Guardar la imagen recortada en el mismo path
        img_cropped.save(image_path)

@app.route('/')
def index():
    inventario = load_inventory()
    tags = load_tags()
    filtro_tags = request.args.getlist('tag')
    search_query = request.args.get('search', '').lower()

    # Filtrar por tags si hay seleccionados
    if filtro_tags:
        inventario = [p for p in inventario if any(tag in p.get('tags', []) for tag in filtro_tags)]
    
    # Filtrar por nombre de producto si hay búsqueda
    if search_query:
        inventario = [p for p in inventario if search_query in p['nombre'].lower()]
    print("Intentando cargar index.html desde la ruta de templates...")
    return render_template('index.html', inventario=inventario, tags=tags, selected_tags=filtro_tags)

# Ruta para agregar un nuevo tag
@app.route('/add_tag', methods=['POST'])
def add_tag():
    tags = load_tags()
    new_tag = request.form.get('tag')
    if new_tag and new_tag not in tags:
        tags.append(new_tag)
        save_tags(tags)
        flash('Tag agregado exitosamente.', 'success')
    else:
        flash('El tag ya existe o está vacío.', 'danger')
    return redirect(url_for('manage_tags'))

# Ruta para eliminar un tag
@app.route('/delete_tag/<tag>', methods=['POST'])
def delete_tag(tag):
    tags = load_tags()
    tags = [t for t in tags if t != tag]  # Filtrar el tag
    save_tags(tags)  # Guardar tags actualizados
    # También debemos eliminar el tag de cualquier producto que lo tenga asignado
    inventario = load_inventory()
    for producto in inventario:
        if tag in producto.get('tags', []):
            producto['tags'].remove(tag)
    save_inventory(inventario)  # Guardar inventario actualizado
    return redirect(url_for('manage_tags'))

@app.route('/add', methods=['GET', 'POST'])
def add_product():
    tags = load_tags()
    if request.method == 'POST':
        inventario = load_inventory()
        new_id = max([p['id'] for p in inventario], default=0) + 1
        nombre = request.form['nombre']
        cantidad = int(request.form['cantidad'])
        precio = float(request.form['precio'])
        producto_tags = request.form.getlist('tags')

        # Manejar la carga de la imagen
        file = request.files['foto'] if 'foto' in request.files else None
        imagen = None
        if file and allowed_file(file.filename):
            # Generar un nombre de archivo basado en el nombre del producto y la extensión del archivo
            extension = file.filename.rsplit('.', 1)[1].lower()
            filename = generate_filename(nombre, extension)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            
            # Guardar el archivo original
            file.save(filepath)

            # Recortar la imagen a una proporción 1:1
            crop_image_to_square(filepath)

            # Guardar solo la ruta relativa de la imagen
            imagen = os.path.join('/static/uploads', filename)

        # Crear el nuevo producto con la ruta de la imagen relativa
        inventario.append({'id': new_id, 'nombre': nombre, 'cantidad': cantidad, 'precio': precio, 'tags': producto_tags, 'imagen': imagen})
        save_inventory(inventario)
        return redirect(url_for('index'))
    return render_template('add_product.html', tags=tags)

@app.route('/edit/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    inventario = load_inventory()
    producto = next((p for p in inventario if p['id'] == product_id), None)
    tags = load_tags()
    if request.method == 'POST':
        if producto:
            producto['nombre'] = request.form['nombre']
            producto['cantidad'] = int(request.form['cantidad'])
            producto['precio'] = float(request.form['precio'])
            producto['tags'] = request.form.getlist('tags')

            # Manejar la carga de la imagen
            file = request.files['foto'] if 'foto' in request.files else None
            if file and allowed_file(file.filename):
                extension = file.filename.rsplit('.', 1)[1].lower()
                filename = generate_filename(producto['nombre'], extension)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                
                # Guardar el archivo original
                file.save(filepath)

                # Recortar la imagen a una proporción 1:1
                crop_image_to_square(filepath)

                # Actualizar la ruta de la imagen en el producto
                producto['imagen'] = os.path.join('/static/uploads', filename)

            save_inventory(inventario)
        return redirect(url_for('index'))
    return render_template('edit_product.html', producto=producto, tags=tags)

# Ruta para manejar la eliminación de productos
@app.route('/delete/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    inventario = load_inventory()
    # Buscar el producto a eliminar
    producto_a_eliminar = next((p for p in inventario if p['id'] == product_id), None)

    # Si se encuentra el producto, eliminar la imagen asociada
    if producto_a_eliminar and 'imagen' in producto_a_eliminar:
        print(f"Eliminando la imagen asociada al producto: {producto_a_eliminar['imagen']}")
        delete_image(producto_a_eliminar['imagen'])  # Pasar la ruta de la imagen a delete_image

    # Eliminar el producto del inventario
    inventario = [p for p in inventario if p['id'] != product_id]
    save_inventory(inventario)
    flash('Producto eliminado exitosamente.', 'success')
    return redirect(url_for('index'))

@app.route('/manage_tags', methods=['GET', 'POST'])
def manage_tags():
    # Cargar los tags desde el archivo JSON
    tags = load_tags()

    if request.method == 'POST':
        new_tag = request.form['tag']
        if new_tag and new_tag not in tags:
            tags.append(new_tag)
            save_tags(tags)
            flash('Tag agregado exitosamente.', 'success')
        else:
            flash('El tag ya existe o está vacío.', 'danger')
        return redirect(url_for('manage_tags'))

    return render_template('manage_tags.html', tags=tags)

@app.route('/search')
def search():
    query = request.args.get('query', '').lower()  # Obtener la búsqueda y convertir a minúsculas
    inventario = load_inventory()
    
    # Filtrar los productos según la búsqueda en el nombre
    productos_filtrados = [p for p in inventario if query in p['nombre'].lower()]

    # Devolver los productos filtrados como JSON
    return jsonify(productos_filtrados)

if __name__ == '__main__':
    # Obtener la IP local del dispositivo
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    #Limpiar consola
    os.system('cls' if os.name == 'nt' else 'clear')
    # Imprimir la IP local para acceder a la aplicación
    print(f"Accede a la aplicacion en: http://{local_ip}:5000")
    # Mostrar las rutas al iniciar la aplicación
    print_debug_paths()
    #Abre el navegador con la IP local
    os.system(f"start http://{local_ip}:80")
    # Levantar Flask en la IP local para que sea accesible en la red
    app.run(host='0.0.0.0', port=80, debug=True)
