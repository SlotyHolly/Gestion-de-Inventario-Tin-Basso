from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
import os
import redis
from PIL import Image  # Importar la biblioteca Pillow para manipulación de imágenes
from werkzeug.utils import secure_filename

# Definir la ruta base del directorio
base_dir = os.path.abspath(os.path.dirname(__file__))

# Cargar las variables de entorno de conexión desde Vercel
REDIS_URL = os.getenv('KV_URL')  # Usar la variable de entorno para la URL de conexión

# Configurar la conexión a Redis (KV Database)
redis_client = redis.StrictRedis.from_url(REDIS_URL, decode_responses=True)

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

# Función para cargar el inventario desde KV Database
def load_inventory():
    keys = redis_client.keys("product:*")
    inventario = []
    for key in keys:
        product_data = redis_client.hgetall(key)  # Obtener el hash de cada producto
        product_data['cantidad'] = int(product_data['cantidad'])
        product_data['precio'] = float(product_data['precio'])
        product_data['tags'] = product_data['tags'].split(',') if product_data['tags'] else []
        inventario.append(product_data)
    return inventario

# Función para guardar un producto en KV Database
def save_product(product):
    key = f"product:{product['id']}"
    product['tags'] = ','.join(product['tags'])  # Convertir la lista de tags a una cadena
    redis_client.hset(key, mapping=product)

# Función para cargar los tags desde KV Database
def load_tags():
    tags = redis_client.lrange("tags", 0, -1)
    return tags

# Función para guardar los tags en KV Database
def save_tags(tags):
    redis_client.delete("tags")
    for tag in tags:
        redis_client.rpush("tags", tag)

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
