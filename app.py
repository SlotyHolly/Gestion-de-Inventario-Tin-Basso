from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
import os
import redis
from PIL import Image  # Importar la biblioteca Pillow para manipulación de imágenes
from werkzeug.utils import secure_filename
import requests

# Definir la ruta base del directorio
base_dir = os.path.abspath(os.path.dirname(__file__))

# Cargar las variables de entorno
KV_REST_API_URL = os.getenv('KV_REST_API_URL')
KV_REST_API_TOKEN = os.getenv('KV_REST_API_TOKEN')

# Headers para autenticar con la API REST
headers = {"Authorization": f"Bearer {KV_REST_API_TOKEN}"}

# Crear la aplicación Flask
app = Flask(__name__,
            template_folder=os.path.join(base_dir, 'templates'),  # Ruta completa de templates
            static_folder=os.path.join(base_dir, 'static'))       # Ruta completa de static
app.secret_key = 'supersecretkey'
app.config['UPLOAD_FOLDER'] = 'static/uploads/'  # Carpeta para guardar las imágenes
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# Función para comprimir y guardar la imagen
def compress_image(image_path, quality=30):
    with Image.open(image_path) as img:
        # Comprimir y guardar la imagen
        img = img.convert("RGB")  # Convertir a RGB para evitar problemas de compatibilidad
        img.save(image_path, "JPEG", optimize=True, quality=quality)

# Función para recortar la imagen a una proporción 1:1 (cuadrada)
def crop_image_to_square(image_path):
    """Recorta la imagen a una proporción 1:1 (cuadrada) centrada."""
    with Image.open(image_path) as img:
        width, height = img.size
        # Determinar el tamaño mínimo para hacer el recorte
        min_dimension = min(width, height)
        left = (width - min_dimension) / 2
        top = (height - min_dimension) / 2
        right = (width + min_dimension) / 2
        bottom = (height + min_dimension) / 2
        # Hacer el recorte y guardar la imagen
        img = img.crop((left, top, right, bottom))
        img.save(image_path)

# Función para eliminar la imagen del sistema de archivos
def delete_image(image_path):
    if image_path:
        full_image_path = os.path.abspath(os.path.join(app.config['UPLOAD_FOLDER'], os.path.basename(image_path)))
        if os.path.exists(full_image_path):
            try:
                os.remove(full_image_path)
            except Exception as e:
                print(f"Error al eliminar la imagen: {e}")

# Asegurarse de que la carpeta de subida exista
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# Función para verificar si el archivo tiene una extensión permitida
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Función para generar un nombre de archivo basado en el nombre del producto
def generate_filename(nombre_producto, extension):
    nombre_seguro = secure_filename(nombre_producto).replace(" ", "_").lower()
    return f"{nombre_seguro}.{extension}"

# Función para cargar el inventario usando la API REST
def load_inventory():
    url = f"{KV_REST_API_URL}/scan"
    payload = {"match": "product:*", "count": 100}
    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 200:
            keys = response.json()["result"]
            inventario = []
            for key in keys:
                product_data = requests.get(f"{KV_REST_API_URL}/hgetall/{key}", headers=headers).json()["result"]
                product_data['cantidad'] = int(product_data.get('cantidad', 0))
                product_data['precio'] = float(product_data.get('precio', 0.0))
                product_data['tags'] = product_data.get('tags', "").split(',') if product_data.get('tags') else []
                inventario.append(product_data)
            return inventario
        else:
            print(f"Error al obtener inventario: {response.status_code}, {response.text}")
            return []
    except Exception as e:
        print(f"Error de conexión a la API REST: {e}")
        return []

# Función para guardar un producto en KV Database
def save_product(product):
    key = f"product:{product['id']}"
    product['tags'] = ','.join(product['tags'])  # Convertir la lista de tags a una cadena
    redis_client.hset(key, mapping=product)

# Función para cargar los tags usando la API REST
def load_tags():
    url = f"{KV_REST_API_URL}/lrange/tags/0/-1"
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()["result"]
        else:
            print(f"Error al obtener tags: {response.status_code}, {response.text}")
            return []
    except Exception as e:
        print(f"Error de conexión a la API REST: {e}")
        return []

# Función para guardar los tags en la API REST
def save_tags(tags):
    url_delete = f"{KV_REST_API_URL}/del/tags"
    requests.post(url_delete, headers=headers)  # Eliminar los tags anteriores
    for tag in tags:
        url_push = f"{KV_REST_API_URL}/rpush/tags"
        requests.post(url_push, json={"value": tag}, headers=headers)

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

    inventario = load_inventory()
    for producto in inventario:
        if tag in producto.get('tags', []):
            producto['tags'].remove(tag)
    for product in inventario:
        save_product(product)  # Guardar productos actualizados en la base de datos

    return redirect(url_for('manage_tags'))

# Ruta para agregar productos usando KV Database
@app.route('/add', methods=['GET', 'POST'])
def add_product():
    tags = load_tags()
    if request.method == 'POST':
        inventario = load_inventory()
        new_id = max([int(p['id']) for p in inventario], default=0) + 1
        nombre = request.form['nombre']
        cantidad = int(request.form['cantidad'])
        precio = float(request.form['precio'])
        producto_tags = request.form.getlist('tags')

        # Manejar la carga de la imagen
        file = request.files['foto'] if 'foto' in request.files else None
        imagen = None
        if file and allowed_file(file.filename):
            extension = file.filename.rsplit('.', 1)[1].lower()
            filename = generate_filename(nombre, extension)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            
            # Guardar el archivo original
            file.save(filepath)

            # Recortar y comprimir la imagen
            crop_image_to_square(filepath)
            compress_image(filepath, quality=50)

            # Guardar solo la ruta relativa de la imagen
            imagen = os.path.join('/static/uploads', filename)

        # Crear el nuevo producto con la ruta de la imagen relativa
        new_product = {'id': str(new_id), 'nombre': nombre, 'cantidad': cantidad, 'precio': precio, 'tags': producto_tags, 'imagen': imagen}
        save_product(new_product)
        
        flash('Producto agregado con éxito y guardado en la base de datos KV.', 'success')
        return redirect(url_for('index'))
    return render_template('add_product.html', tags=tags)

# El resto de las rutas se mantiene igual...

if __name__ == '__main__':
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
    app.run(debug=True)
