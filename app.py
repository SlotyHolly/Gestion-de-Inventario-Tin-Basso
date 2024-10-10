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
app.config['UPLOAD_FOLDER'] = '/'  # Carpeta para guardar las imágenes
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# Función para comprimir y guardar la imagen
def compress_image(image, quality=30):
    """Comprime la imagen y la guarda en un objeto de BytesIO."""
    compressed_image = io.BytesIO()
    image.save(compressed_image, "JPEG", optimize=True, quality=quality)
    compressed_image.seek(0)  # Regresar al inicio para poder leerlo
    return compressed_image

# Función para recortar la imagen a una proporción 1:1 (cuadrada)
def crop_image_to_square(image):
    """Recorta la imagen a una proporción 1:1 (cuadrada) centrada."""
    width, height = image.size
    min_dimension = min(width, height)
    left = (width - min_dimension) / 2
    top = (height - min_dimension) / 2
    right = (width + min_dimension) / 2
    bottom = (height + min_dimension) / 2
    return image.crop((left, top, right, bottom))

# Asegurarse de que la carpeta de subida exista
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# Función para eliminar la imagen de S3
def delete_image_from_s3(image_url):
    """Elimina la imagen del bucket de S3 usando la URL proporcionada."""
    if image_url:
        # Obtener el nombre del archivo de la URL
        image_key = image_url.split(f"https://{BUCKET_NAME}.s3.amazonaws.com/")[-1]
        try:
            s3_client.delete_object(Bucket=BUCKET_NAME, Key=image_key)
            print(f"Imagen eliminada exitosamente de S3: {image_key}")
        except Exception as e:
            print(f"Error al eliminar la imagen de S3: {e}")

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
        # Usar lrange para obtener todas las claves de productos almacenadas en una lista
        url = f"{KV_REST_API_URL}/lrange/products/0/-1"
        response = requests.get(url, headers=headers)

        # Mostrar el código de estado de la respuesta para depuración
        print(f"Respuesta de la API REST al obtener claves: {response.status_code}")

        if response.status_code == 200:
            keys = response.json().get('result', [])
            print(f"Claves obtenidas: {keys}")
            
            # Obtener los datos de cada clave
            for key in keys:
                product_data = rest_get(key)
                if product_data:
                    product = eval(product_data)  # Convertir la cadena a diccionario
                    product['cantidad'] = int(product['cantidad'])
                    product['precio'] = float(product['precio'])
                    product['tags'] = product['tags'].split(',') if product['tags'] else []

                    # Si el producto tiene una imagen, obtener la URL de S3
                    if 'imagen' in product and product['imagen']:
                        product['imagen'] = f'https://{BUCKET_NAME}.s3.amazonaws.com/{product["imagen"]}'
                    
                    inventario.append(product)
            print(f"Inventario cargado: {inventario}")
        else:
            print(f"Error al obtener inventario con LRANGE: {response.status_code}, {response.text}")

    except Exception as e:
        print(f"Error de conexión o problema al cargar el inventario: {e}")

    return inventario

# Función para obtener los datos de una clave específica utilizando la API REST de Upstash
def rest_get(key):
    url = f"{KV_REST_API_URL}/get/{key}"
    print(f"Obteniendo datos de {key} con URL: {url}")
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            print(f"Datos obtenidos para {key}: {response.json()['result']}")
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
            
            # Agregar la clave del producto a la lista "products"
            url_push = f"{KV_REST_API_URL}/rpush/products"
            requests.post(url_push, json={"value": key}, headers=headers)
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
                imagen = f'https://{BUCKET_NAME}.s3.amazonaws.com/{filename}'

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

# Ruta para manejar la eliminación de productos y eliminar las imágenes de S3
@app.route('/delete/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    inventario = load_inventory()
    producto_a_eliminar = next((p for p in inventario if p['id'] == product_id), None)

    if producto_a_eliminar:
        # Eliminar la imagen de S3 si existe
        if 'imagen' in producto_a_eliminar and producto_a_eliminar['imagen']:
            delete_image_from_s3(producto_a_eliminar['imagen'])

        # Eliminar el producto de la base de datos
        key = f"product:{product_id}"
        url = f"{KV_REST_API_URL}/del/{key}"
        response = requests.post(url, headers=headers)
        if response.status_code == 200:
            flash('Producto eliminado exitosamente.', 'success')
        else:
            flash(f'Error al eliminar el producto: {response.status_code}, {response.text}', 'danger')
    else:
        flash('Producto no encontrado.', 'danger')

    return redirect(url_for('index'))

if __name__ == '__main__':
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
    app.run(debug=True)
