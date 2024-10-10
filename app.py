from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
import os
import redis
from PIL import Image  # Importar la biblioteca Pillow para manipulación de imágenes
from werkzeug.utils import secure_filename
import requests
import io
import boto3

# Definir la ruta base del directorio
base_dir = os.path.abspath(os.path.dirname(__file__))

# Configurar el cliente S3
s3_client = boto3.client(
    's3',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_REGION')  # Cambia esto a la región que estés usando
)

BUCKET_NAME = os.getenv('BUCKET_S3_NAME')  # Cambia esto al nombre de tu bucket de S3

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

# Cambiar la función para aceptar un objeto de imagen en lugar de una ruta de archivo
def crop_image_to_square(image):
    """Recorta la imagen a una proporción 1:1 (cuadrada) centrada."""
    width, height = image.size
    # Determinar el tamaño mínimo para hacer el recorte
    min_dimension = min(width, height)
    left = (width - min_dimension) / 2
    top = (height - min_dimension) / 2
    right = (width + min_dimension) / 2
    bottom = (height + min_dimension) / 2
    # Hacer el recorte y devolver la imagen
    return image.crop((left, top, right, bottom))

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

def load_inventory():
    inventario = []
    try:
        # Hacer una solicitud a la API REST para obtener las claves de los productos
        url = f"{KV_REST_API_URL}/keys?pattern=product:*"
        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            keys = response.json().get('result', [])
            for key in keys:
                product_data = rest_get(key)
                if product_data:
                    product = eval(product_data)  # Convertir la cadena a diccionario
                    product['cantidad'] = int(product['cantidad'])
                    product['precio'] = float(product['precio'])
                    product['tags'] = product['tags'].split(',') if product['tags'] else []
                    inventario.append(product)
        else:
            print(f"Error al obtener inventario: {response.status_code}, {response.text}")
    except Exception as e:
        print(f"Error de conexión o problema al cargar el inventario: {e}")
    
    return inventario


# Función para obtener los datos de una clave específica utilizando la API REST de Upstash
def rest_get(key):
    url = f"{KV_REST_API_URL}/get/{key}"
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()["result"]
        else:
            print(f"Error al obtener {key}: {response.status_code}, {response.text}")
            return None
    except Exception as e:
        print(f"Error de conexión a la API REST al obtener {key}: {e}")
        return None

# Función para guardar un producto usando la API REST
def save_product(product):
    key = f"product:{product['id']}"
    product['tags'] = ','.join(product['tags'])  # Convertir la lista de tags a una cadena
    
    # Guardar el producto usando la API REST
    url = f"{KV_REST_API_URL}/set/{key}"
    try:
        response = requests.post(url, json={"value": str(product)}, headers=headers)
        if response.status_code == 200:
            print(f"Producto {key} guardado exitosamente.")
        else:
            print(f"Error al guardar {key}: {response.status_code}, {response.text}")
    except Exception as e:
        print(f"Error de conexión a la API REST al guardar {key}: {e}")

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

@app.route('/manage_tags', methods=['GET', 'POST'])
def manage_tags():
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

        # Manejar la carga de la imagen usando io.BytesIO
        file = request.files['foto'] if 'foto' in request.files else None
        imagen = None
        if file and allowed_file(file.filename):
            extension = file.filename.rsplit('.', 1)[1].lower()
            filename = generate_filename(nombre, extension)
            
            # Leer el contenido del archivo y manipularlo en memoria
            image_stream = io.BytesIO(file.read())

            try:
                # Abrir la imagen para manipularla
                image = Image.open(image_stream)
                image = crop_image_to_square(image)  # Recortar a proporción 1:1

                # Comprimir la imagen y guardarla en un nuevo stream de bytes
                compressed_image = io.BytesIO()
                image.save(compressed_image, format='JPEG', optimize=True, quality=50)

                # Volver a poner el puntero al inicio para poder leer el archivo
                compressed_image.seek(0)

                # Subir la imagen a S3 usando boto3
                s3_client.upload_fileobj(
                    compressed_image,
                    BUCKET_NAME,
                    f'static/uploads/{filename}',
                    ExtraArgs={'ContentType': 'image/jpeg'}
                )

                # Construir la URL de la imagen subida
                imagen = f'https://{BUCKET_NAME}.s3.amazonaws.com/static/uploads/{filename}'

                # Mostrar un mensaje de éxito en la consola para depuración
                print(f"Imagen subida exitosamente a S3: {imagen}")

            except Exception as e:
                print(f"Error al subir la imagen a S3: {e}")
                flash('Hubo un error al subir la imagen a S3. Por favor, intenta de nuevo.', 'danger')
                return redirect(url_for('add_product'))

        # Crear el nuevo producto con la URL de la imagen
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
